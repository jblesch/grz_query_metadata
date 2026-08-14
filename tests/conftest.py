from __future__ import annotations

import itertools
import json

import pytest
from odf import teletype
from odf.opendocument import load
from odf.table import Table, TableCell, TableRow
from odf.text import P
from sqlalchemy import create_engine, text


def _read_ods(path) -> dict[str, list[list]]:
    """Every sheet of an .ods as plain rows, numbers as numbers."""
    sheets = {}
    for table in load(str(path)).spreadsheet.getElementsByType(Table):
        rows = []
        for row in table.getElementsByType(TableRow):
            cells = []
            for cell in row.getElementsByType(TableCell):
                if cell.getAttribute("valuetype") == "float":
                    number = float(cell.getAttribute("value"))
                    cells.append(int(number) if number == int(number) else number)
                else:
                    text = "".join(teletype.extractText(p) for p in cell.getElementsByType(P))
                    cells.append(text or None)
            rows.append(cells)
        sheets[table.getAttribute("name")] = rows
    return sheets


def _cell_styles(path, sheet: str) -> list[list[str | None]]:
    """The style name on each cell of a sheet, row by row."""
    for table in load(str(path)).spreadsheet.getElementsByType(Table):
        if table.getAttribute("name") != sheet:
            continue
        return [
            [c.getAttribute("stylename") for c in row.getElementsByType(TableCell)]
            for row in table.getElementsByType(TableRow)
        ]
    raise KeyError(sheet)


@pytest.fixture
def read_ods():
    """Read an .ods into {sheet name: rows}."""
    return _read_ods


@pytest.fixture
def cell_styles():
    """Read the style name of every cell of one sheet: (path, sheet) -> rows."""
    return _cell_styles


def make_submission(
    *,
    library_type: str = "wgs",
    tissue_type_id: str = "BTO:0000089",
    sequencer_model: str = "Illumina NovaSeq 6000",
    grz_id: str | None = "GRZK00123",
) -> dict:
    """A metadata document reduced to the parts the survey actually reads."""
    return {
        "submission": {
            **({"genomicDataCenterId": grz_id} if grz_id else {}),
            "submissionType": "initial",
            "coverageType": "GKV",
            "diseaseType": "oncological",
            "genomicStudyType": "single",
            "genomicStudySubtype": "tumor-only",
        },
        "donors": [
            {
                "gender": "female",
                "relation": "index",
                "researchConsents": [{"noScopeJustification": "not-asked"}],
                "labData": [
                    {
                        "labDataName": "Blut DNA",
                        "libraryType": library_type,
                        "sequencingLayout": "paired-end",
                        "sequencerModel": sequencer_model,
                        "tissueTypeId": tissue_type_id,
                        "tissueOntology": {"name": "BRENDA", "version": "2024"},
                        "tumorCellCount": [{"method": "pathology"}],
                        "sequenceData": {
                            "referenceGenome": "GRCh38",
                            "files": [
                                {"fileType": "fastq", "readOrder": "R1", "checksumType": "sha256"},
                                {"fileType": "fastq", "readOrder": "R2", "checksumType": "sha256"},
                            ],
                        },
                    }
                ],
            }
        ],
    }


@pytest.fixture
def submission():
    """Factory for the metadata document above; keyword args vary one field."""
    return make_submission


@pytest.fixture
def schema_dir(tmp_path_factory):
    """A miniature GRZ schema exercising each shape declared_enum must handle."""
    root = tmp_path_factory.mktemp("schema")
    (root / "vocabularies").mkdir()
    (root / "vocabularies" / "instrument-model.json").write_text(
        json.dumps({"enum": ["NovaSeq 6000", "NextSeq 2000"]})
    )
    (root / "grz-schema.json").write_text(
        json.dumps(
            {
                "properties": {
                    "submission": {"$ref": "#/$defs/Submission"},
                    "donors": {"type": "array", "items": {"$ref": "#/$defs/Donor"}},
                },
                "$defs": {
                    "Submission": {"properties": {"coverageType": {"enum": ["GKV", "PKV"]}}},
                    "Donor": {
                        "properties": {
                            "labData": {"type": "array", "items": {"$ref": "#/$defs/LabDatum"}},
                        }
                    },
                    "LabDatum": {
                        "properties": {
                            "sequencerModel": {"$ref": "vocabularies/instrument-model.json"},
                            "labDataName": {"type": "string"},
                        },
                        "allOf": [{"properties": {"libraryType": {"enum": ["wgs", "wes"]}}}],
                    },
                },
            }
        )
    )
    return root


def make_db(path, submissions: list[dict | None | str]):
    """A submissions table holding exactly `submissions`, JSON-encoded."""
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE submissions (id INTEGER PRIMARY KEY, submission_metadata TEXT)"))
        conn.execute(
            text("INSERT INTO submissions (id, submission_metadata) VALUES (:i, :m)"),
            [
                {"i": i, "m": m if m is None or isinstance(m, str) else json.dumps(m)}
                for i, m in enumerate(submissions, start=1)
            ],
        )
    return path


@pytest.fixture
def sqlite_db(tmp_path):
    """Two usable submissions, one NULL row and one that will not parse."""
    return make_db(
        tmp_path / "submission.db.sqlite",
        [make_submission(), make_submission(library_type="wxs"), None, "{not json"],
    )


@pytest.fixture
def db_factory(tmp_path):
    """Build a submissions table from a list of metadata documents."""
    counter = itertools.count()

    def build(submissions):
        return make_db(tmp_path / f"db-{next(counter)}.sqlite", submissions)

    return build
