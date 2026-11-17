"""Device type picker, modeled on NetBox's "Select device type" dialog.

Left: a checkable list of filter criteria; each checked criterion becomes a
row on the right (label, operator where useful, value). Below: **Search** and
the results as a list with the model in bold and a secondary line
(manufacturer, part number, source, match hint). Results come from NetBox,
the local type folder and the devicetype-library; matches for the UniFi model
come first. **New** asks the caller to open the editor with a draft.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from html import escape

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from unifi2netbox.devicetypes import choices
from unifi2netbox.gui_jobs import TaskRunner
from unifi2netbox.typesearch import (
    COMPONENT_FILTERS,
    FILTER_FIELDS,
    LIBRARY,
    SOURCE_LABELS,
    SOURCES,
    TypeCandidate,
    TypeFilter,
    is_suggested,
    search,
)

KEY_ROLE = Qt.ItemDataRole.UserRole + 1
DEFAULT_FILTERS = ("search", "manufacturer", "source")
_YES_NO = ("", "yes", "no")


def _label(text: str, role: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setWordWrap(True)
    if role:
        widget.setProperty("role", role)
    return widget


def candidate_line(candidate: TypeCandidate, hint: str) -> str:
    """Secondary line: manufacturer, part number, source and match hint."""
    parts = [candidate.manufacturer]
    if candidate.part_number and candidate.part_number != candidate.title:
        parts.append(candidate.part_number)
    source = SOURCE_LABELS[candidate.source]
    if candidate.source != "netbox":
        source += ", imported into NetBox on apply"
    parts.append(source)
    if is_suggested(candidate, hint):
        parts.append("matches the UniFi model")
    return " · ".join(p for p in parts if p)


class FilterRow(QWidget):
    """Operator (where useful) and value for one criterion."""

    def __init__(self, field: str, manufacturers: Sequence[str]) -> None:
        super().__init__()
        self.field = field
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.operator: QComboBox | None = None
        if field in ("manufacturer", "source"):
            self.operator = QComboBox()
            self.operator.addItems(("is", "is not"))
            self.operator.setFixedWidth(90)
            layout.addWidget(self.operator)
        if field == "manufacturer":
            self.value = QComboBox()
            self.value.setEditable(True)
            self.value.addItems(("",) + tuple(manufacturers))
        elif field == "source":
            self.value = QComboBox()
            self.value.addItem("", "")
            for source in SOURCES:
                self.value.addItem(SOURCE_LABELS[source], source)
        elif field == "airflow":
            self.value = QComboBox()
            self.value.addItems(("",) + choices("airflow", ""))
        elif field in COMPONENT_FILTERS or field == "is_full_depth":
            self.value = QComboBox()
            self.value.addItems(_YES_NO)
        else:
            self.value = QLineEdit()
            if field == "weight":
                self.value.setPlaceholderText("at most, in the type's unit")
            elif field == "u_height":
                self.value.setPlaceholderText("for example 1 or 0")
        self.value.setObjectName(f"pickerValue_{field}")
        layout.addWidget(self.value, 1)

    def type_filter(self) -> TypeFilter:
        if isinstance(self.value, QComboBox):
            text = (
                str(self.value.currentData())
                if self.field == "source"
                else self.value.currentText()
            )
        else:
            text = self.value.text()
        operator = self.operator.currentText() if self.operator else "is"
        return TypeFilter(self.field, text or "", operator)


class DeviceTypePicker(QDialog):
    """Modal picker; ``selected`` holds the choice, ``new_requested`` New."""

    def __init__(
        self,
        candidates: Sequence[TypeCandidate],
        *,
        hint: str = "",
        hint_manufacturer: str = "",
        note: str = "",
        refresh_library: Callable[[], Sequence[TypeCandidate]] | None = None,
        pool: QThreadPool | None = None,
        parent: QWidget | None = None,
        allow_new: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("typePicker")
        self.setWindowTitle("Select device type")
        self.resize(900, 640)
        self.candidates = list(candidates)
        self.hint = hint
        self.hint_manufacturer = hint_manufacturer
        self.selected: TypeCandidate | None = None
        self.new_requested = False
        self.refresh_library = refresh_library
        self.runner = TaskRunner(pool or QThreadPool.globalInstance(), self)
        self.runner.finished.connect(self._library_refreshed)
        manufacturers = sorted(
            {c.manufacturer for c in self.candidates if c.manufacturer}
        )

        layout = QHBoxLayout(self)
        self.criteria = QListWidget()
        self.criteria.setObjectName("pickerCriteria")
        self.criteria.setFixedWidth(200)
        for field, title in FILTER_FIELDS:
            item = QListWidgetItem(title)
            item.setData(KEY_ROLE, field)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if field in DEFAULT_FILTERS
                else Qt.CheckState.Unchecked
            )
            self.criteria.addItem(item)
        self.criteria.itemChanged.connect(self._criteria_changed)
        layout.addWidget(self.criteria)

        right = QVBoxLayout()
        self.form = QFormLayout()
        self.rows: dict[str, FilterRow] = {}
        self.manufacturers = manufacturers
        right.addLayout(self.form)
        buttons = QHBoxLayout()
        self.note = _label(note, "caption")
        self.note.setObjectName("pickerNote")
        buttons.addWidget(self.note, 1)
        if refresh_library is not None:
            self.refresh_button = QPushButton("Refresh library")
            self.refresh_button.setObjectName("pickerRefreshLibrary")
            self.refresh_button.clicked.connect(self._refresh_library)
            buttons.addWidget(self.refresh_button)
        self.search_button = QPushButton("Search")
        self.search_button.setObjectName("pickerSearch")
        self.search_button.setProperty("variant", "primary")
        self.search_button.clicked.connect(self.run_search)
        buttons.addWidget(self.search_button)
        right.addLayout(buttons)
        self.results = QListWidget()
        self.results.setObjectName("pickerResults")
        self.results.itemDoubleClicked.connect(lambda _i: self.accept_current())
        self.results.currentItemChanged.connect(self._update_buttons)
        right.addWidget(self.results, 1)
        footer = QHBoxLayout()
        self.new_button = QPushButton("New...")
        self.new_button.setObjectName("pickerNew")
        self.new_button.setToolTip(
            "Create a device type in the editor from the UniFi data"
        )
        self.new_button.clicked.connect(self._new)
        self.new_button.setVisible(allow_new)
        footer.addWidget(self.new_button)
        footer.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.select_button = QPushButton("Select")
        self.select_button.setObjectName("pickerSelect")
        self.select_button.setProperty("variant", "primary")
        self.select_button.clicked.connect(self.accept_current)
        footer.addWidget(cancel)
        footer.addWidget(self.select_button)
        right.addLayout(footer)
        layout.addLayout(right, 1)
        for field in DEFAULT_FILTERS:
            self._add_row(field)
        if hint_manufacturer and "manufacturer" in self.rows:
            self.rows["manufacturer"].value.setCurrentText(hint_manufacturer)
        self.run_search()

    # -- filters -------------------------------------------------------------------

    def filters(self) -> tuple[TypeFilter, ...]:
        return tuple(row.type_filter() for row in self.rows.values())

    def set_filter(self, field: str, value: str, operator: str = "is") -> None:
        """Check a criterion and set its value (also used by tests)."""
        for index in range(self.criteria.count()):
            item = self.criteria.item(index)
            if item.data(KEY_ROLE) == field:
                item.setCheckState(Qt.CheckState.Checked)
        row = self.rows[field]
        if row.operator is not None:
            row.operator.setCurrentText(operator)
        if isinstance(row.value, QComboBox):
            found = row.value.findData(value)
            if found < 0:
                found = row.value.findText(value)
            if found >= 0:
                row.value.setCurrentIndex(found)
            else:
                row.value.setCurrentText(value)
        else:
            row.value.setText(value)

    def _criteria_changed(self, item: QListWidgetItem) -> None:
        field = item.data(KEY_ROLE)
        if item.checkState() == Qt.CheckState.Checked:
            self._add_row(field)
        else:
            self._remove_row(field)

    def _add_row(self, field: str) -> None:
        if field in self.rows:
            return
        row = FilterRow(field, self.manufacturers)
        if isinstance(row.value, QLineEdit):
            row.value.returnPressed.connect(self.run_search)
        title = dict(FILTER_FIELDS)[field]
        self.rows[field] = row
        self.form.addRow(title, row)

    def _remove_row(self, field: str) -> None:
        row = self.rows.pop(field, None)
        if row is not None:
            self.form.removeRow(row)

    # -- results -------------------------------------------------------------------

    def run_search(self) -> None:
        result = search(
            self.candidates,
            self.filters(),
            hint=self.hint,
            hint_manufacturer=self.hint_manufacturer,
        )
        self.results.clear()
        for candidate in result.candidates:
            item = QListWidgetItem()
            item.setData(KEY_ROLE, candidate)
            text = (
                f"<b>{escape(candidate.title)}</b><br>"
                f"<span style='font-size:small'>"
                f"{escape(candidate_line(candidate, self.hint))}</span>"
            )
            plain = f"{candidate.title}\n{candidate_line(candidate, self.hint)}"
            # The label widget draws the row; the item keeps the text only for
            # tooltips and screen readers (no second, overlapping text).
            item.setToolTip(plain)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, plain)
            label = QLabel(text)
            label.setContentsMargins(8, 4, 8, 4)
            label.setTextFormat(Qt.TextFormat.RichText)
            item.setSizeHint(label.sizeHint())
            self.results.addItem(item)
            self.results.setItemWidget(item, label)
        notes = []
        if result.unchecked:
            notes.append(
                f"{result.unchecked} types could not be checked against these "
                "filters (details are only known for local and downloaded files)."
            )
        if not result.candidates:
            notes.append("No device type found. Use New to create one.")
        base = self._base_note()
        self.note.setText(" ".join(([base] if base else []) + notes))
        if self.results.count():
            self.results.setCurrentRow(0)
        self._update_buttons()

    def accept_current(self) -> None:
        item = self.results.currentItem()
        if item is None:
            return
        self.selected = item.data(KEY_ROLE)
        self.accept()

    def _new(self) -> None:
        self.new_requested = True
        self.accept()

    def _update_buttons(self, *_args) -> None:
        self.select_button.setEnabled(self.results.currentItem() is not None)

    def _base_note(self) -> str:
        if not any(c.source == LIBRARY for c in self.candidates) and (
            self.refresh_library is not None
        ):
            return "The library index is not loaded yet."
        return ""

    def _refresh_library(self) -> None:
        if self.refresh_library is None:
            return
        self.refresh_button.setEnabled(False)
        self.note.setText("Reading the library index from GitHub...")
        self.runner.start(self.refresh_library)

    def _library_refreshed(self, result: object) -> None:
        self.refresh_button.setEnabled(True)
        if isinstance(result, Exception):
            self.note.setText(f"Library not refreshed: {result}")
            return
        self.candidates = [c for c in self.candidates if c.source != LIBRARY] + list(
            result
        )
        self.manufacturers = sorted(
            {c.manufacturer for c in self.candidates if c.manufacturer}
        )
        if "manufacturer" in self.rows:
            box = self.rows["manufacturer"].value
            current = box.currentText()
            box.clear()
            box.addItems(("",) + tuple(self.manufacturers))
            box.setCurrentText(current)
        self.run_search()
