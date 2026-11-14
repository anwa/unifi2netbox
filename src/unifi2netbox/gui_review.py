"""Review widgets: device table model, badges, detail panel and confirmation."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from unifi2netbox import theme
from unifi2netbox.review import (
    CATEGORY_LABELS,
    CREATE,
    FIELD_LABELS,
    IN_SYNC,
    NETBOX_ONLY,
    UPDATE,
    ReviewRow,
    ReviewState,
)
from unifi2netbox.write_plan import OperationType, WritePlan

COL_SELECT, COL_DEVICE, COL_CHANGE, COL_MODEL, COL_NETBOX, COL_STATUS = range(6)
HEADERS = ("", "Device", "Change", "UniFi model", "In NetBox", "Status")
_ROOT = QModelIndex()
KEY_ROLE = Qt.ItemDataRole.UserRole + 1
TONE_ROLE = Qt.ItemDataRole.UserRole + 2

CATEGORY_TONES = {
    CREATE: "accent",
    UPDATE: "warning",
    IN_SYNC: "success",
    NETBOX_ONLY: "neutral",
}
OUTCOME_TONES = {"success": "success", "skipped": "warning", "failed": "danger"}


def label(text: str = "", role: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if role:
        widget.setProperty("role", role)
    return widget


def type_name(state: ReviewState, type_id: str) -> str:
    for item_id, manufacturer, model in state.device_types:
        if item_id == type_id:
            return f"{manufacturer} {model}"
    return ""


def type_model(state: ReviewState, type_id: str) -> str:
    for item_id, _manufacturer, model in state.device_types:
        if item_id == type_id:
            return model
    return ""


def status_text(item: ReviewRow) -> tuple[str, str]:
    """(text, tone) for the status column."""
    if item.outcome is not None and item.outcome.status == "success":
        return {
            "verified": ("Verified", "success"),
            "mismatch": ("Mismatch", "danger"),
            "unverified": ("Not verified", "warning"),
        }.get(item.outcome.verification, ("Written", "success"))
    if item.outcome is not None:
        status = item.outcome.status
        text = {
            "success": "Written",
            "skipped": "Skipped",
            "failed": "Failed",
        }.get(status, status.capitalize())
        return text, OUTCOME_TONES.get(status, "neutral")
    if not item.selected and item.category in (CREATE, UPDATE):
        return "Not selected", "neutral"
    if item.attention:
        return item.note or "Needs attention", "danger"
    if item.category in (CREATE, UPDATE):
        return "Ready", "success"
    return "", "neutral"


class ReviewTableModel(QAbstractTableModel):
    selection_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.state = ReviewState()
        self.category = "all"
        self.search = ""
        self.items: tuple[ReviewRow, ...] = ()

    def set_state(self, state: ReviewState) -> None:
        self.state = state
        self.reload()

    def set_filter(self, category: str, search: str) -> None:
        self.category = category
        self.search = search
        self.reload()

    def reload(self) -> None:
        self.beginResetModel()
        self.items = self.state.rows(self.category, self.search)
        self.endResetModel()

    def refresh_rows(self) -> None:
        """Re-read row facts without changing which rows are shown."""
        keys = [item.key for item in self.items]
        fresh = {item.key: item for item in self.state.rows()}
        self.items = tuple(fresh[key] for key in keys if key in fresh)
        if self.items:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self.items) - 1, len(HEADERS) - 1)
            )

    def key_at(self, row: int) -> str:
        return self.items[row].key if 0 <= row < len(self.items) else ""

    def row_of(self, key: str) -> int:
        return next((i for i, item in enumerate(self.items) if item.key == key), -1)

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
        ):
            return HEADERS[section]
        return None

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == COL_SELECT and self._checkable(index.row()):
            base |= Qt.ItemFlag.ItemIsUserCheckable
        return base

    def _checkable(self, row: int) -> bool:
        return 0 <= row < len(self.items) and self.items[row].category in (
            CREATE,
            UPDATE,
        )

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role=Qt.ItemDataRole.DisplayRole,
    ):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        column = index.column()
        if role == KEY_ROLE:
            return item.key
        if column == COL_SELECT and role == Qt.ItemDataRole.CheckStateRole:
            if not self._checkable(index.row()):
                return None
            return Qt.CheckState.Checked if item.selected else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(item, column)
        if role == TONE_ROLE:
            if column == COL_CHANGE:
                return CATEGORY_TONES.get(item.category, "neutral")
            if column == COL_STATUS:
                return status_text(item)[1]
        if role == Qt.ItemDataRole.ToolTipRole:
            if column == COL_STATUS and item.outcome is not None:
                return item.outcome.message
            if column == COL_STATUS and item.note:
                return item.note
            if column == COL_NETBOX and item.row.suggested_device_types:
                return f"Suggestions: {item.row.suggested_device_types}"
        return None

    def _display(self, item: ReviewRow, column: int) -> str:
        if column == COL_DEVICE:
            return item.name
        if column == COL_CHANGE:
            return CATEGORY_LABELS.get(item.category, item.category)
        if column == COL_MODEL:
            return item.source_value("model")
        if column == COL_NETBOX:
            if item.category == CREATE:
                chosen = type_model(
                    self.state, self.state.type_by_key.get(item.key, "")
                )
                return chosen or "Choose type"
            return item.row.target_label
        if column == COL_STATUS:
            return status_text(item)[0]
        return ""

    def setData(
        self,
        index: QModelIndex | QPersistentModelIndex,
        value,
        role=Qt.ItemDataRole.EditRole,
    ) -> bool:
        if (
            index.column() != COL_SELECT
            or role != Qt.ItemDataRole.CheckStateRole
            or not self._checkable(index.row())
        ):
            return False
        checked = Qt.CheckState(value) == Qt.CheckState.Checked
        self.state.set_device_selected(self.items[index.row()].key, checked)
        self.refresh_rows()
        self.selection_changed.emit()
        return True


class BadgeDelegate(QStyledItemDelegate):
    """Paint the cell text as a rounded pill in its semantic tone."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        if not text:
            super().paint(painter, option, index)
            return
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(theme.colors().accent_soft))
        tone = str(index.data(TONE_ROLE) or "neutral")
        foreground, background = theme.tone_colors(tone)
        metrics = option.fontMetrics
        width = min(metrics.horizontalAdvance(text) + 18, option.rect.width() - 8)
        height = metrics.height() + 6
        rect = QRectF(
            option.rect.left() + 6,
            option.rect.center().y() - height / 2,
            width,
            height,
        )
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(rect, height / 2, height / 2)
        painter.fillPath(path, QColor(background))
        painter.setPen(QColor(foreground))
        elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(width) - 14)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, elided)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        size = super().sizeHint(option, index)
        return QSize(size.width() + 24, max(size.height(), 34))


