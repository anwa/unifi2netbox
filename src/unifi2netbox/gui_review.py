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
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from unifi2netbox import theme
from unifi2netbox.journal_store import StoredRun
from unifi2netbox.networks import (
    CONFLICT as NET_CONFLICT,
)
from unifi2netbox.networks import (
    CREATE as NET_CREATE,
)
from unifi2netbox.networks import (
    UPDATE as NET_UPDATE,
)
from unifi2netbox.networks import NetworkPlan, NetworkPlanRow
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

    def show_placeholder(self, text: str = "Select a device to see details.") -> None:
        self._clear()
        self.key = ""
        placeholder = label(text, "secondary")
        placeholder.setObjectName("detailPlaceholder")
        self.layout_.addWidget(placeholder)
        self.layout_.addStretch()

    def show_network(self, state: ReviewState, key: str) -> None:
        self.state = state
        row = state.network_row(key)
        plan = state.network_plan
        if row is None or plan is None:
            self.show_placeholder("Select a network to see details.")
            return
        self.key = key
        self._clear()
        title = label(row.name, "heading")
        title.setObjectName("detailTitle")
        self.layout_.addWidget(title)
        subtitle = f"UniFi network, VLAN {row.vid}"
        if row.subnet:
            subtitle += f", {row.subnet}"
        self.layout_.addWidget(label(subtitle, "secondary"))
        outcomes = state.network_outcomes.get(key, [])
        if outcomes:
            text = "\n".join(
                f"{o.status}: {o.message}"
                + (f" (read-back {o.verification})" if o.verification else "")
                for o in outcomes
            )
            tone = (
                "danger"
                if any(o.status == "failed" for o in outcomes)
                else (
                    "success"
                    if all(o.status == "success" for o in outcomes)
                    else "warning"
                )
            )
            self.layout_.addWidget(banner(text, tone))
        elif row.notes:
            tone = "danger" if row.category == NET_CONFLICT else "neutral"
            self.layout_.addWidget(banner("\n".join(row.notes), tone))

        group = plan.group
        self.layout_.addWidget(label("NetBox", "subheading"))
        if group is not None:
            group_text = f"VLAN group '{group.name}' for site {group.site_name}" + (
                " will be created." if group.action == NET_CREATE else " exists."
            )
            self.layout_.addWidget(label(group_text, "caption"))
        for part, action, selected, text in (
            ("vlan", row.vlan_action, row.vlan_selected, _vlan_text(row)),
            ("prefix", row.prefix_action, row.prefix_selected, _prefix_text(row)),
        ):
            if (
                action in (NET_CREATE, NET_UPDATE)
                and row.enabled
                and row.category != NET_CONFLICT
            ):
                box = QCheckBox(text)
                box.setObjectName(f"network_{part}")
                box.setChecked(selected)
                box.toggled.connect(
                    lambda checked, p=part: self._toggle_network(p, checked)
                )
                self.layout_.addWidget(box)
            elif text:
                self.layout_.addWidget(label(text, "secondary"))
        self.layout_.addWidget(
            label(
                "Only checked items are written. Prefixes are linked to the VLAN "
                "and scoped to the NetBox site; nothing is deleted.",
                "caption",
            )
        )
        self.layout_.addStretch()

    def _toggle_network(self, part: str, checked: bool) -> None:
        self.state.set_network_selected(self.key, part, checked)
        self.changed.emit()

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

        self._add_ports(item)

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

    def _add_ports(self, item: ReviewRow) -> None:
        matches = self.state.ports_for(item.key)
        if not matches:
            return
        ports = [m.port for m in matches if m.port is not None]
        up = sum(port.link_state == "UP" for port in ports)
        heading = label(f"Ports ({len(ports)})", "subheading")
        heading.setObjectName("portsHeading")
        self.layout_.addWidget(heading)
        summary = f"{up} up, {len(ports) - up} down. Link and speed are live values"
        summary += " and never written."
        if item.category == CREATE:
            summary += " NetBox adds interfaces from the device type on create."
        self.layout_.addWidget(label(summary, "caption"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(3)
        titles = ("Port", "NetBox", "Type", "Link", "PoE")
        for column, text in enumerate(titles):
            grid.addWidget(label(text, "caption"), 0, column)
        notes: list[str] = []
        for row, match in enumerate(matches, start=1):
            port, interface = match.port, match.interface
            name = str(port.idx) if port else "-"
            values = (
                name,
                interface.name if interface else "-",
                _port_type(port) if port else (interface.type if interface else ""),
                _port_link(port) if port else "",
                _port_poe(port) if port else "",
            )
            for column, value in enumerate(values):
                cell = label(value, "secondary" if column == 3 else "")
                if match.notes:
                    cell.setToolTip("\n".join(match.notes))
                grid.addWidget(cell, row, column)
            for note in match.notes:
                prefix = f"Port {port.idx}" if port else interface.name
                notes.append(f"{prefix}: {note}")
        grid.setColumnStretch(1, 1)
        self.layout_.addLayout(grid)
        if notes and item.category != CREATE:
            shown = notes[:8]
            if len(notes) > 8:
                shown.append(f"... and {len(notes) - 8} more")
            note_label = label("\n".join(shown), "caption")
            note_label.setObjectName("portNotes")
            self.layout_.addWidget(note_label)

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
        network_plan: NetworkPlan | None = None,
    ) -> None:
        super().__init__(parent)
        creates = sum(
            op.operation_type == OperationType.CREATE_DEVICE for op in plan.operations
        )
        updates = len(plan.operations) - creates
        group_ops, vlan_ops, prefix_ops = network_actions(network_plan)
        network_ops = group_ops + vlan_ops + prefix_ops
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
        if vlan_ops:
            parts.append(f"{vlan_ops} VLAN{'s' if vlan_ops != 1 else ''}")
        if prefix_ops:
            parts.append(f"{prefix_ops} prefix{'es' if prefix_ops != 1 else ''}")
        if group_ops:
            parts.append("1 VLAN group")
        summary = label(", ".join(parts) or "No changes", "subheading")
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
                    "Nothing is written. UniFi and NetBox are re-read and each "
                    "operation reports what would happen."
                    if dry_run
                    else "UniFi and NetBox are re-read before writing; devices that "
                    "changed since the preview are skipped. UniFi is never modified."
                ),
                "caption",
            )
        )
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        count = len(plan.operations) + network_ops
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
        self.confirm_button.setEnabled(bool(count) and not self.blockers)
        self.confirm_button.clicked.connect(self.accept)
        buttons.addWidget(self.confirm_button)
        layout.addLayout(buttons)


