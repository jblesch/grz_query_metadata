"""A thin writer over odfpy, so the aggregation can stay about the data.

It builds an OpenDocument spreadsheet out of
named sheets and :class:`Row` objects, where a cell may carry one of a handful
of named styles. The sheet-building functions in
:mod:`grz_query_metadata.aggregate` return lists of these rows, which is what
lets them be read — and tested — without a spreadsheet in the picture.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from odf.opendocument import OpenDocumentSpreadsheet
from odf.style import Style, TableCellProperties, TableColumnProperties, TextProperties
from odf.table import Table, TableCell, TableColumn, TableRow
from odf.text import P

# Cell styles, by the meaning they carry rather than by their colour.
HEAD = "head"
UNUSED = "unused"  # declared in the schema, never used by anyone
OUTSIDE_VOCAB = "outside-vocab"  # not covered by the proposed vocabulary
PROBLEM = "problem"

_FILLS = {
    UNUSED: "#DAE8FC",
    OUTSIDE_VOCAB: "#FFF2CC",
    PROBLEM: "#F8CECC",
}

WIDE = "wide"
NARROW = "narrow"
_WIDTHS = {WIDE: "9cm", NARROW: "3cm"}


@dataclass
class Row:
    """One spreadsheet row. `style` applies to every cell, `styles` overrides
    individual cells by column index. An empty Row is a blank spacer line."""

    values: Sequence[Any] = ()
    style: str | None = None
    styles: Mapping[int, str] = field(default_factory=dict)


def new_document() -> OpenDocumentSpreadsheet:
    """An empty spreadsheet with the cell and column styles registered."""
    doc = OpenDocumentSpreadsheet()

    head = Style(name=HEAD, family="table-cell")
    head.addElement(TextProperties(fontweight="bold"))
    doc.automaticstyles.addElement(head)

    for name, colour in _FILLS.items():
        style = Style(name=name, family="table-cell")
        style.addElement(TableCellProperties(backgroundcolor=colour))
        doc.automaticstyles.addElement(style)

    for name, width in _WIDTHS.items():
        style = Style(name=name, family="table-column")
        style.addElement(TableColumnProperties(columnwidth=width))
        doc.automaticstyles.addElement(style)

    return doc


def _cell(value: Any, style: str | None = None) -> TableCell:
    attrs: dict[str, Any] = {"stylename": style} if style else {}
    # Numbers go in as numbers, so that the sheet stays sortable and summable.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        cell = TableCell(valuetype="float", value=value, **attrs)
        cell.addElement(P(text=str(value)))
        return cell
    cell = TableCell(valuetype="string", **attrs)
    if value not in (None, ""):
        cell.addElement(P(text=str(value)))
    return cell


def write_sheet(
    doc: OpenDocumentSpreadsheet,
    name: str,
    rows: Iterable[Row],
    columns: Iterable[str] = (),
) -> Table:
    """Add a sheet holding `rows`, with an optional width style per column."""
    table = Table(name=name)
    for width in columns:
        table.addElement(TableColumn(stylename=width))
    for row in rows:
        tr = TableRow()
        for i, value in enumerate(row.values):
            tr.addElement(_cell(value, row.styles.get(i, row.style)))
        table.addElement(tr)
    doc.spreadsheet.addElement(table)
    return table
