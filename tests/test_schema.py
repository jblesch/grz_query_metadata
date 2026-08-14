from __future__ import annotations

import json

import pytest

from grz_query_metadata.schema import declared_enum, enum_paths


def enum_at(schema_dir, path):
    with open(schema_dir / "grz-schema.json", encoding="utf-8") as fh:
        root = json.load(fh)
    return declared_enum(root, schema_dir, path)


def test_local_ref(schema_dir):
    assert enum_at(schema_dir, "submission/coverageType") == ["GKV", "PKV"]


def test_descends_through_arrays(schema_dir):
    assert enum_at(schema_dir, "donors[]/labData[]/libraryType") == ["wgs", "wes"]


def test_follows_a_ref_into_a_vocabulary_file(schema_dir):
    assert enum_at(schema_dir, "donors[]/labData[]/sequencerModel") == ["NovaSeq 6000", "NextSeq 2000"]


def test_none_when_the_field_declares_no_enum(schema_dir):
    assert enum_at(schema_dir, "donors[]/labData[]/labDataName") is None


def test_none_when_the_path_does_not_exist(schema_dir):
    assert enum_at(schema_dir, "donors[]/labData[]/inventedField") is None


def test_a_reference_cycle_raises_instead_of_reading_as_no_enum(tmp_path):
    root = {
        "properties": {"a": {"$ref": "#/$defs/A"}},
        "$defs": {"A": {"$ref": "#/$defs/B"}, "B": {"$ref": "#/$defs/A"}},
    }
    with pytest.raises(ValueError, match="chained"):
        declared_enum(root, tmp_path, "a")


def test_enum_paths_discovers_every_declared_enum(schema_dir):
    with open(schema_dir / "grz-schema.json", encoding="utf-8") as fh:
        root = json.load(fh)
    assert set(enum_paths(root, schema_dir)) == {
        "submission/coverageType",
        "donors[]/labData[]/libraryType",  # sits inside an allOf branch
        "donors[]/labData[]/sequencerModel",  # enum lives in a vocabulary file
    }