_CONNECTOR_NAMES = {"SFPPLUS": "SFP+", "SFP28": "SFP28", "SFP": "SFP"}


def _short_speed(mbps: int) -> str:
    if not mbps:
        return ""
    return f"{mbps / 1000:g}G" if mbps >= 1000 else f"{mbps}M"


def _port_type(port) -> str:
    connector = _CONNECTOR_NAMES.get(port.connector, port.connector)
    return f"{connector} {_short_speed(port.max_speed_mbps)}".strip()


def _port_link(port) -> str:
    if port.link_state == "UP":
        return f"Up {_short_speed(port.speed_mbps)}".strip()
    return port.link_state.capitalize() or "-"


def _port_poe(port) -> str:
    if not port.poe_standard:
        return ""
    state = "off" if port.poe_enabled is False else port.poe_state.lower() or "on"
    return f"{port.poe_standard} ({state})"


def _vlan_text(row: NetworkPlanRow) -> str:
    if row.vlan_action == NET_CREATE:
        return f"Create VLAN {row.vid} '{row.name}'"
    if row.vlan_action == NET_UPDATE:
        return f"Rename VLAN {row.vid} from '{row.netbox_vlan_name}' to '{row.name}'"
    if row.vlan_action == "in_sync":
        return f"VLAN {row.vid} '{row.name}' is in sync."
    return f"VLAN {row.vid} has a conflict."


def _prefix_text(row: NetworkPlanRow) -> str:
    if row.prefix_action == NET_CREATE:
        return f"Create prefix {row.subnet} linked to VLAN {row.vid}"
    if row.prefix_action == NET_UPDATE:
        return f"Link existing prefix {row.subnet} to VLAN {row.vid}"
    if row.prefix_action == "in_sync":
        return f"Prefix {row.subnet} is in sync."
    if row.prefix_action == NET_CONFLICT:
        return f"Prefix {row.subnet} has a conflict."
    return ""


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


