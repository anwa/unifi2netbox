from dataclasses import asdict, dataclass
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from unifi2netbox.config import (
    ConfigError,
    NetBoxConfig,
    UniFiConfig,
    load_config,
    load_unifi_config,
    save_connections,
)
from unifi2netbox.connections import Checker, ConnectionRunner, check_unifi_connection
from unifi2netbox.matching import deduplicate_inventory
from unifi2netbox.netbox import ConnectionResult, ConnectionState, check_connection
from unifi2netbox.preview import build_change_preview, build_difference_preview
from unifi2netbox.refresh import refresh_snapshots
from unifi2netbox.snapshots import SnapshotStore
from unifi2netbox.write_plan import build_write_plan


@dataclass(frozen=True)
class InventoryPreviewRow:
    device_key: str
    action: str
    source_label: str
    target_label: str
    selected_fields: str
    executable: str


@dataclass(frozen=True)
class InventoryPreviewResult:
    status: str
    details: str
    netbox_devices: int = 0
    unifi_devices: int = 0
    matched_devices: int = 0
    unmatched_unifi: int = 0
    unmatched_netbox: int = 0
    conflicts: int = 0
    preview_rows: int = 0
    executable_operations: int = 0
    last_updated: str = ""
    detail_lines: tuple[str, ...] = ()
    rows: tuple[InventoryPreviewRow, ...] = ()


class InventoryJobSignals(QObject):
    finished = Signal(object)


class InventoryPreviewJob(QRunnable):
    def __init__(
        self,
        config_path: Path,
        netbox_config: NetBoxConfig,
        unifi_config: UniFiConfig,
    ) -> None:
        super().__init__()
        self.config_path = config_path
        self.netbox_config = netbox_config
        self.unifi_config = unifi_config
        self.signals = InventoryJobSignals()

    @Slot()
    def run(self) -> None:
        try:
            store = SnapshotStore(self.config_path.with_name("snapshots.sqlite3"))
            refresh = refresh_snapshots(self.netbox_config, self.unifi_config, store)
            diagnostics = (*refresh.netbox.diagnostics, *refresh.unifi.diagnostics)
            message = " ".join(item for item in diagnostics if item)
            if refresh.netbox.error or refresh.unifi.error:
                partial_detail = (
                    message or "Inventory refresh is partial; check source diagnostics."
                )
                self.signals.finished.emit(
                    InventoryPreviewResult(
                        status="Partial",
                        details=(
                            message
                            or "Inventory refresh completed with cached/failed sources."
                        ),
                        netbox_devices=(
                            len(refresh.netbox.snapshot.devices)
                            if refresh.netbox.snapshot
                            else 0
                        ),
                        unifi_devices=(
                            len(refresh.unifi.snapshot.devices)
                            if refresh.unifi.snapshot
                            else 0
                        ),
                        last_updated=refresh.netbox.last_updated
                        or refresh.unifi.last_updated,
                        detail_lines=(partial_detail,),
                    )
                )
                return

            netbox_snapshot = refresh.netbox.snapshot
            unifi_snapshot = refresh.unifi.snapshot
            if netbox_snapshot is None or unifi_snapshot is None:
                unavailable_detail = (
                    message or "Inventory snapshots are not available for both sources."
                )
                self.signals.finished.emit(
                    InventoryPreviewResult(
                        status="Unavailable",
                        details=(
                            message
                            or "Inventory snapshots are not available for both sources."
                        ),
                        last_updated=refresh.netbox.last_updated
                        or refresh.unifi.last_updated,
                        detail_lines=(unavailable_detail,),
                    )
                )
                return

            dedup = deduplicate_inventory(netbox_snapshot, unifi_snapshot)
            diff = build_difference_preview(netbox_snapshot, unifi_snapshot, dedup)
            change = build_change_preview(diff)
            plan = build_write_plan(diff, change)

            self.signals.finished.emit(
                InventoryPreviewResult(
                    status="Ready",
                    details=(
                        message or "Inventory preview and write-plan summary updated."
                    ),
                    netbox_devices=len(netbox_snapshot.devices),
                    unifi_devices=len(unifi_snapshot.devices),
                    matched_devices=len(dedup.pairs),
                    unmatched_unifi=len(dedup.unmatched_unifi),
                    unmatched_netbox=len(dedup.unmatched_netbox),
                    conflicts=len(dedup.conflicts),
                    preview_rows=len(diff.devices),
                    executable_operations=(
                        len(plan.operations) if plan.executable else 0
                    ),
                    last_updated=refresh.netbox.last_updated
                    or refresh.unifi.last_updated,
                    detail_lines=_preview_detail_lines(
                        dedup,
                        plan,
                        netbox_device_count=len(netbox_snapshot.devices),
                        unifi_device_count=len(unifi_snapshot.devices),
                    ),
                    rows=_preview_rows(diff, change, plan),
                )
            )
        except Exception:
            self.signals.finished.emit(
                InventoryPreviewResult(
                    status="Error",
                    details="Inventory preview refresh failed unexpectedly.",
                    detail_lines=(
                        "Inventory preview refresh failed before details were "
                        "available.",
                    ),
                )
            )


