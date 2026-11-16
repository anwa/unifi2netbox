"""Device type editor window (M12 slice 4).

Laid out like the manual window: the local type folder as a tree on the left
(``device-types/<Manufacturer>/<file>``), the selected definition on the
right. The definition can be edited as raw YAML or as tables with an
explanation per field; both views edit the same document. Saving validates
against the library schema and the CONTRIBUTING rules and writes the file
under its library name. UniFi models can be completed from techspecs.ui.com.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from ruamel.yaml.comments import CommentedMap

from unifi2netbox import theme
from unifi2netbox.config import DeviceTypesConfig
from unifi2netbox.devicetypes import (
    ATTRIBUTES,
    COLUMN_HELP,
    COMPONENTS,
    FIELD_HELP,
    DeviceTypeError,
    Issue,
    LocalTypeStore,
    component_columns,
    dump_yaml,
    errors,
    field_spec,
    load_yaml,
    new_document,
    validate,
)
from unifi2netbox.gui_jobs import TaskRunner
from unifi2netbox.library import client
from unifi2netbox.techspecs import TechSpec, fetch_url, lookup
from unifi2netbox.typedraft import merge_spec

PATH_ROLE = Qt.ItemDataRole.UserRole + 1
_TABLE_ATTRIBUTES = tuple(name for name in ATTRIBUTES if name != "comments")


def _label(text: str, role: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setWordWrap(True)
    if role:
        widget.setProperty("role", role)
    return widget


def value_text(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return "" if value is None else str(value)


def text_value(section: str | None, name: str, text: str):
    """Typed value for a table cell; invalid numbers stay text for validation."""
    text = text.strip()
    if not text:
        return None
    kind = field_spec(section, name).kind
    if kind == "boolean":
        return {"true": True, "false": False}.get(text.lower(), text)
    if kind in ("number", "integer"):
        try:
            number = float(text.replace(",", "."))
        except ValueError:
            return text
        if kind == "integer" or number.is_integer():
            return int(number) if number.is_integer() else number
        return number
    return text


class _Cells:
    """Read and write one table cell, plain or as a choice box."""

    def __init__(self, table: QTableWidget) -> None:
        self.table = table

    def put(self, row: int, column: int, section, name, value, changed) -> None:
        spec = field_spec(section, name)
        text = value_text(value)
        if spec.kind in ("enum", "boolean"):
            box = QComboBox()
            choices = spec.choices if spec.kind == "enum" else ("true", "false")
            box.addItems(("",) + tuple(choices))
            if text and box.findText(text) < 0:
                box.addItem(text)
            box.setCurrentText(text)
            box.currentTextChanged.connect(lambda _t: changed())
            self.table.setCellWidget(row, column, box)
        else:
            self.table.setItem(row, column, QTableWidgetItem(text))

    def get(self, row: int, column: int) -> str:
        widget = self.table.cellWidget(row, column)
        if isinstance(widget, QComboBox):
            return widget.currentText()
        item = self.table.item(row, column)
        return item.text() if item is not None else ""


class ComponentTable(QWidget):
    """One component section (for example interfaces) as an editable table."""

    changed = Signal()

    def __init__(self, section: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.section = section
        self.columns = component_columns(section)
        self.originals: list = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        self.table = QTableWidget(0, len(self.columns))
        self.table.setObjectName(f"component_{section}")
        self.table.setHorizontalHeaderLabels(
            [f"{c} *" if field_spec(section, c).required else c for c in self.columns]
        )
        for index, column in enumerate(self.columns):
            header = self.table.horizontalHeaderItem(index)
            header.setToolTip(COLUMN_HELP.get(column, column))
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(lambda _i: self.changed.emit())
        self.cells = _Cells(self.table)
        buttons = QHBoxLayout()
        add = QPushButton("Add row")
        add.setObjectName(f"add_{section}")
        add.clicked.connect(self.add_row)
        remove = QPushButton("Remove selected")
        remove.setObjectName(f"remove_{section}")
        remove.clicked.connect(self.remove_rows)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)
        help_text = "; ".join(
            f"{c}: {COLUMN_HELP[c]}" for c in self.columns if c in COLUMN_HELP
        )
        layout.addWidget(_label(help_text + " (* required)", "caption"))

    def set_rows(self, rows: Iterable) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.originals = []
        for row in rows:
            self._append(row if isinstance(row, dict) else {})
            self.originals[-1] = row if isinstance(row, dict) else None
        self.table.resizeColumnsToContents()
        self.table.blockSignals(False)

    def rows(self) -> tuple[list, bool]:
        """The rows and whether they are exactly the original ones."""
        result = []
        unchanged = True
        for row in range(self.table.rowCount()):
            texts = [self.cells.get(row, c) for c in range(len(self.columns))]
            original = self.originals[row] if row < len(self.originals) else None
            if original is not None and texts == [
                value_text(original.get(name)) for name in self.columns
            ]:
                result.append(copy.deepcopy(original))
                continue
            unchanged = False
            item = CommentedMap()
            for name, text in zip(self.columns, texts, strict=True):
                value = text_value(self.section, name, text)
                if value is not None:
                    item[name] = value
            if item:
                result.append(item)
        return result, unchanged

    def add_row(self) -> None:
        self._append({})
        self.table.scrollToBottom()
        self.changed.emit()

    def remove_rows(self) -> None:
        for row in sorted(
            {i.row() for i in self.table.selectedIndexes()}, reverse=True
        ):
            self.table.removeRow(row)
            if row < len(self.originals):
                del self.originals[row]
        self.changed.emit()

    def _append(self, values: dict) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.originals.append(None)
        for column, name in enumerate(self.columns):
            self.cells.put(
                row, column, self.section, name, values.get(name), self.changed.emit
            )


class TableView(QWidget):
    """Attributes with explanations, comments and one tab per component kind."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.attributes = QTableWidget(len(_TABLE_ATTRIBUTES), 3)
        self.attributes.setObjectName("typeAttributes")
        self.attributes.setHorizontalHeaderLabels(["Field", "Value", "Explanation"])
        self.attributes.verticalHeader().hide()
        self.attributes.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.attributes.setWordWrap(True)
        self.attributes.setMinimumHeight(300)
        self.cells = _Cells(self.attributes)
        for row, name in enumerate(_TABLE_ATTRIBUTES):
            spec = field_spec(None, name)
            label = QTableWidgetItem(f"{name} *" if spec.required else name)
            label.setFlags(label.flags() & ~Qt.ItemFlag.ItemIsEditable)
            help_item = QTableWidgetItem(FIELD_HELP.get(name, ""))
            help_item.setFlags(help_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            help_item.setToolTip(FIELD_HELP.get(name, ""))
            self.attributes.setItem(row, 0, label)
            self.attributes.setItem(row, 2, help_item)
        self.attributes.itemChanged.connect(lambda _i: self.changed.emit())
        self.comments = QPlainTextEdit()
        self.comments.setObjectName("typeComments")
        self.comments.setPlaceholderText(FIELD_HELP["comments"])
        self.comments.setMaximumHeight(90)
        self.comments.textChanged.connect(self.changed.emit)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("typeComponents")
        self.sections: dict[str, ComponentTable] = {}
        for section in COMPONENTS:
            table = ComponentTable(section)
            table.changed.connect(self._section_changed)
            self.sections[section] = table
            self.tabs.addTab(table, section)
        layout.addWidget(_label("Attributes (* required)", "subheading"))
        layout.addWidget(self.attributes, 2)
        layout.addWidget(_label("Comments", "subheading"))
        layout.addWidget(self.comments)
        layout.addWidget(_label("Components", "subheading"))
        layout.addWidget(self.tabs, 3)
        self.base = CommentedMap()

    def set_document(self, doc: CommentedMap) -> None:
        self.base = copy.deepcopy(doc)
        self.attributes.blockSignals(True)
        for row, name in enumerate(_TABLE_ATTRIBUTES):
            self.cells.put(row, 1, None, name, doc.get(name), self.changed.emit)
        self.attributes.resizeColumnToContents(0)
        self.attributes.setColumnWidth(1, 220)
        self.attributes.resizeRowsToContents()
        self.attributes.blockSignals(False)
        self.comments.blockSignals(True)
        self.comments.setPlainText(value_text(doc.get("comments")).rstrip("\n"))
        self.comments.blockSignals(False)
        for section, table in self.sections.items():
            table.set_rows(doc.get(section) or ())
        self._update_tab_titles()
        first = next(
            (i for i, s in enumerate(COMPONENTS) if doc.get(s)),
            COMPONENTS.index("interfaces"),
        )
        self.tabs.setCurrentIndex(first)

    def document(self) -> CommentedMap:
        doc = copy.deepcopy(self.base)
        for row, name in enumerate(_TABLE_ATTRIBUTES):
            text = self.cells.get(row, 1)
            if name in doc and text.strip() == value_text(doc[name]):
                continue  # unchanged: keep the original value and its style
            value = text_value(None, name, text)
            if value is None:
                doc.pop(name, None)
            else:
                doc[name] = value
        comments = self.comments.toPlainText().strip()
        original = doc.get("comments")
        if comments and isinstance(original, str) and original.strip() == comments:
            pass  # unchanged: keep the original scalar style
        elif comments:
            doc["comments"] = comments + ("\n" if "\n" in comments else "")
        else:
            doc.pop("comments", None)
        for section, table in self.sections.items():
            rows, unchanged = table.rows()
            if unchanged and len(rows) == len(doc.get(section) or ()):
                continue  # unchanged: keep the original list and its comments
            if rows:
                doc[section] = rows
            else:
                doc.pop(section, None)
        return doc

    def _section_changed(self) -> None:
        self._update_tab_titles()
        self.changed.emit()

    def _update_tab_titles(self) -> None:
        for index, section in enumerate(COMPONENTS):
            count = self.sections[section].table.rowCount()
            self.tabs.setTabText(index, f"{section} ({count})" if count else section)


class DeviceTypeEditor(QDialog):
    """Non-modal editor for the local type folder."""

    saved = Signal(Path)

    def __init__(
        self,
        store: LocalTypeStore,
        config: DeviceTypesConfig,
        pool: QThreadPool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("typeEditor")
        self.setWindowTitle("Device types")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.resize(1180, 780)
        self.store = store
        self.config = config
        self.path: Path | None = None
        self.doc = CommentedMap()
        self.dirty = False
        self._loading = False
        self.runner = TaskRunner(pool, self)
        self.runner.finished.connect(self._lookup_finished)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(12, 8, 12, 8)
        self.buttons: dict[str, QPushButton] = {}
        for name, text, slot in (
            ("new", "New", self.new_type),
            ("save", "Save", self.save),
            ("revert", "Revert", self.revert),
            ("delete", "Delete", self.delete),
            ("validate", "Validate", self.run_validation),
            ("folder", "Open folder", self.open_folder),
        ):
            button = QPushButton(text)
            button.setObjectName(f"typeEditor_{name}")
            button.setProperty("variant", "ghost")
            button.clicked.connect(slot)
            self.buttons[name] = button
            bar.addWidget(button)
        bar.addStretch()
        self.yaml_button = QPushButton("YAML")
        self.table_button = QPushButton("Table")
        for button in (self.yaml_button, self.table_button):
            button.setCheckable(True)
            button.setProperty("segment", True)
            bar.addWidget(button)
        self.yaml_button.setObjectName("typeEditor_yaml")
        self.table_button.setObjectName("typeEditor_table")
        self.table_button.setChecked(True)
        self.yaml_button.clicked.connect(lambda: self.set_mode("yaml"))
        self.table_button.clicked.connect(lambda: self.set_mode("table"))
        layout.addLayout(bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setObjectName("typeTree")
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(220)
        self.tree.currentItemChanged.connect(self._tree_selected)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 4, 12, 8)
        self.title = _label("", "heading")
        self.title.setObjectName("typeTitle")
        self.subtitle = _label("", "secondary")
        self.subtitle.setObjectName("typeSubtitle")
        right_layout.addWidget(self.title)
        right_layout.addWidget(self.subtitle)
        self.lookup_row = QWidget()
        lookup_layout = QHBoxLayout(self.lookup_row)
        lookup_layout.setContentsMargins(0, 0, 0, 0)
        self.spec_url = QLineEdit()
        self.spec_url.setObjectName("typeSpecUrl")
        self.spec_url.setPlaceholderText(
            "techspecs.ui.com page (optional; found by part number or model)"
        )
        self.lookup_button = QPushButton("Look up specs")
        self.lookup_button.setObjectName("typeLookup")
        self.lookup_button.clicked.connect(self.look_up_specs)
        lookup_layout.addWidget(self.spec_url, 1)
        lookup_layout.addWidget(self.lookup_button)
        right_layout.addWidget(self.lookup_row)
        self.notes = _label("", "caption")
        self.notes.setObjectName("typeNotes")
        right_layout.addWidget(self.notes)
        self.stack = QStackedWidget()
        self.table_view = TableView()
        self.table_view.changed.connect(self._edited)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.table_view)
        self.yaml_view = QPlainTextEdit()
        self.yaml_view.setObjectName("typeYaml")
        self.yaml_view.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        # The app style sheet sets a proportional font; YAML needs a fixed one.
        self.yaml_view.setStyleSheet(
            "font-family: 'Cascadia Mono', Consolas, 'DejaVu Sans Mono', monospace;"
        )
        self.yaml_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.yaml_view.textChanged.connect(self._edited)
        self.stack.addWidget(scroll)
        self.stack.addWidget(self.yaml_view)
        right_layout.addWidget(self.stack, 1)
        right_layout.addWidget(_label("Validation", "subheading"))
        self.issues = QListWidget()
        self.issues.setObjectName("typeIssues")
        self.issues.setMaximumHeight(110)
        right_layout.addWidget(self.issues)
        splitter.addWidget(self.tree)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 920])
        layout.addWidget(splitter, 1)
        self.mode = "table"
        self.reload_tree()
        self._show_document(CommentedMap(), None, ("Choose a file or click New.",))

    # -- public ------------------------------------------------------------------

    def open_path(self, path: Path) -> bool:
        if not self._confirm_discard():
            return False
        try:
            doc = self.store.read(path)
        except (DeviceTypeError, OSError) as error:
            QMessageBox.warning(self, "Device types", f"Cannot open the file: {error}")
            return False
        self._show_document(doc, Path(path).resolve(), ())
        self._select_tree(self.path)
        return True

    def open_new(self, doc: CommentedMap, notes: Iterable[str] = ()) -> bool:
        """Show an unsaved definition, for example a draft from UniFi."""
        if not self._confirm_discard():
            return False
        self._show_document(doc, None, tuple(notes))
        self.tree.blockSignals(True)
        self.tree.setCurrentItem(None)
        self.tree.blockSignals(False)
        self.dirty = True
        self._update_title()
        return True

    def current_document(self) -> CommentedMap:
        """The document of the active view; raises DeviceTypeError for bad YAML."""
        if self.mode == "yaml":
            return load_yaml(self.yaml_view.toPlainText())
        return self.table_view.document()

    def set_mode(self, mode: str) -> None:
        if mode == self.mode:
            self._sync_mode_buttons()
            return
        try:
            doc = self.current_document()
        except DeviceTypeError as error:
            self._show_issues((Issue("error", "YAML", str(error)),))
            self._sync_mode_buttons()
            return
        self.mode = mode
        self._loading = True
        if mode == "yaml":
            self.yaml_view.setPlainText(dump_yaml(doc))
            self.stack.setCurrentWidget(self.yaml_view)
        else:
            self.table_view.set_document(doc)
            self.stack.setCurrentIndex(0)
        self._loading = False
        self._sync_mode_buttons()

    # -- actions -------------------------------------------------------------------

    def new_type(self) -> None:
        manufacturer = ""
        item = self.tree.currentItem()
        if item is not None:
            manufacturer = (item.parent() or item).text(0)
        self.open_new(
            new_document(manufacturer, ""), ("Fill in the fields, then Save.",)
        )

    def save(self) -> bool:
        try:
            doc = self.current_document()
            target = self.store.path_for(doc)
        except DeviceTypeError as error:
            self._show_issues((Issue("error", "", str(error)),))
            return False
        issues = validate(doc, target)
        self._show_issues(issues)
        problems = errors(issues)
        if problems:
            answer = QMessageBox.question(
                self,
                "Save device type",
                f"The definition has {len(problems)} error(s). Save it anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        try:
            path = self.store.write(doc, previous=self.path)
        except (DeviceTypeError, OSError) as error:
            self._show_issues((Issue("error", "file", str(error)),))
            return False
        self.reload_tree()
        self._show_document(self.store.read(path), path, ())
        self._select_tree(path)
        self.saved.emit(path)
        return True

    def revert(self) -> None:
        if self.path is not None:
            self.dirty = False
            self.open_path(self.path)

    def delete(self) -> None:
        if self.path is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete device type",
            f"Delete {self.path.name} from the local type folder?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(self.path)
        self.dirty = False
        self.reload_tree()
        self._show_document(CommentedMap(), None, ("The file was deleted.",))

    def run_validation(self) -> None:
        try:
            doc = self.current_document()
        except DeviceTypeError as error:
            self._show_issues((Issue("error", "YAML", str(error)),))
            return
        try:
            target = self.path or self.store.path_for(doc)
        except DeviceTypeError:
            target = None
        self._show_issues(validate(doc, target))

    def open_folder(self) -> None:
        self.store.folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.folder)))

    def look_up_specs(self) -> None:
        try:
            doc = self.current_document()
        except DeviceTypeError as error:
            self._show_issues((Issue("error", "YAML", str(error)),))
            return
        url = self.spec_url.text().strip()
        model = str(doc.get("model") or "")
        part = str(doc.get("part_number") or "")
        self.lookup_button.setEnabled(False)
        self.notes.setText("Looking up techspecs.ui.com...")

        def task():
            with client() as http:
                if url:
                    return fetch_url(url, http)
                return lookup(model, part, http)

        self.runner.start(task)

    # -- internals -----------------------------------------------------------------

    def reload_tree(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        folders: dict[str, QTreeWidgetItem] = {}
        for item in self.store.files():
            folder = folders.get(item.manufacturer)
            if folder is None:
                folder = QTreeWidgetItem([item.manufacturer])
                folder.setFlags(folder.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.tree.addTopLevelItem(folder)
                folders[item.manufacturer] = folder
            child = QTreeWidgetItem([item.name])
            child.setData(0, PATH_ROLE, str(item.path.resolve()))
            child.setToolTip(0, str(item.path))
            folder.addChild(child)
        self.tree.expandAll()
        self.tree.blockSignals(False)

    def _select_tree(self, path: Path | None) -> None:
        self.tree.blockSignals(True)
        for index in range(self.tree.topLevelItemCount()):
            folder = self.tree.topLevelItem(index)
            for child_index in range(folder.childCount()):
                child = folder.child(child_index)
                if path is not None and child.data(0, PATH_ROLE) == str(path):
                    self.tree.setCurrentItem(child)
        self.tree.blockSignals(False)

    def _tree_selected(self, item: QTreeWidgetItem | None, previous=None) -> None:
        if item is None or not item.data(0, PATH_ROLE):
            return
        path = Path(item.data(0, PATH_ROLE))
        if path == self.path:
            return
        if not self.open_path(path):
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(previous)
            self.tree.blockSignals(False)

    def _show_document(
        self, doc: CommentedMap, path: Path | None, notes: tuple[str, ...]
    ) -> None:
        self._loading = True
        self.doc = doc
        self.path = path
        self.table_view.set_document(doc)
        self.yaml_view.setPlainText(dump_yaml(doc) if doc else "")
        self.stack.setCurrentIndex(0 if self.mode == "table" else 1)
        self._loading = False
        self.dirty = False
        self.notes.setText("\n".join(notes))
        self.spec_url.clear()
        self._update_title()
        if doc:
            try:
                target = path or self.store.path_for(doc)
            except DeviceTypeError:
                target = None
            self._show_issues(validate(doc, target))
        else:
            self.issues.clear()

    def _update_title(self) -> None:
        doc = self.doc
        name = str(doc.get("model") or doc.get("part_number") or "New device type")
        self.title.setText(name + (" *" if self.dirty else ""))
        if self.path is not None:
            self.subtitle.setText(str(self.path))
        else:
            self.subtitle.setText("Not saved yet")
        has_doc = bool(doc) or self.dirty
        self.buttons["save"].setEnabled(has_doc)
        self.buttons["validate"].setEnabled(has_doc)
        self.buttons["revert"].setEnabled(self.path is not None)
        self.buttons["delete"].setEnabled(self.path is not None)
        ubiquiti = str(doc.get("manufacturer") or "").strip().lower() == "ubiquiti"
        self.lookup_row.setVisible(ubiquiti and self.config.use_techspecs)
        self.lookup_button.setEnabled(not self.runner.busy)

    def _edited(self) -> None:
        if self._loading:
            return
        self.dirty = True
        try:
            self.doc = self.current_document()
        except DeviceTypeError:
            pass
        self._update_title()

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            "Discard the unsaved changes of this device type?",
        )
        return answer == QMessageBox.StandardButton.Yes

    def _lookup_finished(self, result: object) -> None:
        self.lookup_button.setEnabled(True)
        if isinstance(result, TechSpec):
            try:
                doc = self.current_document()
            except DeviceTypeError as error:
                self.notes.setText(str(error))
                return
            notes = merge_spec(doc, result)
            self._loading = True
            self.table_view.set_document(doc)
            self.yaml_view.setPlainText(dump_yaml(doc))
            self._loading = False
            self.doc = doc
            self.dirty = True
            self.notes.setText(
                f"Found {result.title} ({result.sku}). " + " ".join(notes)
            )
            self._update_title()
        elif result is None:
            self.notes.setText(
                "No techspecs page found for this model. Enter the page URL and "
                "look up again."
            )
        else:
            self.notes.setText(f"Lookup failed: {result}")

    def _show_issues(self, issues: Iterable[Issue]) -> None:
        self.issues.clear()
        issues = tuple(issues)
        if not issues:
            item = QListWidgetItem("No problems found.")
            item.setForeground(theme.tone_qcolor("success"))
            self.issues.addItem(item)
            return
        for issue in issues:
            item = QListWidgetItem(str(issue))
            tone = "danger" if issue.level == "error" else "warning"
            item.setForeground(theme.tone_qcolor(tone))
            self.issues.addItem(item)

    def _sync_mode_buttons(self) -> None:
        self.yaml_button.setChecked(self.mode == "yaml")
        self.table_button.setChecked(self.mode == "table")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        # Only a visible window asks; hidden ones (shutdown) just close.
        if not self.isVisible() or self._confirm_discard():
            self.dirty = False
            event.accept()
        else:
            event.ignore()
