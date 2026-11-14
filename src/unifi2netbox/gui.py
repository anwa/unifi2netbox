import json
from dataclasses import asdict
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
    BehaviorConfig,
    ConfigError,
    NetBoxConfig,
    UniFiConfig,
    load_behavior_config,
    load_config,
    load_unifi_config,
    save_connections,
)
from unifi2netbox.connections import Checker, ConnectionRunner, check_unifi_connection
from unifi2netbox.netbox import ConnectionResult, ConnectionState, check_connection
from unifi2netbox.pipeline import (
    InventoryPreviewResult,
    InventoryPreviewRow,
    WriteExecutionReport,
    build_inventory_preview,
    run_write_execution,
)
from unifi2netbox.preview import DifferencePreview
from unifi2netbox.write_plan import (
    OperationType,
    WritePlan,
    WritePlanSummary,
)


class InventoryJobSignals(QObject):
    finished = Signal(object)


class InventoryPreviewJob(QRunnable):
    def __init__(
        self,
        config_path: Path,
        netbox_config: NetBoxConfig,
        unifi_config: UniFiConfig,
        include_all_netbox_delete_candidates: bool,
        netbox_site_name: str = "",
    ) -> None:
        super().__init__()
        self.config_path = config_path
        self.netbox_config = netbox_config
        self.unifi_config = unifi_config
        self.include_all_netbox_delete_candidates = include_all_netbox_delete_candidates
        self.netbox_site_name = netbox_site_name
        self.signals = InventoryJobSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = build_inventory_preview(
                self.config_path,
                self.netbox_config,
                self.unifi_config,
                include_all_netbox_delete_candidates=(
                    self.include_all_netbox_delete_candidates
                ),
                netbox_site_name=self.netbox_site_name,
            )
        except Exception:
            result = InventoryPreviewResult(
                status="Error",
                details="Inventory preview refresh failed unexpectedly.",
                detail_lines=(
                    "Inventory preview refresh failed before details were available.",
                ),
            )
        self.signals.finished.emit(result)


class WriteExecutionSignals(QObject):
    finished = Signal(object)


class WriteExecutionJob(QRunnable):
    def __init__(
        self,
        netbox_config: NetBoxConfig,
        behavior: BehaviorConfig,
        difference_preview: DifferencePreview,
        write_plan: WritePlan,
        role_overrides: dict[str, str],
        site_overrides: dict[str, str],
        status_overrides: dict[str, str],
        device_type_overrides: dict[str, str],
        *,
        dry_run: bool,
    ) -> None:
        super().__init__()
        self.netbox_config = netbox_config
        self.behavior = behavior
        self.difference_preview = difference_preview
        self.write_plan = write_plan
        self.role_overrides = role_overrides
        self.site_overrides = site_overrides
        self.status_overrides = status_overrides
        self.device_type_overrides = device_type_overrides
        self.dry_run = dry_run
        self.signals = WriteExecutionSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = run_write_execution(
                self.netbox_config,
                self.behavior,
                self.difference_preview,
                self.write_plan,
                role_overrides=self.role_overrides,
                site_overrides=self.site_overrides,
                status_overrides=self.status_overrides,
                device_type_overrides=self.device_type_overrides,
                dry_run=self.dry_run,
            )
        except Exception as error:
            result = WriteExecutionReport(
                status="Error",
                details="Write execution failed unexpectedly.",
                detail_lines=(f"Write execution error: {error}",),
            )
        self.signals.finished.emit(result)