def _preview_detail_lines(
    dedup,
    plan,
    *,
    netbox_device_count: int,
    unifi_device_count: int,
) -> tuple[str, ...]:
    lines: list[str] = []

    if netbox_device_count == 0 and unifi_device_count > 0:
        lines.append(
            "NetBox inventory is empty; unmatched UniFi devices are expected "
            "until target records exist or create flow is executed."
        )

    if dedup.unmatched_unifi:
        lines.append(f"Unmatched UniFi observations: {len(dedup.unmatched_unifi)}")
    if dedup.unmatched_netbox:
        lines.append(f"Unmatched NetBox observations: {len(dedup.unmatched_netbox)}")

    for pair in dedup.pairs[:3]:
        lines.append(
            "Match "
            f"{pair.unifi_observation_id} -> {pair.netbox_observation_id} "
            f"({pair.reason})"
        )
    for conflict in dedup.conflicts[:3]:
        lines.append(
            f"Conflict {conflict.reason}: {', '.join(conflict.observation_ids[:3])}"
        )
    for operation in plan.operations[:3]:
        lines.append(
            "Plan "
            f"#{operation.sequence} {operation.operation_type} "
            f"{operation.device_key}"
        )

    if plan.issues:
        first_issue = plan.issues[0]
        lines.append(f"Plan issue ({first_issue.code}): {first_issue.message}")

    if not lines:
        lines.append("No preview detail entries are currently available.")
    return tuple(lines)


def _preview_rows(diff, change, plan) -> tuple[InventoryPreviewRow, ...]:
    change_by_key = {item.device_key: item for item in change.devices}
    executable_by_key = {item.device_key: item.executable for item in plan.devices}

    rows: list[InventoryPreviewRow] = []
    for device in diff.devices:
        selected_fields = ""
        change_item = change_by_key.get(device.device_key)
        if change_item is not None and change_item.selected_fields:
            selected_fields = ", ".join(change_item.selected_fields)

        rows.append(
            InventoryPreviewRow(
                device_key=device.device_key,
                action=str(device.action),
                source_label=device.source_label,
                target_label=device.target_label,
                selected_fields=selected_fields,
                executable=(
                    "Yes" if executable_by_key.get(device.device_key, False) else "No"
                ),
            )
        )
    return tuple(rows)


