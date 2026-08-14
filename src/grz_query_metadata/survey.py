"""Survey controlled-vocabulary usage in GRZ submission metadata.

Reads the `submissions` table of a GRZ internal submission database and counts
how often each value of each surveyed field occurs. Works against SQLite and
PostgreSQL alike: the metadata JSON is selected as a whole and inspected in
Python, so no dialect-specific JSON SQL is involved.

Emits a single JSON report. The report contains counts and, for technical
fields, the distinct values found. It contains no tanG, no pseudonym, no
localCaseId, no file paths and no dates.

Usage
-----
    grz-survey-metadata --db-url sqlite:////path/to/submission.db.sqlite
    grz-survey-metadata --db-url postgresql://user@host/grzdb

    # read the URL from a grz config file instead
    grz-survey-metadata --config-file /etc/grz/config.yaml
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import yaml
from sqlalchemy import create_engine, text

from . import __version__
from .fields import BTO_ID, ENUM_FIELDS, FREETEXT_FIELDS, split_segment

Counters = dict[str, collections.Counter[str]]

# Every submission records the GRZ that received it, so the report can label
# itself instead of asking for the id to be retyped. This is the site's own
# identifier — submitterId, which identifies the submitting institution, is
# deliberately never read.
GRZ_ID_PATH = "submission/genomicDataCenterId"


# --------------------------------------------------------------------------
# JSON path walking
# --------------------------------------------------------------------------


def walk(node: Any, parts: list[str]):
    """Yield every value reachable by `parts`, descending into [] segments."""
    if node is None:
        return
    if not parts:
        yield node
        return
    head, rest = parts[0], parts[1:]
    key, is_array = split_segment(head)
    if is_array:
        seq = node.get(key) if isinstance(node, dict) else None
        if isinstance(seq, list):
            for item in seq:
                yield from walk(item, rest)
    else:
        if isinstance(node, dict) and key in node:
            yield from walk(node[key], rest)


def collect(meta: dict, path: str) -> list[Any]:
    return [v for v in walk(meta, path.split("/")) if v is not None]


# --------------------------------------------------------------------------
# Derived checks: things a plain value count cannot answer
# --------------------------------------------------------------------------


def derived_metrics(meta: dict, d: Counters) -> None:
    # --- tissueTypeId: does it look like a BTO identifier? ---
    # collect() rather than a hand-rolled walk: it shrugs off malformed shapes
    # (a null donor, labData not a list) exactly like the field counting does,
    # and it reads the path from the same table, so the two cannot diverge.
    for tid in collect(meta, FREETEXT_FIELDS["labData.tissueTypeId"]):
        d["tissueTypeId_is_BTO_format"]["yes" if BTO_ID.match(str(tid)) else "no"] += 1


# --------------------------------------------------------------------------
# Counting
# --------------------------------------------------------------------------


def count_submission(meta: dict, counters: Counters) -> None:
    """Fold one submission's metadata document into `counters`."""
    for label, path in (*ENUM_FIELDS.items(), *FREETEXT_FIELDS.items()):
        for v in collect(meta, path):
            counters[label][str(v)] += 1
    derived_metrics(meta, counters)


def dump(counters: Counters, labels: Iterable[str]) -> dict[str, dict]:
    """Render the counters for `labels`, most common value first."""
    out: dict[str, dict] = {}
    for label in labels:
        c = counters.get(label)
        if not c:
            out[label] = {"_total": 0, "_distinct": 0, "values": {}}
            continue
        out[label] = {
            "_total": sum(c.values()),
            "_distinct": len(c),
            "values": dict(c.most_common()),
        }
    return out


@dataclass
class SurveyResult:
    """What one pass over a submissions table yields."""

    counters: Counters
    n_rows: int  # rows in the table
    n_with_metadata: int  # rows carrying a usable metadata document
    n_unparseable: int  # rows whose metadata could not be parsed
    grz_ids: collections.Counter[str]  # genomicDataCenterId values seen, with counts


def survey(db_url: str) -> SurveyResult:
    """Count every surveyed field across the `submissions` table."""
    engine = create_engine(db_url)
    counters: Counters = collections.defaultdict(collections.Counter)
    grz_ids: collections.Counter[str] = collections.Counter()
    n_rows = n_with_metadata = n_unparseable = 0

    with engine.connect() as conn:
        # No JSON SQL: the driver hands back dict (JSON/JSONB) or str (older rows).
        result = conn.execute(text("SELECT id, submission_metadata FROM submissions"))
        for _sid, meta in result:
            n_rows += 1
            if meta is None:
                continue
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except json.JSONDecodeError:
                    n_unparseable += 1
                    continue
            if not isinstance(meta, dict):
                n_unparseable += 1
                continue
            n_with_metadata += 1
            count_submission(meta, counters)
            grz_ids.update(str(v) for v in collect(meta, GRZ_ID_PATH))

    return SurveyResult(counters, n_rows, n_with_metadata, n_unparseable, grz_ids)


