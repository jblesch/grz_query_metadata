from __future__ import annotations

import pytest

from grz_query_metadata import ods


def write_one_sheet(tmp_path, rows):
    doc = ods.new_document()
    ods.write_sheet(doc, "sheet", rows)
    path = tmp_path / "out.ods"
    doc.save(str(path))
    return path


def test_numbers_are_written_as_numbers(tmp_path, read_ods):
    # Counts must stay sortable and summable in the opened spreadsheet.
    path = write_one_sheet(tmp_path, [ods.Row(["label", 3, 0.25])])
    assert read_ods(path)["sheet"] == [["label", 3, 0.25]]


def test_booleans_are_written_as_text_not_as_numbers(tmp_path, read_ods):
    # bool subclasses int in Python; without the explicit guard in _cell,
    # True would silently land in the sheet as the number 1.
    path = write_one_sheet(tmp_path, [ods.Row([True, False])])
    assert read_ods(path)["sheet"] == [["True", "False"]]


def test_a_per_cell_style_overrides_the_row_style(tmp_path, cell_styles):
    path = write_one_sheet(
        tmp_path,
        [ods.Row(["a", "b", "c"], style=ods.UNUSED, styles={1: ods.HEAD})],
    )
    assert cell_styles(path, "sheet") == [[ods.UNUSED, ods.HEAD, ods.UNUSED]]


def test_an_empty_row_is_a_blank_spacer(tmp_path, read_ods):
    path = write_one_sheet(tmp_path, [ods.Row(["above"]), ods.Row(), ods.Row(["below"])])
    assert read_ods(path)["sheet"] == [["above"], [], ["below"]]


@pytest.mark.parametrize("value", [None, ""])
def test_empty_values_produce_empty_cells(tmp_path, read_ods, value):
    path = write_one_sheet(tmp_path, [ods.Row([value, "x"])])
    assert read_ods(path)["sheet"] == [[None, "x"]]