class InventoryPreviewRunner(QObject):
    finished = Signal(object)

    def __init__(self, pool: QThreadPool, config_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.pool = pool
        self.config_path = config_path
        self.job: InventoryPreviewJob | None = None

    @property
    def busy(self) -> bool:
        return self.job is not None

    def start(self, netbox: NetBoxConfig, unifi: UniFiConfig) -> bool:
        if self.busy:
            return False
        self.job = InventoryPreviewJob(self.config_path, netbox, unifi)
        self.job.signals.finished.connect(self._finished)
        self.pool.start(self.job)
        return True

    @Slot(object)
    def _finished(self, result: InventoryPreviewResult) -> None:
        self.job = None
        self.finished.emit(result)


def plain_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class ConnectionSettingsForm(QWidget):
    changed = Signal()

    def __init__(
        self,
        config: NetBoxConfig,
        pool: QThreadPool,
        checker: Checker = check_connection,
        parent=None,
        *,
        unifi: bool = False,
        sites: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__(parent)
        self.is_unifi = unifi
        self.state = ConnectionState.UNCONFIGURED
        self.runner = ConnectionRunner(pool, checker, self)
        self.runner.finished.connect(self.test_finished)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.url = QLineEdit(config.url)
        self.url.setPlaceholderText(
            "https://console.example.invalid"
            if unifi
            else "https://netbox.example.invalid"
        )
        self.token = QLineEdit(config.token)
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.show_token = QCheckBox("Show API key" if unifi else "Show token")
        self.show_token.toggled.connect(
            lambda shown: self.token.setEchoMode(
                QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
            )
        )
        self.verify_tls = QCheckBox("Verify TLS certificate")
        self.verify_tls.setChecked(config.verify_tls)
        self.ca_bundle = QLineEdit(config.ca_bundle)
        ca_row = QHBoxLayout()
        ca_row.addWidget(self.ca_bundle)
        self.browse = QToolButton()
        self.browse.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        self.browse.setToolTip("Choose CA bundle")
        self.browse.setAccessibleName("Choose CA bundle")
        self.browse.clicked.connect(self.choose_ca)
        ca_row.addWidget(self.browse)
        self.timeout = QDoubleSpinBox()
        self.timeout.setRange(1, 60)
        self.timeout.setDecimals(1)
        self.timeout.setSuffix(" s")
        self.timeout.setValue(config.timeout)
        form.addRow("Base URL", self.url)
        form.addRow("Local API key" if unifi else "API token", self.token)
        form.addRow("", self.show_token)
        self.site = QComboBox(self)
        self.site.setEditable(True)
        self.site.setVisible(unifi)
        self.update_sites(sites, config.site if isinstance(config, UniFiConfig) else "")
        if unifi:
            form.addRow("Site", self.site)
        form.addRow("", self.verify_tls)
        form.addRow("CA bundle", ca_row)
        form.addRow("Request timeout", self.timeout)
        layout.addLayout(form)
        self.warning = plain_label()
        layout.addWidget(self.warning)
        self.outcome = plain_label()
        layout.addWidget(self.outcome)
        layout.addStretch()
        self.url.textChanged.connect(self.update_warning)
        self.verify_tls.toggled.connect(self.update_warning)
        self.update_warning()

    def update_warning(self) -> None:
        if self.url.text().startswith("http://"):
            self.warning.setText("Plain HTTP: the token is transmitted unencrypted.")
        elif not self.verify_tls.isChecked():
            self.warning.setText("TLS certificate verification is disabled.")
        else:
            self.warning.clear()

    def choose_ca(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Choose CA Bundle")
        if filename:
            self.ca_bundle.setText(filename)

    def config_from_fields(self) -> NetBoxConfig:
        config = NetBoxConfig(
            url=self.url.text().strip().rstrip("/"),
            token=self.token.text().strip(),
            verify_tls=self.verify_tls.isChecked(),
            ca_bundle=self.ca_bundle.text().strip(),
            timeout=self.timeout.value(),
        )
        if self.is_unifi:
            return UniFiConfig(**asdict(config), site=self.site_value())
        return config

    def site_value(self) -> str:
        index = self.site.currentIndex()
        if index >= 0 and self.site.currentText() == self.site.itemText(index):
            return self.site.itemData(index)
        return self.site.currentText().strip()

    def update_sites(self, sites: tuple[tuple[str, str], ...], selected: str) -> None:
        self.site.clear()
        self.site.addItem("Automatic (single accessible site)", "")
        for identifier, name in sites:
            self.site.addItem(f"{name} ({identifier})", identifier)
        index = self.site.findData(selected)
        if index >= 0:
            self.site.setCurrentIndex(index)
        else:
            self.site.setEditText(selected)

    def test_connection(self) -> None:
        if self.runner.busy:
            return
        try:
            config = self.config_from_fields()
        except ConfigError as error:
            self.state = ConnectionState.ERROR
            self.outcome.setText(str(error))
            self.changed.emit()
            return
        self.state = ConnectionState.CHECKING
        self.outcome.setText("Checking...")
        self.runner.start(config)
        self.changed.emit()

    def test_finished(self, config: NetBoxConfig, result: ConnectionResult) -> None:
        self.state = result.state
        self.outcome.setText(f"{result.state}: {result.message}")
        if self.is_unifi:
            self.update_sites(result.sites, self.site_value())
        self.changed.emit()


class SettingsDialog(QDialog):
    def __init__(
        self,
        path: Path,
        config: NetBoxConfig,
        pool: QThreadPool,
        checker: Checker = check_connection,
        parent=None,
        *,
        unifi_config: UniFiConfig | None = None,
        unifi_checker: Checker = check_unifi_connection,
        sites: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.saved_config: NetBoxConfig | None = None
        self.saved_unifi_config: UniFiConfig | None = None
        self.close_pending = False
        self.setWindowTitle("Settings")
        self.resize(640, 520)
        self.setMinimumSize(500, 460)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.netbox = ConnectionSettingsForm(config, pool, checker)
        self.unifi = ConnectionSettingsForm(
            unifi_config if unifi_config is not None else load_unifi_config(path),
            pool,
            unifi_checker,
            unifi=True,
            sites=sites,
        )
        self.tabs.addTab(self.netbox, "NetBox")
        self.tabs.addTab(self.unifi, "UniFi Network")
        layout.addWidget(self.tabs)
        layout.addWidget(plain_label("Local token storage: plaintext"))
        layout.addWidget(plain_label(str(path)))
        self.outcome = plain_label()
        layout.addWidget(self.outcome)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.test_button = self.buttons.addButton(
            "Check Connections", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.test_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.test_button.clicked.connect(self.test_connections)
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.netbox.changed.connect(self.update_activity)
        self.unifi.changed.connect(self.update_activity)

    @property
    def busy(self) -> bool:
        return self.netbox.runner.busy or self.unifi.runner.busy

    def save(self) -> None:
        if self.busy:
            return
        try:
            netbox = self.netbox.config_from_fields()
            unifi = self.unifi.config_from_fields()
            if not isinstance(unifi, UniFiConfig):
                raise ConfigError("UniFi settings are invalid.")
            save_connections(self.path, netbox, unifi)
        except ConfigError as error:
            self.outcome.setText(str(error))
            return
        self.saved_config = netbox
        self.saved_unifi_config = unifi
        self.accept()

    def test_connections(self) -> None:
        if self.busy:
            return
        self.netbox.test_connection()
        self.unifi.test_connection()
        self.update_activity()

    def update_activity(self) -> None:
        self.tabs.setEnabled(not self.busy)
        self.buttons.setEnabled(not self.busy)
        self.outcome.setText(
            f"NetBox: {self.netbox.state}\nUniFi Network: {self.unifi.state}"
        )
        if self.close_pending and not self.busy:
            super().reject()

    def reject(self) -> None:
        if self.busy:
            self.close_pending = True
            self.outcome.setText("Finishing connection checks before closing...")
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.busy:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)


class ConnectionPanel(QWidget):
    idle = Signal()
    activity_changed = Signal()

    def __init__(
        self,
        config_path: Path,
        pool: QThreadPool,
        checker: Checker,
        *,
        unifi: bool = False,
    ) -> None:
        super().__init__()
        self.path = config_path
        self.pool = pool
        self.checker = checker
        self.is_unifi = unifi
        self.closing = False
        self.pending_check = False
        self.site_choices = ()
        self.runner = ConnectionRunner(pool, checker, self)
        self.runner.finished.connect(self.connection_finished)
        self.config_error = ""
        try:
            self.config = (
                load_unifi_config(config_path) if unifi else load_config(config_path)
            )
        except ConfigError as error:
            self.config = UniFiConfig() if unifi else NetBoxConfig()
            self.config_error = str(error)

        name = "UniFi Network" if unifi else "NetBox"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = plain_label(name)
        font = title.font()
        font.setPointSize(14)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        grid = QGridLayout()
        self.state = plain_label(ConnectionState.UNCONFIGURED)
        font = self.state.font()
        font.setBold(True)
        self.state.setFont(font)
        self.endpoint = plain_label()
        self.server_version = plain_label("Not checked")
        self.checked_at = plain_label("Not checked")
        self.selected_site = plain_label("Not selected")
        grid.addWidget(plain_label("Status"), 0, 0)
        grid.addWidget(self.state, 0, 1)
        grid.addWidget(plain_label("Endpoint"), 1, 0)
        grid.addWidget(self.endpoint, 1, 1)
        grid.addWidget(plain_label("Server version"), 2, 0)
        grid.addWidget(self.server_version, 2, 1)
        grid.addWidget(plain_label("Last check"), 3, 0)
        grid.addWidget(self.checked_at, 3, 1)
        if unifi:
            grid.addWidget(plain_label("Site"), 4, 0)
            grid.addWidget(self.selected_site, 4, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        self.details = plain_label(
            "Set a console URL and local API key."
            if unifi
            else "Set a NetBox URL and API token."
        )
        self.warning = plain_label()
        layout.addSpacing(12)
        layout.addWidget(self.details)
        layout.addWidget(self.warning)
        self.update_config_display()
        if self.config_error:
            self.show_result(ConnectionResult(ConnectionState.ERROR, self.config_error))
        elif self.config.configured:
            QTimer.singleShot(0, self.recheck)

    def update_config_display(self) -> None:
        self.endpoint.setText(self.config.url or "Not configured")
        self.warning.setText(self.config.security_warning)

    def apply_config(self, config: NetBoxConfig) -> None:
        self.config = config
        self.config_error = ""
        self.server_version.setText("Not checked")
        self.checked_at.setText("Not checked")
        self.selected_site.setText("Not selected")
        self.site_choices = ()
        self.update_config_display()
        self.recheck()

    def recheck(self) -> None:
        if self.closing:
            return
        if self.runner.busy:
            self.pending_check = True
            self.state.setText(ConnectionState.CHECKING)
            self.details.setText("Waiting for the previous check to finish...")
            return
        self.pending_check = False
        self.state.setText(ConnectionState.CHECKING)
        self.details.setText("Checking authenticated API access...")
        self.runner.start(self.config)
        self.activity_changed.emit()

    def connection_finished(
        self, config: NetBoxConfig, result: ConnectionResult
    ) -> None:
        self.activity_changed.emit()
        if self.closing:
            self.idle.emit()
            return
        if self.pending_check or config != self.config:
            self.recheck()
            return
        self.show_result(result)
        self.idle.emit()

    def show_result(self, result: ConnectionResult) -> None:
        self.state.setText(result.state)
        self.details.setText(result.message)
        self.server_version.setText(result.version or "Not available")
        self.selected_site.setText(result.site or "Not selected")
        self.site_choices = result.sites
        self.checked_at.setText(
            datetime.now().astimezone().isoformat(timespec="seconds")
        )

    def stop_for_close(self) -> None:
        self.closing = True
        self.pending_check = False
        if self.runner.busy:
            self.details.setText("Finishing the connection check before closing...")


class MainWindow(QMainWindow):
    def __init__(
        self,
        config_path: Path,
        pool: QThreadPool,
        checker: Checker = check_connection,
        *,
        open_first_run: bool = True,
        unifi_checker: Checker = check_unifi_connection,
    ) -> None:
        super().__init__()
        self.path = config_path
        self.pool = pool
        self.closing = False
        self.inventory_runner = InventoryPreviewRunner(pool, config_path, self)
        self.inventory_runner.finished.connect(self.inventory_preview_finished)
        self.netbox = ConnectionPanel(config_path, pool, checker)
        self.unifi = ConnectionPanel(config_path, pool, unifi_checker, unifi=True)
        self.setWindowTitle(f"unifi2netbox {version('unifi2netbox')}")
        self.resize(860, 720)
        self.setMinimumSize(580, 620)
        self.runner = self.netbox.runner
        self.state = self.netbox.state
        self.endpoint = self.netbox.endpoint
        self.server_version = self.netbox.server_version
        self.checked_at = self.netbox.checked_at
        self.details = self.netbox.details
        self.warning = self.netbox.warning
        self.check_action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload),
            "Check Connections",
            self,
        )
        self.check_action.setToolTip("Check NetBox and UniFi Network connections")
        self.check_action.triggered.connect(self.recheck)
        self.settings_action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView),
            "Settings",
            self,
        )
        self.settings_action.setToolTip("Edit NetBox and UniFi Network settings")
        self.settings_action.triggered.connect(self.open_settings)
        self.preview_action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogInfoView),
            "Refresh Inventory Preview",
            self,
        )
        self.preview_action.setToolTip(
            "Read both inventories and build the M4/M5 preview summary"
        )
        self.preview_action.triggered.connect(self.refresh_inventory_preview)
        toolbar = QToolBar("Connections")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        toolbar.addAction(self.check_action)
        toolbar.addAction(self.preview_action)
        toolbar.addAction(self.settings_action)
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self.settings_action)
        for panel in (self.netbox, self.unifi):
            panel.idle.connect(self.finish_close)
            panel.activity_changed.connect(self.update_check_action)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(24, 20, 24, 20)
        heading = plain_label("unifi2netbox")
        font = heading.font()
        font.setPointSize(22)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)
        layout.addSpacing(18)
        layout.addWidget(self.netbox)
        layout.addSpacing(24)
        layout.addWidget(self.unifi)
        layout.addSpacing(24)
        layout.addWidget(plain_label("Inventory Preview"))
        preview_grid = QGridLayout()
        self.preview_status = plain_label("Not refreshed")
        self.preview_counts = plain_label("NetBox: 0 | UniFi: 0")
        self.preview_matches = plain_label(
            "Matched: 0 | Unmatched UniFi: 0 | Unmatched NetBox: 0 | Conflicts: 0"
        )
        self.preview_plan = plain_label("Preview rows: 0 | Executable operations: 0")
        self.preview_checked_at = plain_label("Not refreshed")
        self.preview_detail_list = QListWidget(self)
        self.preview_detail_list.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
        )
        self.preview_detail_list.setMinimumHeight(96)
        self.preview_detail_list.currentItemChanged.connect(self.preview_detail_changed)
        self.preview_detail_text = plain_label("No preview details yet.")
        self.preview_rows: tuple[InventoryPreviewRow, ...] = ()
        self.preview_rows_dialog: QDialog | None = None
        self.copy_selected_button = QPushButton("Copy selected", self)
        self.copy_selected_button.clicked.connect(self.copy_selected_highlight)
        self.copy_all_button = QPushButton("Copy all", self)
        self.copy_all_button.clicked.connect(self.copy_all_highlights)
        self.show_rows_button = QPushButton("Show all rows", self)
        self.show_rows_button.clicked.connect(self.show_preview_rows_dialog)
        self.show_rows_button.setEnabled(False)
        copy_row = QHBoxLayout()
        copy_row.addWidget(self.show_rows_button)
        copy_row.addWidget(self.copy_selected_button)
        copy_row.addWidget(self.copy_all_button)
        copy_row.addStretch()
        preview_grid.addWidget(plain_label("Status"), 0, 0)
        preview_grid.addWidget(self.preview_status, 0, 1)
        preview_grid.addWidget(plain_label("Counts"), 1, 0)
        preview_grid.addWidget(self.preview_counts, 1, 1)
        preview_grid.addWidget(plain_label("Matching"), 2, 0)
        preview_grid.addWidget(self.preview_matches, 2, 1)
        preview_grid.addWidget(plain_label("Write plan"), 3, 0)
        preview_grid.addWidget(self.preview_plan, 3, 1)
        preview_grid.addWidget(plain_label("Last refresh"), 4, 0)
        preview_grid.addWidget(self.preview_checked_at, 4, 1)
        preview_grid.addWidget(plain_label("Highlights"), 5, 0)
        preview_grid.addWidget(self.preview_detail_list, 5, 1)
        preview_grid.addWidget(plain_label("Highlight detail"), 6, 0)
        preview_grid.addWidget(self.preview_detail_text, 6, 1)
        preview_grid.addWidget(plain_label("Clipboard"), 7, 0)
        preview_grid.addLayout(copy_row, 7, 1)
        preview_grid.setColumnStretch(1, 1)
        layout.addLayout(preview_grid)
        layout.addStretch()
        self.setCentralWidget(central)
        self.statusBar().showMessage(f"Configuration: {config_path}")
        if (
            open_first_run
            and not self.netbox.config.configured
            and not self.netbox.config_error
        ):
            QTimer.singleShot(0, self.open_settings)

    def open_settings(self) -> None:
        dialog = SettingsDialog(
            self.path,
            self.netbox.config,
            self.pool,
            self.netbox.checker,
            self,
            unifi_config=self.unifi.config,
            unifi_checker=self.unifi.checker,
            sites=self.unifi.site_choices,
        )
        if (
            dialog.exec() == QDialog.DialogCode.Accepted
            and dialog.saved_config is not None
            and dialog.saved_unifi_config is not None
        ):
            self.netbox.apply_config(dialog.saved_config)
            self.unifi.apply_config(dialog.saved_unifi_config)
        dialog.deleteLater()

    def apply_config(self, config: NetBoxConfig) -> None:
        self.netbox.apply_config(config)

    def recheck(self) -> None:
        self.netbox.recheck()
        self.unifi.recheck()

    def refresh_inventory_preview(self) -> None:
        if self.closing or self.inventory_runner.busy:
            return
        if not self.netbox.config.configured or not self.unifi.config.configured:
            self.preview_status.setText("Unconfigured")
            self.preview_plan.setText(
                "Configure NetBox and UniFi Network before inventory preview refresh."
            )
            return
        self.preview_status.setText("Refreshing...")
        self.preview_plan.setText("Collecting inventory snapshots in background...")
        self.inventory_runner.start(self.netbox.config, self.unifi.config)
        self.update_check_action()

    def inventory_preview_finished(self, result: InventoryPreviewResult) -> None:
        self.preview_status.setText(result.status)
        self.preview_counts.setText(
            f"NetBox: {result.netbox_devices} | UniFi: {result.unifi_devices}"
        )
        self.preview_matches.setText(
            "Matched: "
            f"{result.matched_devices} | "
            f"Unmatched UniFi: {result.unmatched_unifi} | "
            f"Unmatched NetBox: {result.unmatched_netbox} | "
            f"Conflicts: {result.conflicts}"
        )
        self.preview_plan.setText(
            f"Preview rows: {result.preview_rows} | "
            f"Executable operations: {result.executable_operations}"
            f". {result.details}"
        )
        self.preview_checked_at.setText(result.last_updated or "Not available")
        self.preview_rows = result.rows
        self.show_rows_button.setEnabled(bool(self.preview_rows))
        self.preview_detail_list.clear()
        for line in result.detail_lines:
            self.preview_detail_list.addItem(QListWidgetItem(line))
        if result.detail_lines:
            self.preview_detail_list.setCurrentRow(0)
            self.preview_detail_text.setText(result.detail_lines[0])
        else:
            self.preview_detail_text.setText("No preview details yet.")
        self.update_check_action()

    def preview_detail_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        del previous
        if current is None:
            self.preview_detail_text.setText("No preview details yet.")
            return
        self.preview_detail_text.setText(current.text())

    def copy_selected_highlight(self) -> None:
        current = self.preview_detail_list.currentItem()
        text = current.text() if current is not None else ""
        if not text:
            self.statusBar().showMessage("No highlight selected to copy.")
            return
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("Copied selected highlight.")

    def copy_all_highlights(self) -> None:
        lines = [
            self.preview_detail_list.item(index).text()
            for index in range(self.preview_detail_list.count())
        ]
        if not lines:
            self.statusBar().showMessage("No highlights available to copy.")
            return
        QApplication.clipboard().setText("\n".join(lines))
        self.statusBar().showMessage(f"Copied {len(lines)} highlight line(s).")

    def show_preview_rows_dialog(self) -> None:
        if not self.preview_rows:
            self.statusBar().showMessage("No preview rows available.")
            return

        if (
            self.preview_rows_dialog is not None
            and self.preview_rows_dialog.isVisible()
        ):
            self.preview_rows_dialog.raise_()
            self.preview_rows_dialog.activateWindow()
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Inventory Preview Rows")
        dialog.resize(980, 520)
        layout = QVBoxLayout(dialog)

        filter_row = QHBoxLayout()
        filter_row.addWidget(plain_label("Action filter"))
        action_filter = QComboBox(dialog)
        action_filter.setObjectName("preview_rows_action_filter")
        action_filter.addItem("All actions", "")
        action_filter.addItem("Create", "create")
        action_filter.addItem("Update", "update")
        action_filter.addItem("Target only", "target_only")
        filter_row.addWidget(action_filter)
        executable_only = QCheckBox("Executable only", dialog)
        executable_only.setObjectName("preview_rows_executable_filter")
        filter_row.addWidget(executable_only)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        table = QTableWidget(dialog)
        table.setObjectName("preview_rows_table")
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels(
            [
                "Device key",
                "Action",
                "Source",
                "Target",
                "Selected fields",
                "Executable",
            ]
        )

        def populate_table() -> None:
            action_value = str(action_filter.currentData() or "")
            executable_enabled = executable_only.isChecked()
            visible_rows = [
                row
                for row in self.preview_rows
                if (not action_value or row.action == action_value)
                and (not executable_enabled or row.executable == "Yes")
            ]

            table.setRowCount(len(visible_rows))
            for row_index, row in enumerate(visible_rows):
                values = (
                    row.device_key,
                    row.action,
                    row.source_label,
                    row.target_label,
                    row.selected_fields,
                    row.executable,
                )
                for column_index, value in enumerate(values):
                    table.setItem(row_index, column_index, QTableWidgetItem(value))
            table.resizeColumnsToContents()

        action_filter.currentIndexChanged.connect(lambda _index: populate_table())
        executable_only.toggled.connect(lambda _checked: populate_table())
        populate_table()

        table.setAlternatingRowColors(True)
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        self.preview_rows_dialog = dialog
        dialog.setModal(False)
        dialog.show()

    def update_check_action(self) -> None:
        self.settings_action.setEnabled(not self.closing)
        self.check_action.setEnabled(
            not self.closing and not (self.netbox.runner.busy or self.unifi.runner.busy)
        )
        self.preview_action.setEnabled(
            not self.closing
            and not self.inventory_runner.busy
            and not (self.netbox.runner.busy or self.unifi.runner.busy)
        )

    def finish_close(self) -> None:
        if self.closing and not (
            self.netbox.runner.busy
            or self.unifi.runner.busy
            or self.inventory_runner.busy
        ):
            self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.closing = True
        self.netbox.stop_for_close()
        self.unifi.stop_for_close()
        self.update_check_action()
        if (
            self.netbox.runner.busy
            or self.unifi.runner.busy
            or self.inventory_runner.busy
        ):
            event.ignore()
            return
        super().closeEvent(event)
