from __future__ import annotations

import collections
import json

import pytest

from grz_query_metadata import survey as mod


def counters() -> mod.Counters:
    return collections.defaultdict(collections.Counter)


class TestWalk:
    def test_plain_path(self):
        assert mod.collect({"a": {"b": 1}}, "a/b") == [1]

    def test_descends_into_arrays(self):
        meta = {"donors": [{"labData": [{"x": 1}, {"x": 2}]}, {"labData": [{"x": 3}]}]}
        assert mod.collect(meta, "donors[]/labData[]/x") == [1, 2, 3]

    def test_missing_key_yields_nothing(self):
        assert mod.collect({"a": {}}, "a/b/c") == []

    def test_null_values_are_dropped(self):
        assert mod.collect({"donors": [{"gender": None}, {"gender": "male"}]}, "donors[]/gender") == ["male"]

    def test_array_segment_over_non_list(self):
        assert mod.collect({"donors": {"gender": "male"}}, "donors[]/gender") == []


class TestCountSubmission:
    def test_counts_enum_and_freetext(self, submission):
        c = counters()
        mod.count_submission(submission(), c)
        assert c["labData.libraryType"]["wgs"] == 1
        assert c["files.fileType"]["fastq"] == 2
        assert c["labData.sequencerModel"]["Illumina NovaSeq 6000"] == 1

    @pytest.mark.parametrize(
        "tissue_type_id,expected",
        [
            ("BTO:0000089", "yes"),
            ("BTO:89", "no"),
            ("whole blood", "no"),
            ("BTO:0000089\n", "no"),  # $ would accept the trailing newline; \Z must not
        ],
    )
    def test_derived_bto_format(self, tissue_type_id, expected, submission):
        c = counters()
        mod.count_submission(submission(tissue_type_id=tissue_type_id), c)
        assert c["tissueTypeId_is_BTO_format"][expected] == 1

    @pytest.mark.parametrize(
        "meta",
        [
            {"donors": [None]},
            {"donors": "not a list"},
            {"donors": [{"labData": {"not": "a list"}}]},
            {"donors": [{"labData": [None]}]},
        ],
    )
    def test_malformed_shapes_are_skipped_not_fatal(self, meta):
        # One odd row must never abort a whole production run.
        c = counters()
        mod.count_submission(meta, c)
        assert sum(c["tissueTypeId_is_BTO_format"].values()) == 0


class TestDump:
    def test_absent_field_reports_zero(self):
        assert mod.dump(counters(), ["nope"])["nope"] == {"_total": 0, "_distinct": 0, "values": {}}

    def test_reports_every_value_most_common_first(self):
        c = counters()
        c["f"].update({"b": 3, "a": 5, "c": 1})
        out = mod.dump(c, ["f"])["f"]
        assert out["_total"] == 9
        assert out["_distinct"] == 3
        assert list(out["values"].items()) == [("a", 5), ("b", 3), ("c", 1)]


class TestAsUrl:
    def test_passes_through_sqlalchemy_urls(self):
        assert mod.as_url("postgresql://user@host/db") == "postgresql://user@host/db"

    def test_wraps_an_existing_path(self, tmp_path):
        p = tmp_path / "submission.db.sqlite"
        p.touch()
        assert mod.as_url(str(p)) == f"sqlite:///{p}"

    def test_exits_on_a_missing_path(self, tmp_path):
        with pytest.raises(SystemExit):
            mod.as_url(str(tmp_path / "nope.sqlite"))


