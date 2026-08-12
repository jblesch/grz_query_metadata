#!/usr/bin/env python3
"""
Survey controlled-vocabulary usage in GRZ submission metadata.

Reads the `submissions` table of a GRZ internal submission database and counts
how often each value of each surveyed field occurs. Works against SQLite and
PostgreSQL alike: the metadata JSON is selected as a whole and inspected in
Python, so no dialect-specific JSON SQL is involved.

Emits a single JSON report. The report contains counts and, for technical
fields, the distinct values found. It contains no tanG, no pseudonym, no
localCaseId, no file paths and no dates.

Usage
-----
    python survey_grz_metadata.py --db-url sqlite:////path/to/submission.db.sqlite
    python survey_grz_metadata.py --db-url postgresql://user@host/grzdb

    # read the URL from a grz config file instead
    python survey_grz_metadata.py --config-file /etc/grz/config.yaml

Requires: sqlalchemy (already a grz-tools dependency). PyYAML only if
--config-file is used.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import re
import sys
from typing import Any

SCRIPT_VERSION = "1.1.0"

# --------------------------------------------------------------------------
# What to survey.
#
# ENUM_FIELDS  - controlled vocabularies in the current schema. Values are
#                safe to report verbatim; that is the whole point.
# FREETEXT_FIELDS - uncontrolled today. Distinct values are reported so that
#                coverage against a proposed vocabulary can be measured.
#                REVIEW THESE BEFORE SHARING (see --redact-freetext).
# --------------------------------------------------------------------------

ENUM_FIELDS: dict[str, str] = {
    "submission.submissionType": "submission/submissionType",
    "submission.coverageType": "submission/coverageType",
    "submission.diseaseType": "submission/diseaseType",
    "submission.genomicStudyType": "submission/genomicStudyType",
    "submission.genomicStudySubtype": "submission/genomicStudySubtype",
    "donors.gender": "donors[]/gender",
    "donors.relation": "donors[]/relation",
    "researchConsents.noScopeJustification": "donors[]/researchConsents[]/noScopeJustification",
    "labData.sampleConservation": "donors[]/labData[]/sampleConservation",
    "labData.sequenceType": "donors[]/labData[]/sequenceType",
    "labData.sequenceSubtype": "donors[]/labData[]/sequenceSubtype",
    "labData.fragmentationMethod": "donors[]/labData[]/fragmentationMethod",
    "labData.libraryType": "donors[]/labData[]/libraryType",
    "labData.enrichmentKitManufacturer": "donors[]/labData[]/enrichmentKitManufacturer",
    "labData.sequencingLayout": "donors[]/labData[]/sequencingLayout",
    "tumorCellCount.method": "donors[]/labData[]/tumorCellCount[]/method",
    "sequenceData.referenceGenome": "donors[]/labData[]/sequenceData/referenceGenome",
    "files.fileType": "donors[]/labData[]/sequenceData/files[]/fileType",
    "files.readOrder": "donors[]/labData[]/sequenceData/files[]/readOrder",
    "files.checksumType": "donors[]/labData[]/sequenceData/files[]/checksumType",
}

FREETEXT_FIELDS: dict[str, str] = {
    "labData.tissueOntology.name": "donors[]/labData[]/tissueOntology/name",
    "labData.tissueOntology.version": "donors[]/labData[]/tissueOntology/version",
    "labData.tissueTypeId": "donors[]/labData[]/tissueTypeId",
    "labData.tissueTypeName": "donors[]/labData[]/tissueTypeName",
    "labData.libraryPrepKit": "donors[]/labData[]/libraryPrepKit",
    "labData.libraryPrepKitManufacturer": "donors[]/labData[]/libraryPrepKitManufacturer",
    "labData.sequencerModel": "donors[]/labData[]/sequencerModel",
    "labData.sequencerManufacturer": "donors[]/labData[]/sequencerManufacturer",
    "labData.kitName": "donors[]/labData[]/kitName",
    "labData.kitManufacturer": "donors[]/labData[]/kitManufacturer",
    "labData.enrichmentKitDescription": "donors[]/labData[]/enrichmentKitDescription",
    "labData.labDataName": "donors[]/labData[]/labDataName",
    "sequenceData.bioinformaticsPipelineName": "donors[]/labData[]/sequenceData/bioinformaticsPipelineName",
    "callerUsed.name": "donors[]/labData[]/sequenceData/callerUsed[]/name",
}

BTO_ID = re.compile(r"^BTO:[0-9]{7}$")


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
    if head.endswith("[]"):
        key = head[:-2]
        seq = node.get(key) if isinstance(node, dict) else None
        if isinstance(seq, list):
            for item in seq:
                yield from walk(item, rest)
    else:
        if isinstance(node, dict) and head in node:
            yield from walk(node[head], rest)


def collect(meta: dict, path: str):
    return [v for v in walk(meta, path.split("/")) if v is not None]


# --------------------------------------------------------------------------
# Derived checks: things a plain value count cannot answer
# --------------------------------------------------------------------------

def derived_metrics(meta: dict, d: dict[str, collections.Counter]) -> None:
    donors = meta.get("donors") or []

    for ld in (ld for dn in donors for ld in (dn.get("labData") or [])):
        # --- tissueTypeId: does it look like a BTO identifier? ---
        tid = ld.get("tissueTypeId")
        if tid is not None:
            d["tissueTypeId_is_BTO_format"]["yes" if BTO_ID.match(str(tid)) else "no"] += 1


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def as_url(value: str) -> str:
    """Accept either a SQLAlchemy URL or a plain path to a SQLite file."""
    if "://" in value:
        return value
    path = os.path.abspath(os.path.expanduser(value))
    if not os.path.exists(path):
        sys.exit(f"no such file: {path}\n"
                 f"(pass a SQLAlchemy URL such as postgresql://user@host/db "
                 f"if this is not a SQLite file)")
    return f"sqlite:///{path}"


def resolve_db_url(args) -> str:
    if args.db_url:
        return as_url(args.db_url)
    import yaml  # only needed on this path

    with open(args.config_file, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    url = (cfg.get("db") or {}).get("database_url")
    if not url:
        sys.exit(f"no db.database_url found in {args.config_file}")
    return as_url(url)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--db-url", help="SQLAlchemy URL, e.g. sqlite:///... or postgresql://...")
    src.add_argument("--config-file", help="grz config file containing db.database_url")
    ap.add_argument("--grz-id", default=None,
                    help="optional label for your site, e.g. GRZK00123. Only used to name "
                         "the report and label its column during aggregation; if omitted, "
                         "the report filename is used instead.")
    ap.add_argument("--out", default=None, help="output file (default: grz-survey-<grzid>-<date>.json)")
    ap.add_argument(
        "--redact-freetext",
        action="store_true",
        help="report only counts for free-text fields, not the values themselves",
    )
    ap.add_argument("--max-freetext-values", type=int, default=500,
                    help="cap distinct free-text values reported per field (default 500)")
    args = ap.parse_args()

    from sqlalchemy import create_engine, text

    engine = create_engine(resolve_db_url(args))
    counters: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
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

            for label, path in ENUM_FIELDS.items():
                for v in collect(meta, path):
                    counters[label][str(v)] += 1
            for label, path in FREETEXT_FIELDS.items():
                for v in collect(meta, path):
                    counters[label]["<value>" if args.redact_freetext else str(v)] += 1
            derived_metrics(meta, counters)

    def dump(labels):
        out = {}
        for label in labels:
            c = counters.get(label)
            if not c:
                out[label] = {"_total": 0, "_distinct": 0, "values": {}}
                continue
            items = c.most_common()
            capped = items[: args.max_freetext_values]
            out[label] = {
                "_total": sum(c.values()),
                "_distinct": len(c),
                "_truncated": len(items) > len(capped),
                "values": dict(capped),
            }
        return out

    report = {
        "script_version": SCRIPT_VERSION,
        "grz_id": args.grz_id,
        "generated": datetime.date.today().isoformat(),
        "submissions_in_table": n_rows,
        "submissions_with_metadata": n_with_metadata,
        "submissions_unparseable": n_unparseable,
        "freetext_redacted": args.redact_freetext,
        "enum_fields": dump(ENUM_FIELDS),
        "freetext_fields": dump(FREETEXT_FIELDS),
        "derived": dump(sorted(set(counters) - set(ENUM_FIELDS) - set(FREETEXT_FIELDS))),
    }

    out = args.out or (
        f"grz-survey-{args.grz_id}-{report['generated']}.json"
        if args.grz_id else f"grz-survey-{report['generated']}.json"
    )
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False, sort_keys=True)

    print(f"{n_with_metadata} of {n_rows} submissions had metadata; wrote {out}")
    if n_unparseable:
        print(f"warning: {n_unparseable} rows had metadata that could not be parsed", file=sys.stderr)
    print("\nPlease review the file before sharing, in particular freetext_fields.")


if __name__ == "__main__":
    main()