class HistoryDialog(QDialog):
    """Recent write runs on the left, their per-device results on the right."""

    COLUMNS = ("Device", "Operation", "Result", "Read-back", "Message")

    def __init__(self, runs: tuple[StoredRun, ...], parent=None) -> None:
        super().__init__(parent)
        self.runs = runs
        self.setWindowTitle("Write history")
        self.resize(980, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.addWidget(label("Write history", "heading"))
        if not runs:
            empty = label(
                "No writes or dry runs yet. Each run is listed here with its results.",
                "secondary",
            )
            empty.setObjectName("historyEmpty")
            layout.addWidget(empty)
        body = QHBoxLayout()
        self.run_list = QListWidget()
        self.run_list.setObjectName("historyRuns")
        self.run_list.setFixedWidth(300)
        for run in runs:
            kind = "Dry run" if run.dry_run else "Applied"
            item = QListWidgetItem(
                f"{run.started_at[:16].replace('T', ' ')}  {kind}\n{run.summary()}"
            )
            item.setToolTip(run.run_id)
            self.run_list.addItem(item)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setObjectName("historyOutcomes")
        self.table.setHorizontalHeaderLabels(list(self.COLUMNS))
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        body.addWidget(self.run_list)
        body.addWidget(self.table, 1)
        layout.addLayout(body, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(close)
        layout.addLayout(footer)
        self.run_list.currentRowChanged.connect(self.show_run)
        if runs:
            self.run_list.setCurrentRow(0)

    def show_run(self, index: int) -> None:
        run = self.runs[index] if 0 <= index < len(self.runs) else None
        outcomes = run.outcomes if run else ()
        self.table.setRowCount(len(outcomes))
        for row, outcome in enumerate(outcomes):
            values = (
                outcome.label,
                outcome.operation_type.replace("_device", ""),
                outcome.status,
                outcome.verification,
                outcome.message,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 4:
                    tip = outcome.message
                    if outcome.verification_detail:
                        tip += f"\n\nRead-back: {outcome.verification_detail}"
                    item.setToolTip(tip)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()


NET_HEADERS = ("", "Network", "VLAN", "Subnet", "Change", "Status")
NET_CHANGE_LABELS = {
    NET_CREATE: ("New", "accent"),
    NET_UPDATE: ("Changed", "warning"),
    NET_CONFLICT: ("Conflict", "danger"),
    "in_sync": ("In sync", "success"),
}


def network_status(state: ReviewState, row: NetworkPlanRow) -> tuple[str, str]:
    outcomes = state.network_outcomes.get(row.key, [])
    if outcomes:
        if any(o.status == "failed" or o.verification == "mismatch" for o in outcomes):
            return "Failed", "danger"
        if all(o.status == "success" for o in outcomes):
            if all(o.verification == "verified" for o in outcomes):
                return "Verified", "success"
            return "Written", "success"
        return "Skipped", "warning"
    if row.category == NET_CONFLICT:
        return row.notes[0] if row.notes else "Conflict", "danger"
    if not row.enabled:
        return "Disabled in UniFi", "neutral"
    if row.selectable and not row.selected:
        return "Not selected", "neutral"
    if row.selected:
        return "Ready", "success"
    return "", "neutral"


class NetworkTableModel(QAbstractTableModel):
    selection_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.state = ReviewState()
        self.search = ""
        self.items: tuple[NetworkPlanRow, ...] = ()

    def set_state(self, state: ReviewState) -> None:
        self.state = state
        self.reload()

    def set_filter(self, search: str) -> None:
        self.search = search
        self.reload()

    def reload(self) -> None:
        self.beginResetModel()
        self.items = self.state.network_rows(self.search)
        self.endResetModel()

    def refresh_rows(self) -> None:
        keys = [row.key for row in self.items]
        fresh = {row.key: row for row in self.state.network_rows()}
        self.items = tuple(fresh[key] for key in keys if key in fresh)
        if self.items:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self.items) - 1, len(NET_HEADERS) - 1),
            )

    def key_at(self, row: int) -> str:
        return self.items[row].key if 0 <= row < len(self.items) else ""

    def row_of(self, key: str) -> int:
        return next((i for i, row in enumerate(self.items) if row.key == key), -1)

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(NET_HEADERS)

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
        ):
            return NET_HEADERS[section]
        return None

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        row = self.items[index.row()] if 0 <= index.row() < len(self.items) else None
        if index.column() == 0 and row is not None and row.enabled and row.selectable:
            base |= Qt.ItemFlag.ItemIsUserCheckable
        return base

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role=Qt.ItemDataRole.DisplayRole,
    ):
        if not index.isValid():
            return None
        row = self.items[index.row()]
        column = index.column()
        if role == KEY_ROLE:
            return row.key
        if column == 0 and role == Qt.ItemDataRole.CheckStateRole:
            if not (row.enabled and row.selectable):
                return None
            return Qt.CheckState.Checked if row.selected else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 1:
                return row.name
            if column == 2:
                return str(row.vid)
            if column == 3:
                return row.subnet or "-"
            if column == 4:
                return NET_CHANGE_LABELS.get(row.category, ("", ""))[0]
            if column == 5:
                return network_status(self.state, row)[0]
        if role == TONE_ROLE:
            if column == 4:
                return NET_CHANGE_LABELS.get(row.category, ("", "neutral"))[1]
            if column == 5:
                return network_status(self.state, row)[1]
        if role == Qt.ItemDataRole.ToolTipRole and row.notes:
            return "\n".join(row.notes)
        return None

    def setData(
        self,
        index: QModelIndex | QPersistentModelIndex,
        value,
        role=Qt.ItemDataRole.EditRole,
    ) -> bool:
        if index.column() != 0 or role != Qt.ItemDataRole.CheckStateRole:
            return False
        row = self.items[index.row()]
        if not (row.enabled and row.selectable):
            return False
        checked = Qt.CheckState(value) == Qt.CheckState.Checked
        self.state.set_network_selected(row.key, "all", checked)
        self.refresh_rows()
        self.selection_changed.emit()
        return True


def network_actions(plan: NetworkPlan | None) -> tuple[int, int, int]:
    """(VLAN group creates, VLAN writes, prefix writes) for selected rows."""
    if plan is None:
        return 0, 0, 0
    vlans = sum(row.vlan_selected for row in plan.rows)
    prefixes = sum(row.prefix_selected for row in plan.rows)
    group = int(
        bool(vlans or prefixes)
        and plan.group is not None
        and plan.group.action == NET_CREATE
    )
    return group, vlans, prefixes