class DetailPanel(QScrollArea):
    """Everything about one device: notes, NetBox choices, field selection."""

    changed = Signal()
    apply_requested = Signal(str)
    export_requested = Signal(str)
    copy_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setMinimumWidth(320)
        self.state = ReviewState()
        self.key = ""
        self.body = QWidget()
        self.layout_ = QVBoxLayout(self.body)
        self.layout_.setContentsMargins(16, 12, 16, 16)
        self.layout_.setSpacing(10)
        self.setWidget(self.body)
        self.show_placeholder()

    def _clear(self) -> None:
        while self.layout_.count():
            item = self.layout_.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                _delete_layout(item.layout())

    def show_placeholder(self) -> None:
        self._clear()
        self.key = ""
        self.layout_.addWidget(label("Select a device to see details.", "secondary"))
        self.layout_.addStretch()

    def show_device(self, state: ReviewState, key: str) -> None:
        self.state = state
        item = state.row(key)
        if item is None:
            self.show_placeholder()
            return
        self.key = key
        self._clear()
        title = label(item.name, "heading")
        title.setObjectName("detailTitle")
        self.layout_.addWidget(title)
        self.layout_.addWidget(label(_subtitle(item), "secondary"))

        if item.outcome is not None:
            tone = {"success": "success", "skipped": "warning"}.get(
                item.outcome.status, "danger"
            )
            text = item.outcome.message
            if item.outcome.verification:
                tone = {"mismatch": "danger", "unverified": "warning"}.get(
                    item.outcome.verification, tone
                )
                text += f"\nRead-back: {item.outcome.verification_detail}"
            self.layout_.addWidget(banner(text, tone))
        elif item.attention and item.note:
            self.layout_.addWidget(banner(item.note, "danger"))

        if item.category == CREATE:
            self._add_create_choices(item)
        self._add_fields(item)

        if item.row.suggested_device_types and item.category == CREATE:
            self.layout_.addWidget(label("Type suggestions", "subheading"))
            self.layout_.addWidget(
                label(item.row.suggested_device_types.replace("; ", "\n"), "caption")
            )

        actions = QHBoxLayout()
        if item.category in (CREATE, UPDATE):
            apply_button = QPushButton("Apply this device")
            apply_button.setObjectName("detailApply")
            apply_button.setToolTip("Write only this device to NetBox")
            apply_button.clicked.connect(lambda: self.apply_requested.emit(self.key))
            actions.addWidget(apply_button)
        if item.category != NETBOX_ONLY:
            export_button = QPushButton("Export UniFi data")
            export_button.setObjectName("detailExport")
            export_button.setProperty("variant", "ghost")
            export_button.clicked.connect(lambda: self.export_requested.emit(self.key))
            actions.addWidget(export_button)
        copy_button = QPushButton("Copy details")
        copy_button.setObjectName("detailCopy")
        copy_button.setProperty("variant", "ghost")
        copy_button.clicked.connect(lambda: self.copy_requested.emit(self.key))
        actions.addWidget(copy_button)
        actions.addStretch()
        self.layout_.addLayout(actions)
        self.layout_.addStretch()

    def _add_create_choices(self, item: ReviewRow) -> None:
        self.layout_.addWidget(
            label("NetBox settings for the new device", "subheading")
        )
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        type_combo = QComboBox()
        type_combo.setObjectName("choiceType")
        type_combo.addItem("Choose a device type", "")
        for type_id, manufacturer, model in self.state.device_types:
            type_combo.addItem(f"{manufacturer} {model}", type_id)
        type_combo.setCurrentIndex(
            max(0, type_combo.findData(self.state.type_by_key.get(item.key, "")))
        )
        type_combo.currentIndexChanged.connect(
            lambda _i, c=type_combo: self._choose("type", str(c.currentData() or ""))
        )
        form.addRow("Device type", type_combo)
        for kind, title, values, chosen in (
            ("role", "Role", self.state.roles, self.state.role_by_key),
            ("site", "Site", self.state.sites, self.state.site_by_key),
            ("status", "Status", self.state.statuses, self.state.status_by_key),
        ):
            combo = QComboBox()
            combo.setObjectName(f"choice{kind.capitalize()}")
            if values:
                combo.addItems(list(values))
                current = chosen.get(item.key, "")
                if current in values:
                    combo.setCurrentText(current)
                combo.currentTextChanged.connect(
                    lambda value, k=kind: self._choose(k, value)
                )
            else:
                combo.addItem(f"No {title.lower()}s in NetBox")
                combo.setEnabled(False)
            form.addRow(title, combo)
        self.layout_.addLayout(form)

    def _choose(self, kind: str, value: str) -> None:
        self.state.set_choice(kind, self.key, value)
        self.changed.emit()

    def _add_fields(self, item: ReviewRow) -> None:
        heading = {
            CREATE: "Values from UniFi",
            UPDATE: "Changes",
            IN_SYNC: "Fields",
            NETBOX_ONLY: "NetBox values",
        }.get(item.category, "Fields")
        self.layout_.addWidget(label(heading, "subheading"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        column_titles = (
            ("", "Field", "UniFi")
            if item.category == CREATE
            else ("", "Field", "NetBox", "UniFi")
        )
        for column, text in enumerate(column_titles):
            grid.addWidget(label(text, "caption"), 0, column)
        row_index = 1
        for field in item.device.fields:
            if not field.supported:
                continue
            if item.category == CREATE and not field.source_value:
                continue
            if item.category != CREATE and not (
                field.source_value or field.target_value
            ):
                continue
            if field.selectable and item.category == UPDATE:
                box = QCheckBox()
                box.setObjectName(f"field_{field.name}")
                box.setChecked(field.selected)
                box.toggled.connect(
                    lambda checked, name=field.name: self._toggle_field(name, checked)
                )
                grid.addWidget(box, row_index, 0)
            name = label(FIELD_LABELS.get(field.name, field.name))
            grid.addWidget(name, row_index, 1)
            if item.category == CREATE:
                grid.addWidget(label(field.source_value), row_index, 2)
            else:
                grid.addWidget(
                    label(field.target_value or "-", "secondary"), row_index, 2
                )
                value = label(field.source_value or "-")
                if field.changed and not field.selectable:
                    value.setToolTip(field.provenance)
                    value.setProperty("role", "secondary")
                grid.addWidget(value, row_index, 3)
            row_index += 1
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3 if item.category != CREATE else 2, 1)
        self.layout_.addLayout(grid)
        if item.category == UPDATE:
            self.layout_.addWidget(
                label(
                    "Only checked fields are written. Grey values are shown for "
                    "reference and are not written by updates.",
                    "caption",
                )
            )

    def _toggle_field(self, name: str, checked: bool) -> None:
        self.state.set_field_selected(self.key, name, checked)
        self.changed.emit()


def banner(text: str, tone: str) -> QFrame:
    frame = QFrame()
    frame.setProperty("banner", tone)
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(12, 8, 12, 8)
    message = label(text)
    message.setObjectName("bannerText")
    layout.addWidget(message, 1)
    return frame


class ConfirmDialog(QDialog):
    """One summary before NetBox writes; blockers keep the action disabled."""

    def __init__(
        self,
        state: ReviewState,
        plan: WritePlan,
        *,
        dry_run: bool,
        single: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        creates = sum(
            op.operation_type == OperationType.CREATE_DEVICE for op in plan.operations
        )
        updates = len(plan.operations) - creates
        self.setWindowTitle("Dry run" if dry_run else "Apply to NetBox")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)
        heading = (
            "Simulate these changes" if dry_run else "Write these changes to NetBox"
        )
        layout.addWidget(label(heading, "heading"))
        parts = []
        if creates:
            parts.append(f"{creates} new device{'s' if creates != 1 else ''}")
        if updates:
            parts.append(f"{updates} changed device{'s' if updates != 1 else ''}")
        summary = label(" and ".join(parts) or "No changes", "subheading")
        summary.setObjectName("confirmSummary")
        layout.addWidget(summary)
        names = [op.source_label or op.target_label for op in plan.operations]
        preview = ", ".join(names[:6]) + (
            f" and {len(names) - 6} more" if len(names) > 6 else ""
        )
        if preview:
            layout.addWidget(label(preview, "secondary"))
        self.blockers = state.plan_blockers(plan)
        warnings = state.plan_warnings(plan)
        if self.blockers:
            layout.addWidget(banner("\n".join(self.blockers[:6]), "danger"))
        if warnings:
            layout.addWidget(banner("\n".join(warnings[:6]), "warning"))
        layout.addWidget(
            label(
                (
                    "Nothing is written. Each operation re-reads NetBox and reports "
                    "what would happen."
                    if dry_run
                    else "NetBox is re-read before every write; changed or missing "
                    "targets are skipped. UniFi is never modified."
                ),
                "caption",
            )
        )
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        count = len(plan.operations)
        action_text = (
            "Run dry run"
            if dry_run
            else (
                "Apply device"
                if single
                else f"Apply {count} change{'s' if count != 1 else ''}"
            )
        )
        self.confirm_button = QPushButton(action_text)
        self.confirm_button.setObjectName("confirmApply")
        self.confirm_button.setProperty("variant", "primary")
        self.confirm_button.setDefault(True)
        self.confirm_button.setEnabled(bool(plan.operations) and not self.blockers)
        self.confirm_button.clicked.connect(self.accept)
        buttons.addWidget(self.confirm_button)
        layout.addLayout(buttons)


def _subtitle(item: ReviewRow) -> str:
    if item.category == CREATE:
        model = item.source_value("model")
        return f"New in NetBox{' · UniFi ' + model if model else ''}"
    if item.category == UPDATE:
        return f"Matched to NetBox device {item.row.target_label}"
    if item.category == IN_SYNC:
        return f"In sync with NetBox device {item.row.target_label}"
    return "Only in NetBox. The app never deletes devices."


def _delete_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child = item.layout()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif child is not None:
            _delete_layout(child)
    layout.deleteLater()


def device_summary(item: ReviewRow) -> str:
    """Plain-text description for the clipboard."""
    lines = [item.name, _subtitle(item)]
    if item.note:
        lines.append(f"Note: {item.note}")
    if item.outcome is not None:
        lines.append(f"Result: {item.outcome.status} - {item.outcome.message}")
        if item.outcome.verification:
            lines.append(
                f"Read-back: {item.outcome.verification} - "
                f"{item.outcome.verification_detail}"
            )
    for field in item.device.fields:
        if field.supported and (field.source_value or field.target_value):
            lines.append(
                f"{FIELD_LABELS.get(field.name, field.name)}: "
                f"NetBox={field.target_value or '-'} UniFi={field.source_value or '-'}"
            )
    return "\n".join(lines)
