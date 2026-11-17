"""Marks for values that differ from NetBox (M14 slice 3).

A differing cell gets the warning tone (yellow) as background and the NetBox
value as tooltip; a template row that exists only locally gets the danger
tone (red) on its name; rows that exist only in NetBox are shown greyed out
by the component table. The colors are the theme tones used for validation
and the tree status.
"""

from __future__ import annotations

from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QComboBox, QTableWidget, QTableWidgetItem, QWidget

from unifi2netbox import theme

WARNING = "warning"
DANGER = "danger"
SUCCESS = "success"
USE_HINT = "Right-click to use the NetBox value."


def netbox_text(value) -> str:
    if value is None or value == "" or value == []:
        return "(empty)"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, list | tuple):
        return ", ".join(netbox_text(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}: {netbox_text(v)}" for k, v in value.items())
    return str(value)


def background(tone: str) -> str:
    return theme.tone_colors(tone)[1]


def mark_widget(widget: QWidget, tone: str | None, tooltip: str = "") -> None:
    combo = widget if isinstance(widget, QComboBox) else widget.findChild(QComboBox)
    target = combo or widget
    target.setStyleSheet(
        f"QComboBox {{ background-color: {background(tone)}; }}" if tone else ""
    )
    target.setToolTip(tooltip)
    widget.setProperty("netboxMark", tone or "")


def mark_cell(
    table: QTableWidget, row: int, column: int, tone: str | None, tooltip: str = ""
) -> None:
    """Mark one cell; callers block the table's signals while marking."""
    widget = table.cellWidget(row, column)
    if widget is not None:
        mark_widget(widget, tone, tooltip)
        return
    item = table.item(row, column)
    if item is None:
        item = QTableWidgetItem("")
        table.setItem(row, column, item)
    item.setBackground(QBrush(QColor(background(tone))) if tone else QBrush())
    item.setToolTip(tooltip)
    item.setData(MARK_ROLE, tone or "")


def cell_mark(table: QTableWidget, row: int, column: int) -> str:
    widget = table.cellWidget(row, column)
    if widget is not None:
        return str(widget.property("netboxMark") or "")
    item = table.item(row, column)
    return str(item.data(MARK_ROLE) or "") if item is not None else ""


MARK_ROLE = 0x0100 + 7  # Qt.UserRole + 7
