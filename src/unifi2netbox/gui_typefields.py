"""Editor widgets for the NetBox side of a device type (M13 slice 3).

``ChoiceCell`` is an editable drop-down for references (NetBox objects from the
catalog or components of the same definition), with **New...** for NetBox
objects. ``TagEditor`` shows tags as removable chips with a picker,
``ImagePanel`` keeps front/rear image choices until the definition is saved,
and ``CustomFieldsTable`` edits the custom fields NetBox defines for device
types, one value editor per field type.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QCalendarWidget,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from ruamel.yaml.comments import CommentedMap

from unifi2netbox.devicetypes import IMAGE_SIDES, IMAGE_SUFFIXES
from unifi2netbox.netbox_catalog import CustomFieldDef

# (catalog kind, target widget with text()/set_text()) -> opens a New dialog.
NewHandler = Callable[[str, object], None]
# (manufacturer, slug, side) -> local image file or None.
ImageLookup = Callable[[str, str, str], Path | None]
REMOVE = "remove"


def list_text(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, list | tuple):
        return ", ".join(list_text(item) for item in value)
    if isinstance(value, Mapping):
        return json.dumps(dict(value), sort_keys=True)
    return "" if value is None else str(value)


class ChoiceCell(QWidget):
    """Editable drop-down; **New...** creates the NetBox object right away."""

    def __init__(
        self,
        text: str,
        options: Iterable[str],
        new_kind: str = "",
        on_new: NewHandler | None = None,
        changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.combo = QComboBox()
        self.combo.setObjectName("referenceCombo")
        self.combo.setEditable(True)
        self.set_options(options, text)
        if changed is not None:
            self.combo.currentTextChanged.connect(lambda _t: changed())
        layout.addWidget(self.combo, 1)
        self.new_button: QToolButton | None = None
        if new_kind and on_new is not None:
            button = QToolButton()
            button.setText("New...")
            button.setObjectName(f"new_{new_kind}")
            button.setToolTip("Create it in NetBox right away")
            button.clicked.connect(lambda _c=False: on_new(new_kind, self))
            layout.addWidget(button)
            self.new_button = button

    def text(self) -> str:
        return self.combo.currentText()

    def set_text(self, text: str) -> None:
        self.combo.setCurrentText(text)

    def options(self) -> tuple[str, ...]:
        return tuple(self.combo.itemText(i) for i in range(1, self.combo.count()))

    def set_options(self, options: Iterable[str], text: str | None = None) -> None:
        current = self.text() if text is None else text
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem("")
        self.combo.addItems([o for o in dict.fromkeys(options) if o])
        self.combo.setCurrentText(current)
        self.combo.blockSignals(False)


class TagEditor(QWidget):
    """Tags (slugs) as chips; a chip click removes the tag."""

    changed = Signal()

    def __init__(self, on_new: NewHandler | None = None) -> None:
        super().__init__()
        self.setObjectName("typeTags")
        self.tags: list[str] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(4)
        self.empty = QLabel("No tags")
        self.empty.setProperty("role", "secondary")
        self.chips.addWidget(self.empty)
        layout.addLayout(self.chips)
        layout.addStretch()
        self.picker = QComboBox()
        self.picker.setObjectName("tagPicker")
        self.picker.setEditable(True)
        self.picker.setMinimumWidth(160)
        self.picker.lineEdit().setPlaceholderText("Tag slug")
        self.picker.lineEdit().returnPressed.connect(self.add_current)
        add = QToolButton()
        add.setText("Add")
        add.setObjectName("tagAdd")
        add.clicked.connect(self.add_current)
        layout.addWidget(self.picker)
        layout.addWidget(add)
        if on_new is not None:
            new = QToolButton()
            new.setText("New tag...")
            new.setObjectName("new_tags")
            new.clicked.connect(lambda _c=False: on_new("tags", self))
            layout.addWidget(new)

    # The New handler reads the prefill and sets the created tag like a cell.
    def text(self) -> str:
        return self.picker.currentText().strip()

    def set_text(self, slug: str) -> None:
        self.add_tag(slug)
        self.picker.setCurrentText("")

    def set_options(self, slugs: Iterable[str]) -> None:
        self.picker.clear()
        self.picker.addItem("")
        self.picker.addItems(list(slugs))
        self.picker.setCurrentText("")

    def set_tags(self, tags: Iterable) -> None:
        self.tags = [str(tag) for tag in tags if str(tag).strip()]
        self._rebuild()

    def add_current(self) -> None:
        self.set_text(self.text())

    def add_tag(self, slug: str) -> None:
        slug = slug.strip()
        if slug and slug not in self.tags:
            self.tags.append(slug)
            self._rebuild()
            self.changed.emit()

    def remove_tag(self, slug: str) -> None:
        if slug in self.tags:
            self.tags.remove(slug)
            self._rebuild()
            self.changed.emit()

    def _rebuild(self) -> None:
        while self.chips.count() > 1:
            item = self.chips.takeAt(1)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.empty.setVisible(not self.tags)
        for slug in self.tags:
            chip = QToolButton()
            chip.setText(f"{slug}  ×")
            chip.setObjectName(f"tag_{slug}")
            chip.setProperty("chip", "neutral")
            chip.setToolTip(f"Remove the tag {slug}")
            chip.clicked.connect(lambda _c=False, s=slug: self.remove_tag(s))
            self.chips.addWidget(chip)


class ImagePanel(QWidget):
    """Front and rear image; choices are applied when the definition is saved."""

    changed = Signal()

    def __init__(self, lookup: ImageLookup | None = None) -> None:
        super().__init__()
        self.lookup = lookup
        self.key = ("", "")
        self.pending: dict[str, Path | str] = {}
        self.labels: dict[str, QLabel] = {}
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        for row, side in enumerate(IMAGE_SIDES):
            grid.addWidget(QLabel(f"{side.capitalize()} image"), row, 0)
            label = QLabel("")
            label.setObjectName(f"image_{side}")
            label.setProperty("role", "secondary")
            self.labels[side] = label
            grid.addWidget(label, row, 1)
            choose = QToolButton()
            choose.setText("Choose...")
            choose.setObjectName(f"imageChoose_{side}")
            choose.clicked.connect(lambda _c=False, s=side: self.choose(s))
            remove = QToolButton()
            remove.setText("Remove")
            remove.setObjectName(f"imageRemove_{side}")
            remove.clicked.connect(lambda _c=False, s=side: self.set_pending(s, REMOVE))
            grid.addWidget(choose, row, 2)
            grid.addWidget(remove, row, 3)
        grid.setColumnStretch(1, 1)

    def show_for(self, manufacturer: str, slug: str) -> None:
        self.key = (manufacturer, slug)
        self._update()

    def current(self, side: str) -> Path | None:
        if self.lookup is None:
            return None
        return self.lookup(*self.key, side)

    def choose(self, side: str) -> None:
        patterns = " ".join(f"*{suffix}" for suffix in IMAGE_SUFFIXES)
        name, _ = QFileDialog.getOpenFileName(
            self, f"Choose the {side} image", "", f"Images ({patterns})"
        )
        if name:
            self.set_pending(side, Path(name))

    def set_pending(self, side: str, value: Path | str) -> None:
        if value == REMOVE and self.current(side) is None:
            self.pending.pop(side, None)  # nothing saved: just drop the choice
        else:
            self.pending[side] = value
        self._update()
        self.changed.emit()

    def clear_pending(self) -> None:
        self.pending = {}
        self._update()

    def flag(self, side: str, original):
        """The ``front_image``/``rear_image`` value after the pending choice."""
        choice = self.pending.get(side)
        if isinstance(choice, Path):
            return True
        if choice == REMOVE:
            return None
        return original

    def _update(self) -> None:
        for side, label in self.labels.items():
            choice = self.pending.get(side)
            current = self.current(side)
            if isinstance(choice, Path):
                label.setText(f"{choice.name} (copied when saved)")
            elif choice == REMOVE:
                label.setText("Removed when saved")
            elif current is not None:
                label.setText(current.name)
            else:
                label.setText("None")


class CustomFieldsTable(QTableWidget):
    """Custom fields of device types: one row per NetBox definition."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__(0, 3)
        self.setObjectName("typeCustomFields")
        self.setHorizontalHeaderLabels(["Field", "Value", "Explanation"])
        self.verticalHeader().hide()
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.setMinimumHeight(80)
        self.definitions: dict[str, CustomFieldDef] = {}
        self.names: list[str] = []
        self.itemChanged.connect(lambda _i: self.changed.emit())

    def set_fields(
        self, definitions: Iterable[CustomFieldDef], values: Mapping[str, object]
    ) -> None:
        self.blockSignals(True)
        self.definitions = {item.name: item for item in definitions}
        self.names = list(self.definitions) + [
            name for name in values if name not in self.definitions
        ]
        self.setRowCount(len(self.names))
        for row, name in enumerate(self.names):
            definition = self.definitions.get(name)
            label = definition.label if definition else name
            if definition and definition.required:
                label += " *"
            field = QTableWidgetItem(label)
            field.setFlags(field.flags() & ~Qt.ItemFlag.ItemIsEditable)
            field.setToolTip(name)
            self.setItem(row, 0, field)
            text = list_text(values.get(name))
            if definition and definition.type in ("select", "boolean"):
                box = QComboBox()
                choices = (
                    definition.choices
                    if definition.type == "select"
                    else ("true", "false")
                )
                box.addItems(("", *choices))
                if text and box.findText(text) < 0:
                    box.addItem(text)
                box.setCurrentText(text)
                box.currentTextChanged.connect(lambda _t: self.changed.emit())
                self.setCellWidget(row, 1, box)
            elif definition and definition.type == "date":
                self.setCellWidget(row, 1, DateCell(text, self.changed.emit))
            else:
                self.removeCellWidget(row, 1)
                self.setItem(row, 1, QTableWidgetItem(text))
            if definition is None:
                explanation = "Not defined for device types in NetBox."
            else:
                kind = definition.type.replace("_", " ")
                explanation = (
                    f"{definition.description} ({kind})"
                    if definition.description
                    else f"Type: {kind}."
                )
                if definition.type == "multiselect" and definition.choices:
                    explanation += f" Choices: {', '.join(definition.choices)}."
                if definition.type == "multiselect":
                    explanation += " Separate values with commas."
            help_item = QTableWidgetItem(explanation)
            help_item.setFlags(help_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            help_item.setToolTip(explanation)
            self.setItem(row, 2, help_item)
        self.resizeColumnToContents(0)
        self.setColumnWidth(1, 220)
        self.resizeRowsToContents()
        self.blockSignals(False)

    def texts(self) -> dict[str, str]:
        result = {}
        for row, name in enumerate(self.names):
            widget = self.cellWidget(row, 1)
            if isinstance(widget, QComboBox):
                result[name] = widget.currentText().strip()
            elif isinstance(widget, DateCell):
                result[name] = widget.text().strip()
            else:
                item = self.item(row, 1)
                result[name] = item.text().strip() if item is not None else ""
        return result

    def values(self) -> CommentedMap:
        result = CommentedMap()
        for name, text in self.texts().items():
            if text:
                definition = self.definitions.get(name)
                result[name] = typed_value(definition.type if definition else "", text)
        return result


def typed_value(kind: str, text: str):
    """A custom field value from its text; bad numbers stay text for NetBox."""
    if kind == "boolean":
        return {"true": True, "false": False}.get(text.lower(), text)
    if kind in ("integer", "decimal"):
        try:
            number = float(text.replace(",", "."))
        except ValueError:
            return text
        if kind == "integer" and number.is_integer():
            return int(number)
        return number
    if kind == "multiselect":
        return [part.strip() for part in text.split(",") if part.strip()]
    if kind == "json":
        try:
            return json.loads(text)
        except ValueError:
            return text
    return text


class CollapsibleSection(QWidget):
    """A titled section with an arrow button that folds its content away.

    Folded, the section is only as high as its title, so the other sections
    of the surrounding splitter get the room (small screens).
    """

    toggled = Signal(bool)  # True when folded

    def __init__(self, key: str, title: str, content: QWidget) -> None:
        super().__init__()
        self.key = key
        self.content = content
        self.collapsed = False
        self.expanded_height = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(2)
        self.header = QToolButton()
        self.header.setObjectName(f"section_{key}")
        self.header.setText(title)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setArrowType(Qt.ArrowType.DownArrow)
        self.header.setAutoRaise(True)
        self.header.setProperty("role", "subheading")
        font = self.header.font()
        font.setBold(True)
        self.header.setFont(font)
        self.header.setToolTip("Click to fold or unfold this section")
        self.header.clicked.connect(
            lambda _c=False: self.set_collapsed(not self.collapsed)
        )
        layout.addWidget(self.header)
        layout.addWidget(content, 1)

    def folded_height(self) -> int:
        margins = self.layout().contentsMargins()
        return self.header.sizeHint().height() + margins.top() + margins.bottom() + 2

    def set_collapsed(self, collapsed: bool) -> None:
        if collapsed == self.collapsed:
            return
        if collapsed:
            self.expanded_height = self.height()
        self.collapsed = collapsed
        self.content.setVisible(not collapsed)
        self.header.setArrowType(
            Qt.ArrowType.RightArrow if collapsed else Qt.ArrowType.DownArrow
        )
        self.setMaximumHeight(self.folded_height() if collapsed else 16777215)
        self.toggled.emit(collapsed)


class DateCell(QWidget):
    """A date as ``YYYY-MM-DD``: typed, or picked from a calendar; may be empty."""

    def __init__(self, text: str = "", changed: Callable[[], None] | None = None):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.edit = QLineEdit(text)
        self.edit.setObjectName("dateEdit")
        self.edit.setPlaceholderText("YYYY-MM-DD")
        if changed is not None:
            self.edit.textChanged.connect(lambda _t: changed())
        layout.addWidget(self.edit, 1)
        self.pick = QToolButton()
        self.pick.setText("\U0001f4c5")
        self.pick.setObjectName("datePick")
        self.pick.setToolTip("Choose the date in a calendar")
        self.pick.clicked.connect(self.open_calendar)
        layout.addWidget(self.pick)
        self.clear = QToolButton()
        self.clear.setText("×")
        self.clear.setObjectName("dateClear")
        self.clear.setToolTip("Remove the date")
        self.clear.clicked.connect(lambda _c=False: self.edit.setText(""))
        layout.addWidget(self.clear)
        self.popup: QFrame | None = None

    def text(self) -> str:
        return self.edit.text()

    def set_text(self, text: str) -> None:
        self.edit.setText(text)

    def calendar(self) -> QCalendarWidget:
        popup = QFrame(self, Qt.WindowType.Popup)
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(4, 4, 4, 4)
        calendar = QCalendarWidget()
        calendar.setObjectName("dateCalendar")
        current = QDate.fromString(self.text().strip(), "yyyy-MM-dd")
        calendar.setSelectedDate(current if current.isValid() else QDate.currentDate())
        calendar.clicked.connect(lambda date: self._picked(date))
        calendar.activated.connect(lambda date: self._picked(date))
        layout.addWidget(calendar)
        self.popup = popup
        return calendar

    def open_calendar(self) -> None:
        self.calendar()
        self.popup.move(self.mapToGlobal(self.rect().bottomLeft()))
        self.popup.show()

    def _picked(self, date: QDate) -> None:
        self.edit.setText(date.toString("yyyy-MM-dd"))
        if self.popup is not None:
            self.popup.close()