def resolve_grz_id(seen: collections.Counter[str], override: str | None = None) -> tuple[str, str]:
    """The site id for the report, and where it came from.

    The submissions record it themselves, so it is read out of the data rather
    than retyped. `--grz-id` overrides that, and is needed when the database
    holds no id at all or — which would be worth investigating — the
    submissions of more than one GRZ.
    """
    if override:
        return override, "--grz-id"
    if not seen:
        sys.exit(
            f"no {GRZ_ID_PATH} found in any submission of this database.\n"
            f"Pass --grz-id GRZKxxxxx to label the report yourself."
        )
    if len(seen) > 1:
        found = ", ".join(f"{gid} ({n})" for gid, n in seen.most_common())
        sys.exit(
            f"this database holds submissions from more than one GRZ: {found}.\n"
            f"Pass --grz-id GRZKxxxxx to say which one this report is for."
        )
    return next(iter(seen)), GRZ_ID_PATH


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def as_url(value: str) -> str:
    """Accept either a SQLAlchemy URL or a plain path to a SQLite file."""
    if "://" in value:
        return value
    path = os.path.abspath(os.path.expanduser(value))
    if not os.path.exists(path):
        sys.exit(
            f"no such file: {path}\n"
            f"(pass a SQLAlchemy URL such as postgresql://user@host/db "
            f"if this is not a SQLite file)"
        )
    return f"sqlite:///{path}"


def resolve_db_url(db_url: str | None = None, config_file: str | None = None) -> str:
    """The database URL, taken from `db_url` or from a grz config file."""
    if db_url:
        return as_url(db_url)
    if not config_file:
        sys.exit("either db_url or config_file is required")
    with open(config_file, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    url = (cfg.get("db") or {}).get("database_url")
    if not url:
        sys.exit(f"no db.database_url found in {config_file}")
    return as_url(url)


def build_report(result: SurveyResult, grz_id: str, grz_id_source: str = GRZ_ID_PATH) -> dict:
    """The JSON document a GRZ sends back."""
    counters = result.counters
    return {
        "script_version": __version__,
        "grz_id": grz_id,
        # Read out of the submissions, or overridden on the command line. Worth
        # recording, since only one of the two can have been mistyped.
        "grz_id_source": grz_id_source,
        "generated": datetime.date.today().isoformat(),
        "submissions_in_table": result.n_rows,
        "submissions_with_metadata": result.n_with_metadata,
        "submissions_unparseable": result.n_unparseable,
        "enum_fields": dump(counters, ENUM_FIELDS),
        "freetext_fields": dump(counters, FREETEXT_FIELDS),
        "derived": dump(counters, sorted(set(counters) - set(ENUM_FIELDS) - set(FREETEXT_FIELDS))),
    }


def report_filename(generated: str, grz_id: str) -> str:
    return f"grz-survey-{grz_id}-{generated}.json"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="grz-survey-metadata",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--db-url", help="SQLAlchemy URL, e.g. sqlite:///... or postgresql://...")
    src.add_argument("--config-file", help="grz config file containing db.database_url")
    ap.add_argument(
        "--grz-id",
        default=None,
        help=f"your site id, e.g. GRZK00123. Only needed to override what the "
        f"submissions themselves record in {GRZ_ID_PATH}, or to supply it when "
        f"they record nothing.",
    )
    ap.add_argument("--out", default=None, help="output file (default: grz-survey-<grzid>-<date>.json)")
    return ap


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    db_url = resolve_db_url(args.db_url, args.config_file)
    result = survey(db_url)
    grz_id, source = resolve_grz_id(result.grz_ids, args.grz_id)
    report = build_report(result, grz_id, source)

    out = args.out or report_filename(report["generated"], grz_id)
    with open(out, "w", encoding="utf-8") as fh:
        # No sort_keys: it would alphabetise the values sections and destroy
        # the most-common-first ordering that makes the human review possible.
        # The report is built deterministically, so the file diffs fine as is.
        json.dump(report, fh, indent=2, ensure_ascii=False)

    print(f"reporting as {grz_id} (from {source})")
    print(f"{result.n_with_metadata} of {result.n_rows} submissions had metadata; wrote {out}")
    if result.n_unparseable:
        print(
            f"warning: {result.n_unparseable} rows had metadata that could not be parsed",
            file=sys.stderr,
        )
    print(
        "\nOpen the file and read it before you share it. The freetext_fields section "
        "contains the values themselves, and labDataName in particular is free text "
        "that could name a person. Delete anything that should not leave your site."
    )


if __name__ == "__main__":
    main()