class WriteExecutionRunner(QObject):
    finished = Signal(object)

    def __init__(self, pool: QThreadPool, parent=None) -> None:
        super().__init__(parent)
        self.pool = pool
        self.job: WriteExecutionJob | None = None

    @property
    def busy(self) -> bool:
        return self.job is not None

    def start(
        self,
        netbox_config: NetBoxConfig,
        behavior: BehaviorConfig,
        difference_preview: DifferencePreview,
        write_plan: WritePlan,
        role_overrides: dict[str, str],
        site_overrides: dict[str, str],
        status_overrides: dict[str, str],
        device_type_overrides: dict[str, str],
        *,
        dry_run: bool,
    ) -> bool:
        if self.busy:
            return False
        self.job = WriteExecutionJob(
            netbox_config,
            behavior,
            difference_preview,
            write_plan,
            role_overrides,
            site_overrides,
            status_overrides,
            device_type_overrides,
            dry_run=dry_run,
        )
        self.job.signals.finished.connect(self._finished)
        self.pool.start(self.job)
        return True

    @Slot(object)
    def _finished(self, result: WriteExecutionReport) -> None:
        self.job = None
        self.finished.emit(result)


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

    def start(
        self,
        netbox: NetBoxConfig,
        unifi: UniFiConfig,
        *,
        include_all_netbox_delete_candidates: bool,
        netbox_site_name: str = "",
    ) -> bool:
        if self.busy:
            return False
        self.job = InventoryPreviewJob(
            self.config_path,
            netbox,
            unifi,
            include_all_netbox_delete_candidates,
            netbox_site_name,
        )
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
        self.saved_behavior_config: BehaviorConfig | None = None
        self.close_pending = False
        try:
            self.behavior = load_behavior_config(path)
        except ConfigError:
            self.behavior = BehaviorConfig()
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
        self.include_all_netbox_delete_candidates = QCheckBox(
            "Include all NetBox devices for delete proposals"
        )
        self.include_all_netbox_delete_candidates.setChecked(
            self.behavior.include_all_netbox_delete_candidates
        )
        layout.addWidget(self.include_all_netbox_delete_candidates)
        behavior_form = QFormLayout()
        self.default_device_role_name = QLineEdit(
            self.behavior.default_device_role_name
        )
        self.default_device_role_name.setPlaceholderText(
            "Optional now; required for create execution"
        )
        behavior_form.addRow(
            "Default NetBox device role (create)", self.default_device_role_name
        )
        self.netbox_site_name = QLineEdit(self.behavior.netbox_site_name)
        self.netbox_site_name.setPlaceholderText(
            "Optional; replaces the UniFi site name for matching and writes"
        )
        behavior_form.addRow("NetBox site for UniFi devices", self.netbox_site_name)
        layout.addLayout(behavior_form)
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
            behavior = BehaviorConfig(
                include_all_netbox_delete_candidates=(
                    self.include_all_netbox_delete_candidates.isChecked()
                ),
                default_device_role_name=self.default_device_role_name.text().strip(),
                netbox_site_name=self.netbox_site_name.text().strip(),
            )
            save_connections(self.path, netbox, unifi, behavior)
        except ConfigError as error:
            self.outcome.setText(str(error))
            return
        self.saved_config = netbox
        self.saved_unifi_config = unifi
        self.saved_behavior_config = behavior
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
        self.write_runner = WriteExecutionRunner(pool, self)
        self.write_runner.finished.connect(self.write_execution_finished)
        self.current_difference_preview: DifferencePreview | None = None
        self.current_write_plan: WritePlan | None = None
        try:
            self.behavior = load_behavior_config(config_path)
        except ConfigError:
            self.behavior = BehaviorConfig()
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
        self.unifi_snapshot_captured_at = ""
        self.unifi_snapshot_scope = ""
        self.unifi_snapshot_version = ""
        self.unifi_api_feedback: tuple[dict[str, object], ...] = ()
        self.unifi_raw_devices: tuple[dict[str, object], ...] = ()
        self.netbox_device_types: tuple[tuple[str, str, str], ...] = ()
        self.netbox_device_statuses: tuple[str, ...] = ()
        self.netbox_device_roles: tuple[str, ...] = ()
        self.netbox_sites: tuple[str, ...] = ()
        self.create_device_type_by_device_key: dict[str, str] = {}
        self.create_status_by_device_key: dict[str, str] = {}
        self.create_role_by_device_key: dict[str, str] = {}
        self.create_site_by_device_key: dict[str, str] = {}
        self.preview_rows_dialog: QDialog | None = None
        self.copy_selected_button = QPushButton("Copy selected", self)
        self.copy_selected_button.clicked.connect(self.copy_selected_highlight)
        self.copy_all_button = QPushButton("Copy all", self)
        self.copy_all_button.clicked.connect(self.copy_all_highlights)
        self.show_rows_button = QPushButton("Show all rows", self)
        self.show_rows_button.clicked.connect(self.show_preview_rows_dialog)
        self.show_rows_button.setEnabled(False)
        self.export_unifi_dump_button = QPushButton("Export UniFi API dump", self)
        self.export_unifi_dump_button.clicked.connect(self.export_unifi_api_dump)
        self.export_unifi_dump_button.setEnabled(False)
        self.dry_run_only = QCheckBox("Dry run only", self)
        self.execute_plan_button = QPushButton("Execute write plan", self)
        self.execute_plan_button.clicked.connect(self.execute_write_plan_from_preview)
        self.execute_plan_button.setEnabled(False)
        copy_row = QHBoxLayout()
        copy_row.addWidget(self.show_rows_button)
        copy_row.addWidget(self.export_unifi_dump_button)
        copy_row.addWidget(self.dry_run_only)
        copy_row.addWidget(self.execute_plan_button)
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
            if dialog.saved_behavior_config is not None:
                self.behavior = dialog.saved_behavior_config
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
        self.inventory_runner.start(
            self.netbox.config,
            self.unifi.config,
            include_all_netbox_delete_candidates=(
                self.behavior.include_all_netbox_delete_candidates
            ),
            netbox_site_name=self.behavior.netbox_site_name,
        )
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
        self.unifi_snapshot_captured_at = result.unifi_captured_at
        self.unifi_snapshot_scope = result.unifi_scope
        self.unifi_snapshot_version = result.unifi_version
        self.unifi_api_feedback = result.unifi_api_feedback
        self.unifi_raw_devices = result.unifi_raw_devices
        self.netbox_device_types = result.netbox_device_types
        self.netbox_device_statuses = result.netbox_device_statuses
        self.netbox_device_roles = result.netbox_device_roles
        self.netbox_sites = result.netbox_sites
        self.create_device_type_by_device_key = {}
        self.create_status_by_device_key = {}
        self.create_role_by_device_key = {}
        self.create_site_by_device_key = {}
        source_site_by_key: dict[str, str] = {}
        source_type_by_key: dict[str, tuple[str, str]] = {}
        if result.difference_preview is not None:
            for device in result.difference_preview.devices:
                site_value = next(
                    (
                        field.source_value.strip()
                        for field in device.fields
                        if field.name == "site" and field.source_value.strip()
                    ),
                    "",
                )
                if site_value:
                    source_site_by_key[device.device_key] = site_value
                manufacturer = next(
                    (
                        field.source_value.strip()
                        for field in device.fields
                        if field.name == "manufacturer" and field.source_value.strip()
                    ),
                    "",
                )
                model = next(
                    (
                        field.source_value.strip()
                        for field in device.fields
                        if field.name == "model" and field.source_value.strip()
                    ),
                    "",
                )
                if manufacturer and model:
                    source_type_by_key[device.device_key] = (manufacturer, model)

        type_ids_by_name: dict[tuple[str, str], list[str]] = {}
        for type_id, manufacturer, model in self.netbox_device_types:
            key = (manufacturer.strip().lower(), model.strip().lower())
            type_ids_by_name.setdefault(key, []).append(type_id)

        default_role = self.behavior.default_device_role_name.strip()
        for row in self.preview_rows:
            if row.action != "create":
                continue
            source_type = source_type_by_key.get(row.device_key)
            if source_type is not None:
                type_key = (source_type[0].lower(), source_type[1].lower())
                type_ids = type_ids_by_name.get(type_key, [])
                if len(type_ids) == 1:
                    self.create_device_type_by_device_key[row.device_key] = type_ids[0]
            if (
                row.device_key not in self.create_device_type_by_device_key
                and row.suggested_device_type_id
            ):
                # Unambiguous part-number/alias suggestion; editable before writes.
                self.create_device_type_by_device_key[row.device_key] = (
                    row.suggested_device_type_id
                )
            if "active" in self.netbox_device_statuses:
                self.create_status_by_device_key[row.device_key] = "active"
            elif self.netbox_device_statuses:
                self.create_status_by_device_key[row.device_key] = (
                    self.netbox_device_statuses[0]
                )
            default_site = source_site_by_key.get(row.device_key, "")
            if default_site and default_site in self.netbox_sites:
                self.create_site_by_device_key[row.device_key] = default_site
            elif self.netbox_sites:
                self.create_site_by_device_key[row.device_key] = self.netbox_sites[0]
            if default_role and default_role in self.netbox_device_roles:
                self.create_role_by_device_key[row.device_key] = default_role
            elif self.netbox_device_roles:
                self.create_role_by_device_key[row.device_key] = (
                    self.netbox_device_roles[0]
                )
        self.current_difference_preview = result.difference_preview
        self.current_write_plan = result.write_plan
        self.show_rows_button.setEnabled(bool(self.preview_rows))
        self.export_unifi_dump_button.setEnabled(bool(self.unifi_api_feedback))
        self.execute_plan_button.setEnabled(
            bool(self.current_write_plan and self.current_write_plan.executable)
        )
        self.preview_detail_list.clear()
        for line in result.detail_lines:
            self.preview_detail_list.addItem(QListWidgetItem(line))
        if result.detail_lines:
            self.preview_detail_list.setCurrentRow(0)
            self.preview_detail_text.setText(result.detail_lines[0])
        else:
            self.preview_detail_text.setText("No preview details yet.")
        self.update_check_action()

    def execute_write_plan_from_preview(self) -> None:
        if self.write_runner.busy or self.closing:
            return
        if self.current_difference_preview is None or self.current_write_plan is None:
            self.statusBar().showMessage("Refresh inventory preview before apply.")
            return
        if not self.current_write_plan.executable:
            self.statusBar().showMessage(
                "Current write plan is not executable. Resolve blockers first."
            )
            return

        confirm = QDialog(self)
        confirm.setWindowTitle("Confirm write execution")
        layout = QVBoxLayout(confirm)
        layout.addWidget(
            plain_label(self.current_write_plan.summary.confirmation_message)
        )
        layout.addWidget(
            plain_label(
                "Writes target NetBox only. UniFi remains read-only. "
                "Review preview rows before confirming."
            )
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            confirm,
        )
        buttons.accepted.connect(confirm.accept)
        buttons.rejected.connect(confirm.reject)
        layout.addWidget(buttons)

        if confirm.exec() != QDialog.DialogCode.Accepted:
            return

        self.preview_status.setText("Applying...")
        self.preview_plan.setText("Executing write plan in background...")
        self.write_runner.start(
            self.netbox.config,
            self.behavior,
            self.current_difference_preview,
            self.current_write_plan,
            self._create_role_overrides(self.current_write_plan),
            self._create_site_overrides(self.current_write_plan),
            self._create_status_overrides(self.current_write_plan),
            self._create_device_type_overrides(self.current_write_plan),
            dry_run=self.dry_run_only.isChecked(),
        )
        self.update_check_action()

    def execute_selected_preview_row(self, device_key: str) -> None:
        if self.write_runner.busy or self.closing:
            return
        if self.current_difference_preview is None or self.current_write_plan is None:
            self.statusBar().showMessage(
                "Refresh inventory preview before row execution."
            )
            return

        single_plan = _single_operation_plan(self.current_write_plan, device_key)
        if single_plan is None:
            self.statusBar().showMessage(
                "Selected row has no executable write operation."
            )
            return

        confirm = QDialog(self)
        confirm.setWindowTitle("Confirm row execution")
        layout = QVBoxLayout(confirm)
        layout.addWidget(plain_label(single_plan.summary.confirmation_message))
        layout.addWidget(
            plain_label("This runs only the selected row as a single write operation.")
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            confirm,
        )
        buttons.accepted.connect(confirm.accept)
        buttons.rejected.connect(confirm.reject)
        layout.addWidget(buttons)

        if confirm.exec() != QDialog.DialogCode.Accepted:
            return

        self.preview_status.setText("Applying row...")
        self.preview_plan.setText("Executing selected row in background...")
        self.write_runner.start(
            self.netbox.config,
            self.behavior,
            self.current_difference_preview,
            single_plan,
            self._create_role_overrides(single_plan),
            self._create_site_overrides(single_plan),
            self._create_status_overrides(single_plan),
            self._create_device_type_overrides(single_plan),
            dry_run=self.dry_run_only.isChecked(),
        )
        self.update_check_action()

    def write_execution_finished(self, result: WriteExecutionReport) -> None:
        self.preview_status.setText(result.status)
        self.preview_plan.setText(result.details)
        self.preview_detail_list.clear()
        for line in result.detail_lines:
            self.preview_detail_list.addItem(QListWidgetItem(line))
        if result.detail_lines:
            self.preview_detail_list.setCurrentRow(0)
            self.preview_detail_text.setText(result.detail_lines[0])
        else:
            self.preview_detail_text.setText("No preview details yet.")
        self.statusBar().showMessage(result.details)
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
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setColumnCount(12)
        table.setHorizontalHeaderLabels(
            [
                "Device key",
                "Action",
                "Source",
                "Target",
                "Selected fields",
                "Executable",
                "Device status",
                "Device site",
                "Device role",
                "Device type",
                "Reason",
                "Suggested Device Types",
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
                table.setItem(row_index, 0, QTableWidgetItem(row.device_key))
                table.setItem(row_index, 1, QTableWidgetItem(row.action))
                table.setItem(row_index, 2, QTableWidgetItem(row.source_label))
                table.setItem(row_index, 3, QTableWidgetItem(row.target_label))
                table.setItem(row_index, 4, QTableWidgetItem(row.selected_fields))
                table.setItem(row_index, 5, QTableWidgetItem(row.executable))
                table.setItem(row_index, 10, QTableWidgetItem(row.blocked_reason))
                table.setItem(
                    row_index, 11, QTableWidgetItem(row.suggested_device_types)
                )

                if row.action == "create":
                    status_combo = QComboBox(table)
                    if self.netbox_device_statuses:
                        for status_value in self.netbox_device_statuses:
                            status_combo.addItem(status_value)
                        selected_status = self.create_status_by_device_key.get(
                            row.device_key, self.netbox_device_statuses[0]
                        )
                        if selected_status not in self.netbox_device_statuses:
                            selected_status = self.netbox_device_statuses[0]
                        self.create_status_by_device_key[row.device_key] = (
                            selected_status
                        )
                        status_combo.setCurrentText(selected_status)
                        status_combo.currentTextChanged.connect(
                            lambda status, key=row.device_key: self._set_create_status(
                                key, status
                            )
                        )
                    else:
                        status_combo.addItem("No statuses available")
                        status_combo.setEnabled(False)
                    table.setCellWidget(row_index, 6, status_combo)

                    site_combo = QComboBox(table)
                    if self.netbox_sites:
                        for site_name in self.netbox_sites:
                            site_combo.addItem(site_name)
                        selected_site = self.create_site_by_device_key.get(
                            row.device_key, self.netbox_sites[0]
                        )
                        if selected_site not in self.netbox_sites:
                            selected_site = self.netbox_sites[0]
                        self.create_site_by_device_key[row.device_key] = selected_site
                        site_combo.setCurrentText(selected_site)
                        site_combo.currentTextChanged.connect(
                            lambda site, key=row.device_key: self._set_create_site(
                                key, site
                            )
                        )
                    else:
                        site_combo.addItem("No sites available")
                        site_combo.setEnabled(False)
                    table.setCellWidget(row_index, 7, site_combo)

                    role_combo = QComboBox(table)
                    if self.netbox_device_roles:
                        for role_name in self.netbox_device_roles:
                            role_combo.addItem(role_name)
                        selected_role = self.create_role_by_device_key.get(
                            row.device_key, self.netbox_device_roles[0]
                        )
                        if selected_role not in self.netbox_device_roles:
                            selected_role = self.netbox_device_roles[0]
                        self.create_role_by_device_key[row.device_key] = selected_role
                        role_combo.setCurrentText(selected_role)
                        role_combo.currentTextChanged.connect(
                            lambda role, key=row.device_key: self._set_create_role(
                                key, role
                            )
                        )
                    else:
                        role_combo.addItem("No roles available")
                        role_combo.setEnabled(False)
                    table.setCellWidget(row_index, 8, role_combo)

                    type_combo = QComboBox(table)
                    if self.netbox_device_types:
                        type_combo.addItem("Auto-resolve from source", "")
                        for type_id, manufacturer, model in self.netbox_device_types:
                            type_combo.addItem(
                                f"{manufacturer} {model} [id:{type_id}]", type_id
                            )
                        selected_type_id = self.create_device_type_by_device_key.get(
                            row.device_key, ""
                        )
                        selected_index = type_combo.findData(selected_type_id)
                        if selected_index < 0:
                            selected_index = 0
                            self.create_device_type_by_device_key.pop(
                                row.device_key, None
                            )
                        type_combo.setCurrentIndex(selected_index)

                        def _on_type_changed(
                            _index: int,
                            *,
                            combo: QComboBox = type_combo,
                            key: str = row.device_key,
                        ) -> None:
                            self._set_create_device_type(
                                key,
                                str(combo.currentData() or ""),
                            )

                        type_combo.currentIndexChanged.connect(_on_type_changed)
                    else:
                        type_combo.addItem("No device types available", "")
                        type_combo.setEnabled(False)
                    table.setCellWidget(row_index, 9, type_combo)
                else:
                    table.setItem(row_index, 6, QTableWidgetItem(""))
                    table.setItem(row_index, 7, QTableWidgetItem(""))
                    table.setItem(row_index, 8, QTableWidgetItem(""))
                    table.setItem(row_index, 9, QTableWidgetItem(""))
            table.resizeColumnsToContents()
            if visible_rows and table.currentRow() < 0:
                table.setCurrentCell(0, 0)

        action_filter.currentIndexChanged.connect(lambda _index: populate_table())
        executable_only.toggled.connect(lambda _checked: populate_table())
        populate_table()

        table.setAlternatingRowColors(True)
        layout.addWidget(table)
        execute_selected = QPushButton("Execute selected row", dialog)
        execute_selected.setObjectName("preview_rows_execute_selected")
        export_selected_dump = QPushButton("Export selected UniFi row dump", dialog)
        export_selected_dump.setObjectName("preview_rows_export_selected_dump")
        export_full_dump = QPushButton("Export full UniFi API dump", dialog)
        export_full_dump.setObjectName("preview_rows_export_full_dump")

        def run_selected_row() -> None:
            row_index = table.currentRow()
            if row_index < 0:
                self.statusBar().showMessage("No preview row selected.")
                return
            device_item = table.item(row_index, 0)
            executable_item = table.item(row_index, 5)
            if device_item is None or executable_item is None:
                self.statusBar().showMessage("Selected preview row is invalid.")
                return
            if executable_item.text() != "Yes":
                reason_item = table.item(row_index, 10)
                reason = (
                    reason_item.text()
                    if reason_item is not None and reason_item.text().strip()
                    else "Selected preview row is not executable."
                )
                self.statusBar().showMessage(reason)
                return
            self.execute_selected_preview_row(device_item.text())

        execute_selected.clicked.connect(run_selected_row)
        layout.addWidget(execute_selected)

        def export_selected_row_dump() -> None:
            row_index = table.currentRow()
            if row_index < 0:
                self.statusBar().showMessage("No preview row selected.")
                return
            device_item = table.item(row_index, 0)
            if device_item is None or not device_item.text().strip():
                self.statusBar().showMessage("Selected preview row is invalid.")
                return
            self.export_unifi_row_dump(device_item.text().strip())

        export_selected_dump.clicked.connect(export_selected_row_dump)
        export_full_dump.clicked.connect(self.export_unifi_api_dump)
        layout.addWidget(export_selected_dump)
        layout.addWidget(export_full_dump)
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
            and not self.write_runner.busy
            and not (self.netbox.runner.busy or self.unifi.runner.busy)
        )
        self.execute_plan_button.setEnabled(
            not self.closing
            and not self.inventory_runner.busy
            and not self.write_runner.busy
            and bool(self.current_write_plan and self.current_write_plan.executable)
        )

    def finish_close(self) -> None:
        if self.closing and not (
            self.netbox.runner.busy
            or self.unifi.runner.busy
            or self.inventory_runner.busy
            or self.write_runner.busy
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
            or self.write_runner.busy
        ):
            event.ignore()
            return
        super().closeEvent(event)

    def _create_role_overrides(self, write_plan: WritePlan) -> dict[str, str]:
        create_keys = {
            operation.device_key
            for operation in write_plan.operations
            if operation.operation_type == OperationType.CREATE_DEVICE
        }
        return {
            key: role
            for key, role in self.create_role_by_device_key.items()
            if key in create_keys and role.strip()
        }

    def _create_site_overrides(self, write_plan: WritePlan) -> dict[str, str]:
        create_keys = {
            operation.device_key
            for operation in write_plan.operations
            if operation.operation_type == OperationType.CREATE_DEVICE
        }
        return {
            key: site
            for key, site in self.create_site_by_device_key.items()
            if key in create_keys and site.strip()
        }

    def _create_status_overrides(self, write_plan: WritePlan) -> dict[str, str]:
        create_keys = {
            operation.device_key
            for operation in write_plan.operations
            if operation.operation_type == OperationType.CREATE_DEVICE
        }
        return {
            key: status
            for key, status in self.create_status_by_device_key.items()
            if key in create_keys and status.strip()
        }

    def _create_device_type_overrides(self, write_plan: WritePlan) -> dict[str, str]:
        create_keys = {
            operation.device_key
            for operation in write_plan.operations
            if operation.operation_type == OperationType.CREATE_DEVICE
        }
        return {
            key: device_type_id
            for key, device_type_id in self.create_device_type_by_device_key.items()
            if key in create_keys and device_type_id.strip()
        }

    def _set_create_role(self, device_key: str, role_name: str) -> None:
        self.create_role_by_device_key[device_key] = role_name.strip()

    def _set_create_site(self, device_key: str, site_name: str) -> None:
        self.create_site_by_device_key[device_key] = site_name.strip()

    def _set_create_status(self, device_key: str, status_value: str) -> None:
        self.create_status_by_device_key[device_key] = status_value.strip()

    def _set_create_device_type(self, device_key: str, device_type_id: str) -> None:
        value = device_type_id.strip()
        if value:
            self.create_device_type_by_device_key[device_key] = value
        else:
            self.create_device_type_by_device_key.pop(device_key, None)

    def export_unifi_api_dump(self) -> None:
        if not self.unifi_api_feedback:
            self.statusBar().showMessage("No UniFi API feedback available to export.")
            return
        default_name = f"unifi-api-dump-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save UniFi API dump",
            default_name,
            "JSON files (*.json)",
        )
        if not filename:
            return
        payload = {
            "schema_version": 1,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "snapshot": {
                "captured_at": self.unifi_snapshot_captured_at,
                "scope": self.unifi_snapshot_scope,
                "source_version": self.unifi_snapshot_version,
            },
            "api_feedback": list(self.unifi_api_feedback),
            "raw_devices": list(self.unifi_raw_devices),
        }
        self._write_json_dump(Path(filename), payload)

    def export_unifi_row_dump(self, device_key: str) -> None:
        source_id = _unifi_source_id_from_device_key(device_key)
        if not source_id:
            self.statusBar().showMessage(
                "Selected row has no UniFi source device to export."
            )
            return
        raw_row = _find_unifi_raw_device(self.unifi_raw_devices, source_id)
        if raw_row is None:
            self.statusBar().showMessage("No UniFi raw payload found for selected row.")
            return
        safe_id = "".join(ch for ch in source_id if ch.isalnum() or ch in "-_")
        default_name = (
            f"unifi-row-dump-{safe_id or 'device'}-"
            f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        )
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save UniFi row dump",
            default_name,
            "JSON files (*.json)",
        )
        if not filename:
            return
        payload = {
            "schema_version": 1,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "device_key": device_key,
            "unifi_source_id": source_id,
            "raw_device": raw_row,
        }
        self._write_json_dump(Path(filename), payload)

    def _write_json_dump(self, path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.statusBar().showMessage(f"Saved dump: {path}")


def _single_operation_plan(write_plan: WritePlan, device_key: str) -> WritePlan | None:
    operation = next(
        (item for item in write_plan.operations if item.device_key == device_key), None
    )
    if operation is None:
        return None
    summary = WritePlanSummary(
        total_operations=1,
        create_operations=(
            1 if operation.operation_type == OperationType.CREATE_DEVICE else 0
        ),
        update_operations=(
            1 if operation.operation_type == OperationType.UPDATE_DEVICE else 0
        ),
        blocker_issues=0,
        warning_issues=0,
        blocked_device_keys=(),
        requires_confirmation=True,
        confirmation_message=(
            f"Confirm execution of 1 operation ({operation.device_key})."
        ),
    )
    return WritePlan(
        operations=(operation,),
        issues=(),
        executable=True,
        summary=summary,
    )


def _unifi_source_id_from_device_key(device_key: str) -> str:
    key = device_key.strip()
    if key.startswith("create:unifi_network:"):
        return key.split(":", maxsplit=2)[2].strip()
    if key.startswith("unifi_network:") and "->" in key:
        return key.split("->", maxsplit=1)[0].split(":", maxsplit=1)[1].strip()
    return ""


def _find_unifi_raw_device(
    raw_devices: tuple[dict[str, object], ...], source_id: str
) -> dict[str, object] | None:
    needle = source_id.strip()
    if not needle:
        return None
    for row in raw_devices:
        row_id = ""
        if "id" in row and isinstance(row.get("id"), str):
            row_id = str(row.get("id", "")).strip()
        elif "_id" in row and isinstance(row.get("_id"), str):
            row_id = str(row.get("_id", "")).strip()
        if row_id == needle:
            return row
    return None
