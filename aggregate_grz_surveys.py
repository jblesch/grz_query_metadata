#!/usr/bin/env python3
"""
Aggregate per-GRZ survey reports into one workbook.

Takes the grz-survey-*.json files produced by survey_grz_metadata.py and writes
an .xlsx with one sheet per surveyed field: values down the rows, GRZs across
the columns, totals and share of all observations.

Optionally checks the free-text kit and instrument fields against a proposed
controlled vocabulary, so you can see what share of real values a candidate
enum would actually cover.

Usage
-----
    python aggregate_grz_surveys.py grz-survey-*.json -o schema-usage.xlsx

    # also measure coverage of the proposed vocabularies
    python aggregate_grz_surveys.py grz-survey-*.json -o schema-usage.xlsx \\
        --vocab labData.sequencerModel=GRZ/vocabularies/instrument-model.json \\
        --vocab labData.libraryPrepKit=GRZ/vocabularies/library-preparation-kit-retail-name.json

Requires: openpyxl
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEAD = Font(bold=True)
WARN = PatternFill("solid", fgColor="FFF2CC")
BAD = PatternFill("solid", fgColor="F8CECC")


def normalise(v: str) -> str:
    """Loose key for comparing free text against a controlled value."""
    return re.sub(r"[^a-z0-9]+", "", v.lower())


def sheet_name(label: str) -> str:
    # Excel: max 31 chars, no []:*?/\
    s = re.sub(r"[\[\]:*?/\\]", "", label)
    return s[-31:]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reports", nargs="+", help="grz-survey-*.json files")
    ap.add_argument("-o", "--out", default="schema-usage.xlsx")
    ap.add_argument("--vocab", action="append", default=[],
                    help="FIELD=path/to/vocabulary.json, repeatable")
    args = ap.parse_args()

    reports = []
    for p in args.reports:
        with open(p, encoding="utf-8") as fh:
            reports.append(json.load(fh))
    reports.sort(key=lambda r: r["grz_id"])
    grzs = [r["grz_id"] for r in reports]
    if len(set(grzs)) != len(grzs):
        print(f"warning: duplicate grz_id among inputs: {grzs}", file=sys.stderr)

    vocabs = {}
    for spec in args.vocab:
        field, _, path = spec.partition("=")
        with open(path, encoding="utf-8") as fh:
            vocabs[field] = {normalise(v) for v in json.load(fh)["enum"]}

    wb = Workbook()
    wb.remove(wb.active)

    # ---- summary -----------------------------------------------------
    ws = wb.create_sheet("summary")
    ws.append(["GRZ", "submissions in table", "with metadata", "unparseable",
               "script version", "generated", "free text redacted"])
    for c in ws[1]:
        c.font = HEAD
    for r in reports:
        ws.append([r["grz_id"], r["submissions_in_table"], r["submissions_with_metadata"],
                   r["submissions_unparseable"], r["script_version"], r["generated"],
                   "yes" if r.get("freetext_redacted") else "no"])
    ws.append([])
    ws.append(["TOTAL", sum(r["submissions_in_table"] for r in reports),
               sum(r["submissions_with_metadata"] for r in reports),
               sum(r["submissions_unparseable"] for r in reports)])
    ws[ws.max_row][0].font = HEAD
    versions = {r["script_version"] for r in reports}
    if len(versions) > 1:
        ws.append([])
        ws.append([f"WARNING: reports produced by different script versions: {sorted(versions)}"])
        ws[ws.max_row][0].fill = BAD

    # ---- one sheet per field ----------------------------------------
    sections = ("enum_fields", "freetext_fields", "derived")
    fields: list[tuple[str, str]] = []
    for sec in sections:
        for label in sorted({k for r in reports for k in r.get(sec, {})}):
            fields.append((sec, label))

    index = wb.create_sheet("index")
    index.append(["section", "field", "distinct values", "observations", "sheet"])
    for c in index[1]:
        c.font = HEAD

    for sec, label in fields:
        per_grz = {r["grz_id"]: r.get(sec, {}).get(label, {}).get("values", {}) for r in reports}
        values = sorted({v for d in per_grz.values() for v in d},
                        key=lambda v: -sum(d.get(v, 0) for d in per_grz.values()))
        total_obs = sum(sum(d.values()) for d in per_grz.values())
        name = sheet_name(label)
        index.append([sec, label, len(values), total_obs, name])

        ws = wb.create_sheet(name)
        header = ["value", *grzs, "TOTAL", "share"]
        if label in vocabs:
            header.append("in proposed vocabulary")
        ws.append(header)
        for c in ws[1]:
            c.font = HEAD
        ws.freeze_panes = "B2"

        for v in values:
            row = [v] + [per_grz[g].get(v, 0) for g in grzs]
            tot = sum(row[1:])
            row.append(tot)
            row.append(round(tot / total_obs, 4) if total_obs else 0)
            if label in vocabs:
                row.append("yes" if normalise(v) in vocabs[label] else "NO")
            ws.append(row)
            if label in vocabs and row[-1] == "NO":
                for c in ws[ws.max_row]:
                    c.fill = WARN

        ws.append([])
        ws.append(["TOTAL", *[sum(per_grz[g].values()) for g in grzs], total_obs])
        ws[ws.max_row][0].font = HEAD
        for i in range(1, len(header) + 1):
            ws.column_dimensions[get_column_letter(i)].width = 46 if i == 1 else 16
        ws["A1"].alignment = Alignment(horizontal="left")

        if label in vocabs:
            covered = sum(sum(per_grz[g].get(v, 0) for g in grzs)
                          for v in values if normalise(v) in vocabs[label])
            ws.append([])
            ws.append(["coverage by proposed vocabulary",
                       f"{covered}/{total_obs} observations",
                       f"{round(100 * covered / total_obs, 1) if total_obs else 0}%"])
            ws[ws.max_row][0].font = HEAD

    wb.save(args.out)
    print(f"wrote {args.out}: {len(fields)} field sheets from {len(reports)} GRZ report(s)")
    for field in vocabs:
        print(f"  vocabulary coverage checked for {field}")


if __name__ == "__main__":
    main()