class TestResolveDbUrl:
    def test_reads_a_grz_config_file(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("db:\n  database_url: postgresql://user@host/grzdb\n")
        assert mod.resolve_db_url(config_file=str(cfg)) == "postgresql://user@host/grzdb"

    def test_db_url_wins_over_a_config_file(self, tmp_path):
        assert mod.resolve_db_url("postgresql://user@host/db", "/nonexistent.yaml") == (
            "postgresql://user@host/db"
        )

    def test_exits_when_the_config_has_no_url(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("db: {}\n")
        with pytest.raises(SystemExit):
            mod.resolve_db_url(config_file=str(cfg))

    def test_exits_when_neither_is_given(self):
        with pytest.raises(SystemExit):
            mod.resolve_db_url()


class TestResolveGrzId:
    """The site id is read out of the submissions rather than retyped."""

    def test_taken_from_the_submissions(self):
        assert mod.resolve_grz_id(collections.Counter({"GRZK00123": 40})) == (
            "GRZK00123",
            mod.GRZ_ID_PATH,
        )

    def test_the_flag_overrides_what_the_data_says(self):
        found, source = mod.resolve_grz_id(collections.Counter({"GRZK00123": 40}), "GRZK00999")
        assert (found, source) == ("GRZK00999", "--grz-id")

    def test_exits_when_the_database_records_none(self):
        with pytest.raises(SystemExit) as exit:
            mod.resolve_grz_id(collections.Counter())
        assert "--grz-id" in str(exit.value)

    def test_exits_when_the_database_holds_more_than_one(self):
        with pytest.raises(SystemExit) as exit:
            mod.resolve_grz_id(collections.Counter({"GRZK00123": 40, "GRZK00456": 2}))
        message = str(exit.value)
        assert "more than one GRZ" in message
        # the counts are what tell a stray import from the site's own submissions
        assert "GRZK00123 (40)" in message and "GRZK00456 (2)" in message

    def test_the_flag_rescues_both_of_those(self):
        assert mod.resolve_grz_id(collections.Counter(), "GRZK00123")[0] == "GRZK00123"
        assert mod.resolve_grz_id(collections.Counter({"A": 1, "B": 1}), "GRZK00123")[0] == "GRZK00123"


class TestEndToEnd:
    def test_writes_a_report(self, sqlite_db, tmp_path):
        out = tmp_path / "report.json"
        mod.main(["--db-url", str(sqlite_db), "--out", str(out)])
        report = json.loads(out.read_text(encoding="utf-8"))

        assert report["grz_id"] == "GRZK00123"  # never passed on the command line
        assert report["grz_id_source"] == mod.GRZ_ID_PATH
        assert report["submissions_in_table"] == 4
        assert report["submissions_with_metadata"] == 2
        assert report["submissions_unparseable"] == 1  # the "{not json" row; the NULL row is not counted
        assert report["enum_fields"]["labData.libraryType"]["values"] == {"wgs": 1, "wxs": 1}
        assert report["freetext_fields"]["labData.labDataName"]["values"] == {"Blut DNA": 2}
        assert report["derived"]["tissueTypeId_is_BTO_format"]["values"] == {"yes": 2}

    def test_report_values_are_written_most_common_first(self, db_factory, submission, tmp_path):
        db = db_factory([submission(library_type="wxs"), submission(library_type="wxs"), submission()])
        out = tmp_path / "report.json"
        mod.main(["--db-url", str(db), "--out", str(out)])
        report = json.loads(out.read_text(encoding="utf-8"))
        # The order in the file is what the human review sees; it must be the
        # frequency order dump() builds, not alphabetical.
        assert list(report["enum_fields"]["labData.libraryType"]["values"]) == ["wxs", "wgs"]

    def test_default_filename_uses_the_derived_grz_id(self, sqlite_db, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mod.main(["--db-url", str(sqlite_db)])
        assert list(tmp_path.glob("grz-survey-GRZK00123-*.json"))

    def test_the_flag_relabels_the_report_and_says_so(self, sqlite_db, tmp_path):
        out = tmp_path / "report.json"
        mod.main(["--db-url", str(sqlite_db), "--grz-id", "GRZK00999", "--out", str(out)])
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["grz_id"] == "GRZK00999"
        assert report["grz_id_source"] == "--grz-id"

    def test_a_database_without_the_id_needs_the_flag(self, db_factory, submission, tmp_path):
        db = db_factory([submission(grz_id=None)])
        with pytest.raises(SystemExit) as exit:
            mod.main(["--db-url", str(db)])
        assert mod.GRZ_ID_PATH in str(exit.value)

        out = tmp_path / "report.json"
        mod.main(["--db-url", str(db), "--grz-id", "GRZK00123", "--out", str(out)])
        assert json.loads(out.read_text(encoding="utf-8"))["grz_id"] == "GRZK00123"

    def test_a_database_mixing_two_grzs_is_refused(self, db_factory, submission):
        db = db_factory([submission(), submission(grz_id="GRZK00456")])
        with pytest.raises(SystemExit) as exit:
            mod.main(["--db-url", str(db)])
        assert "more than one GRZ" in str(exit.value)
