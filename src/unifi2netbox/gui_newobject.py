"""Small "New ..." dialogs that create a NetBox object right away.

One dialog class for manufacturers, platforms, owners, owner groups, tags and
inventory item roles, built from ``netbox_objects.SPECS``. The slug follows
the name until it is edited; references (an owner's group, a platform's
manufacturer) are drop-downs with their own **New...**. **Create** runs on the
thread pool; the result is shown in the dialog, and a created or already
existing object is returned in ``created``.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from unifi2netbox.devicetypes import slugify
from unifi2netbox.gui_jobs import TaskRunner
from unifi2netbox.netbox_catalog import CatalogObject, NetBoxCatalog
from unifi2netbox.netbox_objects import (
    SPECS,
    TITLES,
    CreateResult,
    ObjectCreateError,
    payload_for,
)

# (kind, values, catalog) -> CreateResult; runs off the GUI thread.
Creator = Callable[[str, dict, NetBoxCatalog], CreateResult]


class NewObjectDialog(QDialog):
    def __init__(
        self,
        kind: str,
        catalog: NetBoxCatalog,
        creator: Creator,
        pool: QThreadPool,
        parent: QWidget | None = None,
        name: str = "",
    ) -> None:
        super().__init__(parent)
        self.kind = kind
        self.catalog = catalog
        self.creator = creator
        self.pool = pool
        self.created: CatalogObject | None = None
        self._slug_edited = False
        self.setObjectName(f"newObject_{kind}")
        self.setWindowTitle(f"New {TITLES[kind]}")
        self.setMinimumWidth(420)
        self.runner = TaskRunner(pool, self)
        self.runner.finished.connect(self._finished)
        layout = QVBoxLayout(self)
        intro = QLabel(
            f"Creates the {TITLES[kind]} in NetBox as soon as you click Create."
        )
        intro.setWordWrap(True)
        intro.setProperty("role", "secondary")
        layout.addWidget(intro)
        form = QFormLayout()
        self.fields: dict[str, QLineEdit | QComboBox] = {}
        for spec in SPECS[kind]:
            label = f"{spec.label} *" if spec.required else spec.label
            if spec.kind == "reference":
                combo = QComboBox()
                combo.setEditable(True)
                combo.setObjectName(f"field_{spec.name}")
                self._fill(combo, spec.reference)
                new = QToolButton()
                new.setText("New...")
                new.setObjectName(f"new_{spec.reference}")
                new.clicked.connect(
                    lambda _c=False, s=spec, c=combo: self._new_reference(
                        s.reference, c
                    )
                )
                row = QHBoxLayout()
                row.addWidget(combo, 1)
                row.addWidget(new)
                form.addRow(label, row)
                self.fields[spec.name] = combo
            else:
                edit = QLineEdit()
                edit.setObjectName(f"field_{spec.name}")
                self.fields[spec.name] = edit
                if spec.kind == "color":
                    pick = QToolButton()
                    pick.setText("...")
                    pick.clicked.connect(lambda _c=False, e=edit: self._pick_color(e))
                    row = QHBoxLayout()
                    row.addWidget(edit, 1)
                    row.addWidget(pick)
                    form.addRow(label, row)
                else:
                    form.addRow(label, edit)
        layout.addLayout(form)
        if "name" in self.fields:
            self.fields["name"].textChanged.connect(self._name_changed)
            self.fields["name"].setText(name)
        if "slug" in self.fields:
            self.fields["slug"].textEdited.connect(self._slug_touched)
        self.message = QLabel("")
        self.message.setObjectName("newObjectMessage")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.create_button = QPushButton("Create")
        self.create_button.setObjectName("newObjectCreate")
        self.create_button.setProperty("variant", "primary")
        self.create_button.setDefault(True)
        self.create_button.clicked.connect(self.create)
        buttons.addWidget(cancel)
        buttons.addWidget(self.create_button)
        layout.addLayout(buttons)

    def values(self) -> dict[str, str]:
        result = {}
        for name, widget in self.fields.items():
            result[name] = (
                widget.currentText() if isinstance(widget, QComboBox) else widget.text()
            )
        return result

    def create(self) -> None:
        values = self.values()
        try:
            payload_for(self.kind, values, self.catalog)
        except ObjectCreateError as error:
            self.message.setText(str(error))
            return
        self.create_button.setEnabled(False)
        self.message.setText("Creating in NetBox...")
        kind, catalog, creator = self.kind, self.catalog, self.creator
        self.runner.start(lambda: creator(kind, values, catalog))

    def _finished(self, result: object) -> None:
        self.create_button.setEnabled(True)
        if isinstance(result, Exception):
            self.message.setText(f"Not created: {result}")
            return
        if not isinstance(result, CreateResult) or result.item is None:
            message = result.message if isinstance(result, CreateResult) else result
            self.message.setText(f"Not created: {message}")
            return
        self.created = result.item
        self.catalog = self.catalog.with_object(self.kind, result.item)
        self.message.setText(result.message)
        self.accept()

    def _fill(self, combo: QComboBox, kind: str, current: str = "") -> None:
        combo.clear()
        combo.addItem("")
        combo.addItems(self.catalog.names(kind))
        combo.setCurrentText(current)

    def _new_reference(self, kind: str, combo: QComboBox) -> None:
        dialog = NewObjectDialog(kind, self.catalog, self.creator, self.pool, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.created:
            self.catalog = dialog.catalog
            self._fill(combo, kind, dialog.created.name)

    def _name_changed(self, text: str) -> None:
        if "slug" in self.fields and not self._slug_edited:
            self.fields["slug"].setText(slugify(text))

    def _slug_touched(self, _text: str) -> None:
        self._slug_edited = True

    def _pick_color(self, edit: QLineEdit) -> None:
        start = QColor(f"#{edit.text().lstrip('#')}") if edit.text() else QColor()
        color = QColorDialog.getColor(start, self, "Choose a color")
        if color.isValid():
            edit.setText(color.name().lstrip("#"))
