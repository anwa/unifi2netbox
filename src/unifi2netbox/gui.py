import json
from dataclasses import asdict
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

from PySide6.QtCore import (
    QItemSelectionModel,
    QObject,
    QPoint,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from unifi2netbox import theme
from unifi2netbox.config import (
    BehaviorConfig,
    ConfigError,
    NetBoxConfig,
    ProtectConfig,
    UiConfig,
    UniFiConfig,
    load_behavior_config,
    load_config,
    load_protect_config,
    load_ui_config,
    load_unifi_config,
    save_connections,
    save_ui_config,
)
from unifi2netbox.connections import (
    Checker,
    ConnectionRunner,
    check_protect_connection,
    check_unifi_connection,
)
from unifi2netbox.gui_review import (
    COL_CHANGE,
    COL_DEVICE,
    COL_MODEL,
    COL_NETBOX,
    COL_SELECT,
    COL_STATUS,
    BadgeDelegate,
    CableTableModel,
    ConfirmDialog,
    DetailPanel,
    HistoryDialog,
    InterfaceTableModel,
    NetworkTableModel,
    ReviewTableModel,
    banner,
    device_summary,
)
from unifi2netbox.journal_store import JOURNAL_FILENAME, JournalStore, JournalStoreError
from unifi2netbox.netbox import ConnectionResult, ConnectionState, check_connection
from unifi2netbox.pipeline import (
    InventoryPreviewResult,
    WriteExecutionReport,
    build_inventory_preview,
    run_write_execution,
)
from unifi2netbox.preview import DifferencePreview
from unifi2netbox.review import (
    ALL,
    ATTENTION,
    CABLES,
    CATEGORY_LABELS,
    CREATE,
    IN_SYNC,
    INTERFACES,
    NETBOX_ONLY,
    NETWORKS,
    UPDATE,
    ReviewState,
    humanize_timestamp,
    single_operation_plan,
)
from unifi2netbox.write_plan import WritePlan

# Kept for callers that used the former private helper.
_single_operation_plan = single_operation_plan

STATE_TONES = {
    ConnectionState.ONLINE: "success",
    ConnectionState.CHECKING: "accent",
    ConnectionState.UNCONFIGURED: "neutral",
}


def state_tone(state: str) -> str:
    if state in STATE_TONES:
        return STATE_TONES[state]
    if state in (ConnectionState.UNSUPPORTED, ConnectionState.PARTIAL):
        return "warning"
    return "danger"


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
        protect_config: ProtectConfig | None = None,
    ) -> None:
        super().__init__()
        self.config_path = config_path
        self.netbox_config = netbox_config
        self.unifi_config = unifi_config
        self.protect_config = protect_config
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
                protect_config=self.protect_config,
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
        unifi_config: UniFiConfig | None = None,
        journal_path: Path | None = None,
        network_plan=None,
        interface_plan=None,
        cable_plan=None,
    ) -> None:
        super().__init__()
        self.unifi_config = unifi_config
        self.journal_path = journal_path
        self.network_plan = network_plan
        self.interface_plan = interface_plan
        self.cable_plan = cable_plan
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
                unifi_config=self.unifi_config,
                journal_path=self.journal_path,
                network_plan=self.network_plan,
                interface_plan=self.interface_plan,
                cable_plan=self.cable_plan,
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
        unifi_config: UniFiConfig | None = None,
        journal_path: Path | None = None,
        network_plan=None,
        interface_plan=None,
        cable_plan=None,
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
            unifi_config=unifi_config,
            journal_path=journal_path,
            network_plan=network_plan,
            interface_plan=interface_plan,
            cable_plan=cable_plan,
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
        protect_config: ProtectConfig | None = None,
    ) -> bool:
        if self.busy:
            return False
        self.job = InventoryPreviewJob(
            self.config_path,
            netbox,
            unifi,
            include_all_netbox_delete_candidates,
            netbox_site_name,
            protect_config,
        )
        self.job.signals.finished.connect(self._finished)
        self.pool.start(self.job)
        return True

    @Slot(object)
    def _finished(self, result: InventoryPreviewResult) -> None:
        self.job = None
        self.finished.emit(result)


def plain_label(text: str = "", role: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if role:
        label.setProperty("role", role)
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
        protect: bool = False,
        sites: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__(parent)
        self.is_unifi = unifi and not protect
        self.is_protect = protect
        unifi = unifi or protect
        self.state = ConnectionState.UNCONFIGURED
        self.runner = ConnectionRunner(pool, checker, self)
        self.runner.finished.connect(self.test_finished)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        heading = "UniFi Protect" if protect else "UniFi Network" if unifi else "NetBox"
        layout.addWidget(plain_label(heading, "heading"))
        layout.addWidget(
            plain_label(
                (
                    "Optional. Console running UniFi Protect, for example a UNVR. "
                    "Use a local integration API key created on that console. "
                    "Protect is only read; recordings and streams are never "
                    "accessed."
                    if protect
                    else "Local console of your UniFi Network application. Use a "
                    "local integration API key; cloud keys do not work."
                    if unifi
                    else "Your NetBox instance and an API token with device read "
                    "access (and write access for applying changes)."
                ),
                "secondary",
            )
        )
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.url = QLineEdit(config.url)
        self.url.setPlaceholderText(
            "https://unvr.example.lan"
            if protect
            else "https://unifi.example.lan"
            if unifi
            else "https://netbox.example.lan"
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
        self.ca_bundle.setPlaceholderText("Optional private CA file")
        ca_row = QHBoxLayout()
        ca_row.addWidget(self.ca_bundle)
        self.browse = QToolButton()
        self.browse.setIcon(
            theme.icon("DocumentOpen", QStyle.StandardPixmap.SP_DirOpenIcon)
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
        self.site.setVisible(self.is_unifi)
        self.update_sites(sites, config.site if isinstance(config, UniFiConfig) else "")
        if self.is_unifi:
            form.addRow("Site", self.site)
        form.addRow("", self.verify_tls)
        form.addRow("CA bundle", ca_row)
        form.addRow("Request timeout", self.timeout)
        layout.addLayout(form)
        self.warning = plain_label()
        self.warning.setObjectName("securityWarning")
        layout.addWidget(self.warning)
        self.outcome = plain_label()
        self.outcome.setObjectName("testOutcome")
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
        theme.set_variant(
            self.warning, "badge", "warning" if self.warning.text() else ""
        )

    def choose_ca(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Choose CA bundle")
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
        if self.is_protect:
            return ProtectConfig(**asdict(config))
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
            self._tone_outcome()
            self.changed.emit()
            return
        self.state = ConnectionState.CHECKING
        self.outcome.setText("Checking...")
        self._tone_outcome()
        self.runner.start(config)
        self.changed.emit()

    def test_finished(self, config: NetBoxConfig, result: ConnectionResult) -> None:
        self.state = result.state
        self.outcome.setText(f"{result.state}: {result.message}")
        self._tone_outcome()
        if self.is_unifi:
            self.update_sites(result.sites, self.site_value())
        self.changed.emit()

    def _tone_outcome(self) -> None:
        theme.set_variant(self.outcome, "badge", state_tone(self.state))


class SettingsDialog(QDialog):
    PAGES = ("NetBox", "UniFi Network", "UniFi Protect", "Sync defaults")

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
        protect_config: ProtectConfig | None = None,
        protect_checker: Checker = check_protect_connection,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.saved_config: NetBoxConfig | None = None
        self.saved_unifi_config: UniFiConfig | None = None
        self.saved_protect_config: ProtectConfig | None = None
        self.saved_behavior_config: BehaviorConfig | None = None
        self.close_pending = False
        try:
            self.behavior = load_behavior_config(path)
        except ConfigError:
            self.behavior = BehaviorConfig()
        self.setWindowTitle("Settings")
        self.resize(760, 520)
        self.setMinimumSize(640, 460)

        self.netbox = ConnectionSettingsForm(config, pool, checker)
        self.unifi = ConnectionSettingsForm(
            unifi_config if unifi_config is not None else load_unifi_config(path),
            pool,
            unifi_checker,
            unifi=True,
            sites=sites,
        )
        if protect_config is None:
            try:
                protect_config = load_protect_config(path)
            except ConfigError:
                protect_config = ProtectConfig()
        self.protect = ConnectionSettingsForm(
            protect_config, pool, protect_checker, protect=True
        )
        sync_page = QWidget()
        sync = QVBoxLayout(sync_page)
        sync.setContentsMargins(0, 0, 0, 0)
        sync.setSpacing(10)
        sync.addWidget(plain_label("Sync defaults", "heading"))
        sync.addWidget(
            plain_label(
                "Defaults for new NetBox devices and how UniFi values are mapped. "
                "You can still change each device before applying.",
                "secondary",
            )
        )
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.netbox_site_name = QLineEdit(self.behavior.netbox_site_name)
        self.netbox_site_name.setPlaceholderText("Name of an existing NetBox site")
        form.addRow("NetBox site for UniFi devices", self.netbox_site_name)
        self.default_device_role_name = QLineEdit(
            self.behavior.default_device_role_name
        )
        self.default_device_role_name.setPlaceholderText("Access Point")
        form.addRow("Default device role", self.default_device_role_name)
        sync.addLayout(form)
        self.include_all_netbox_delete_candidates = QCheckBox(
            "Show NetBox-only devices from all sites (not only the UniFi site)"
        )
        self.include_all_netbox_delete_candidates.setChecked(
            self.behavior.include_all_netbox_delete_candidates
        )
        sync.addWidget(self.include_all_netbox_delete_candidates)
        sync.addWidget(
            plain_label(
                "NetBox-only devices are listed for review. The app never deletes "
                "anything.",
                "caption",
            )
        )
        sync.addStretch()
        sync.addWidget(plain_label("Configuration file", "caption"))
        path_label = plain_label(str(path), "caption")
        path_label.setObjectName("configPath")
        path_label.setWordWrap(False)
        path_label.setToolTip(str(path))
        sync.addWidget(path_label)
        sync.addWidget(
            plain_label("Tokens are stored locally as plain text.", "caption")
        )

        self.nav = QListWidget()
        self.nav.setObjectName("settingsNav")
        self.nav.setFixedWidth(170)
        self.nav.addItems(list(self.PAGES))
        self.pages = QStackedWidget()
        for page in (self.netbox, self.unifi, self.protect, sync_page):
            self.pages.addWidget(page)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)
        # Former name kept for callers that enable or disable the editors.
        self.tabs = self.pages

        body = QHBoxLayout()
        body.setSpacing(18)
        body.addWidget(self.nav)
        body.addWidget(self.pages, 1)

        self.outcome = plain_label("", "secondary")
        self.outcome.setObjectName("settingsOutcome")
        self.test_button = QPushButton("Check connections")
        self.test_button.setIcon(
            theme.icon("SyncSynchronizing", QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.test_button.clicked.connect(self.test_connections)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = QPushButton("Save")
        self.save_button.setProperty("variant", "primary")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.save)
        footer = QHBoxLayout()
        footer.addWidget(self.test_button)
        footer.addWidget(self.outcome, 1)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.save_button)
        self.buttons = QWidget()
        self.buttons.setLayout(footer)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.addLayout(body, 1)
        layout.addWidget(self.buttons)
        self.netbox.changed.connect(self.update_activity)
        self.unifi.changed.connect(self.update_activity)
        self.protect.changed.connect(self.update_activity)

    def show_page(self, name: str) -> None:
        if name in self.PAGES:
            self.nav.setCurrentRow(self.PAGES.index(name))

    @property
    def busy(self) -> bool:
        return (
            self.netbox.runner.busy
            or self.unifi.runner.busy
            or self.protect.runner.busy
        )

    def save(self) -> None:
        if self.busy:
            return
        try:
            netbox = self.netbox.config_from_fields()
            unifi = self.unifi.config_from_fields()
            if not isinstance(unifi, UniFiConfig):
                raise ConfigError("UniFi settings are invalid.")
            protect = self.protect.config_from_fields()
            if not isinstance(protect, ProtectConfig):
                raise ConfigError("Protect settings are invalid.")
            behavior = BehaviorConfig(
                include_all_netbox_delete_candidates=(
                    self.include_all_netbox_delete_candidates.isChecked()
                ),
                default_device_role_name=self.default_device_role_name.text().strip(),
                netbox_site_name=self.netbox_site_name.text().strip(),
            )
            save_connections(self.path, netbox, unifi, behavior, protect)
        except ConfigError as error:
            self.outcome.setText(str(error))
            return
        self.saved_config = netbox
        self.saved_unifi_config = unifi
        self.saved_protect_config = protect
        self.saved_behavior_config = behavior
        self.accept()

    def test_connections(self) -> None:
        if self.busy:
            return
        self.netbox.test_connection()
        self.unifi.test_connection()
        self.protect.test_connection()
        self.update_activity()

    def update_activity(self) -> None:
        busy = self.busy
        self.pages.setEnabled(not busy)
        self.nav.setEnabled(not busy)
        self.buttons.setEnabled(not busy)
        self.outcome.setText(
            f"NetBox: {self.netbox.state}\nUniFi Network: {self.unifi.state}"
            f"\nUniFi Protect: {self.protect.state}"
        )
        if self.close_pending and not busy:
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


class ConnectionPanel(QFrame):
    """Connection controller plus its detail card, shown from the header chip."""

    idle = Signal()
    activity_changed = Signal()
    status_changed = Signal()

    def __init__(
        self,
        config_path: Path,
        pool: QThreadPool,
        checker: Checker,
        *,
        unifi: bool = False,
        protect: bool = False,
    ) -> None:
        super().__init__()
        self.path = config_path
        self.pool = pool
        self.checker = checker
        self.is_unifi = unifi and not protect
        self.is_protect = protect
        self.closing = False
        self.pending_check = False
        self.site_choices = ()
        self.name = (
            "UniFi Protect" if protect else "UniFi Network" if unifi else "NetBox"
        )
        self.runner = ConnectionRunner(pool, checker, self)
        self.runner.finished.connect(self.connection_finished)
        self.config_error = ""
        try:
            self.config = (
                load_protect_config(config_path)
                if protect
                else load_unifi_config(config_path)
                if unifi
                else load_config(config_path)
            )
        except ConfigError as error:
            self.config = (
                ProtectConfig()
                if protect
                else UniFiConfig()
                if unifi
                else NetBoxConfig()
            )
            self.config_error = str(error)

        self.setProperty("card", True)
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(plain_label(self.name, "subheading"))
        self.state = plain_label(ConnectionState.UNCONFIGURED)
        self.state.setObjectName("connectionState")
        self.state.setWordWrap(False)
        state_row = QHBoxLayout()
        state_row.addWidget(self.state)
        state_row.addStretch()
        layout.addLayout(state_row)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        self.endpoint = plain_label()
        self.server_version = plain_label("Not checked")
        self.checked_at = plain_label("Not checked")
        self.selected_site = plain_label("Not selected")
        rows = [
            ("Endpoint", self.endpoint),
            ("Version", self.server_version),
            ("Last check", self.checked_at),
        ]
        if self.is_unifi:
            rows.append(("Site", self.selected_site))
        for index, (title, widget) in enumerate(rows):
            grid.addWidget(plain_label(title, "secondary"), index, 0)
            grid.addWidget(widget, index, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        self.details = plain_label(
            "Optional. Set the URL and local API key of the console running "
            "UniFi Protect."
            if protect
            else "Set a console URL and local API key."
            if unifi
            else "Set a NetBox URL and API token.",
            "secondary",
        )
        self.warning = plain_label()
        self.warning.setObjectName("connectionWarning")
        layout.addWidget(self.details)
        layout.addWidget(self.warning)
        self.check_button = QPushButton("Check again")
        self.check_button.clicked.connect(self.recheck)
        layout.addWidget(self.check_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.update_config_display()
        if self.config_error:
            self.show_result(ConnectionResult(ConnectionState.ERROR, self.config_error))
        elif self.config.configured:
            QTimer.singleShot(0, self.recheck)

    @property
    def current_state(self) -> str:
        return self.state.text()

    def summary(self) -> str:
        """Short chip text, for example 'NetBox 4.7.3' or 'UniFi · Offline'."""
        short = "Protect" if self.is_protect else "UniFi" if self.is_unifi else "NetBox"
        state = self.current_state
        if self.is_protect and state == ConnectionState.UNCONFIGURED:
            return "Protect · Off"
        version_text = self.server_version.text()
        if state == ConnectionState.ONLINE:
            text = f"{short} {version_text}".strip()
            if self.is_unifi and self.selected_site.text() not in ("", "Not selected"):
                text += f" · {self.selected_site.text().split(' (')[0]}"
            return text
        return f"{short} · {state}"

    def update_config_display(self) -> None:
        self.endpoint.setText(self.config.url or "Not configured")
        self.warning.setText(self.config.security_warning)
        theme.set_variant(
            self.warning, "badge", "warning" if self.config.security_warning else ""
        )
        self.status_changed.emit()

    def apply_config(self, config: NetBoxConfig) -> None:
        self.config = config
        self.config_error = ""
        self.server_version.setText("Not checked")
        self.checked_at.setText("Not checked")
        self.selected_site.setText("Not selected")
        self.site_choices = ()
        self.update_config_display()
        self.recheck()

    def _set_state(self, state: str) -> None:
        self.state.setText(state)
        theme.set_variant(self.state, "badge", state_tone(state))
        self.status_changed.emit()

    def recheck(self) -> None:
        if self.closing:
            return
        if self.runner.busy:
            self.pending_check = True
            self._set_state(ConnectionState.CHECKING)
            self.details.setText("Waiting for the previous check to finish...")
            return
        self.pending_check = False
        self.details.setText("Checking authenticated API access...")
        self._set_state(ConnectionState.CHECKING)
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
        self.details.setText(result.message)
        self.server_version.setText(result.version or "Not available")
        self.selected_site.setText(result.site or "Not selected")
        self.site_choices = result.sites
        self.checked_at.setText(
            humanize_timestamp(
                datetime.now().astimezone().isoformat(timespec="seconds")
            )
        )
        self._set_state(result.state)

    def stop_for_close(self) -> None:
        self.closing = True
        self.pending_check = False
        if self.runner.busy:
            self.details.setText("Finishing the connection check before closing...")


class ConnectionChip(QToolButton):
    """Header pill showing one connection; click for the detail card."""

    def __init__(self, panel: ConnectionPanel, parent=None) -> None:
        super().__init__(parent)
        self.panel = panel
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.popup = QFrame(self, Qt.WindowType.Popup)
        popup_layout = QVBoxLayout(self.popup)
        popup_layout.setContentsMargins(0, 0, 0, 0)
        popup_layout.addWidget(panel)
        self.clicked.connect(self.show_details)
        panel.status_changed.connect(self.update_chip)
        self.update_chip()

    def update_chip(self) -> None:
        state = self.panel.current_state
        tone = state_tone(state)
        if tone == "success" and self.panel.config.security_warning:
            tone = "warning"
        font = self.font()
        font.setBold(True)
        self.setFont(font)
        self.setText(f"●  {self.panel.summary()}")
        self.updateGeometry()
        self.adjustSize()
        tip = self.panel.details.text()
        if self.panel.config.security_warning:
            tip += f"\n{self.panel.config.security_warning}"
        self.setToolTip(tip)
        theme.set_variant(self, "chip", tone)

    def show_details(self) -> None:
        self.popup.adjustSize()
        self.popup.move(self.mapToGlobal(QPoint(0, self.height() + 6)))
        self.popup.show()


class SummaryCard(QPushButton):
    """Clickable count card that also acts as a filter shortcut."""

    def __init__(self, category: str, caption: str, parent=None) -> None:
        super().__init__(parent)
        self.category = category
        self.caption = caption
        self.setCheckable(True)
        self.setProperty("summaryCard", True)
        self.setMinimumHeight(72)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(0)
        self.count_label = QLabel("0")
        self.count_label.setObjectName("cardCount")
        self.caption_label = QLabel(caption)
        self.caption_label.setObjectName("cardCaption")
        for widget in (self.count_label, self.caption_label):
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(widget)
        self.set_count(0)

    def set_count(self, count: int) -> None:
        self.count = count
        self.count_label.setText(str(count))
        self.setAccessibleName(f"{count} {self.caption}")


class MainWindow(QMainWindow):
    def __init__(
        self,
        config_path: Path,
        pool: QThreadPool,
        checker: Checker = check_connection,
        *,
        open_first_run: bool = True,
        unifi_checker: Checker = check_unifi_connection,
        protect_checker: Checker = check_protect_connection,
    ) -> None:
        super().__init__()
        self.path = config_path
        self.pool = pool
        self.closing = False
        self.inventory_runner = InventoryPreviewRunner(pool, config_path, self)
        self.inventory_runner.finished.connect(self.inventory_preview_finished)
        self.write_runner = WriteExecutionRunner(pool, self)
        self.write_runner.finished.connect(self.write_execution_finished)
        try:
            self.behavior = load_behavior_config(config_path)
        except ConfigError:
            self.behavior = BehaviorConfig()
        try:
            self.ui = load_ui_config(config_path)
        except ConfigError:
            self.ui = UiConfig()
        self.review = ReviewState(behavior=self.behavior)
        self.journal_path = config_path.with_name(JOURNAL_FILENAME)
        self.last_result: InventoryPreviewResult | None = None
        self.netbox = ConnectionPanel(config_path, pool, checker)
        self.unifi = ConnectionPanel(config_path, pool, unifi_checker, unifi=True)
        self.protect = ConnectionPanel(config_path, pool, protect_checker, protect=True)
        self.setWindowTitle(f"unifi2netbox {version('unifi2netbox')}")
        self.resize(1180, 760)
        self.setMinimumSize(860, 560)
        # Aliases to the NetBox connection, used by older callers and tests.
        self.runner = self.netbox.runner
        self.state = self.netbox.state
        self.endpoint = self.netbox.endpoint
        self.server_version = self.netbox.server_version
        self.checked_at = self.netbox.checked_at
        self.details = self.netbox.details
        self.warning = self.netbox.warning

        self._build_actions()
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(20, 14, 20, 12)
        body_layout.setSpacing(12)
        self.banner_area = QVBoxLayout()
        self.banner_area.setSpacing(8)
        body_layout.addLayout(self.banner_area)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_empty_page())
        self.pages.addWidget(self._build_review_page())
        body_layout.addWidget(self.pages, 1)
        root.addWidget(body, 1)
        root.addWidget(self._build_apply_bar())
        self.setCentralWidget(central)

        for panel in (self.netbox, self.unifi, self.protect):
            panel.idle.connect(self.finish_close)
            panel.activity_changed.connect(self.update_check_action)
            panel.status_changed.connect(self.update_empty_state)
        self.update_empty_state()
        self.update_review()
        self.statusBar().showMessage(f"Configuration: {config_path}")
        if (
            open_first_run
            and not self.netbox.config.configured
            and not self.netbox.config_error
        ):
            QTimer.singleShot(0, self.open_settings)

    # -- construction ----------------------------------------------------------

    def _build_actions(self) -> None:
        self.check_action = QAction(
            theme.icon("SyncSynchronizing", QStyle.StandardPixmap.SP_BrowserReload),
            "Check connections",
            self,
        )
        self.check_action.setToolTip("Check NetBox and UniFi connections")
        self.check_action.triggered.connect(self.recheck)
        self.preview_action = QAction(
            theme.icon("ViewRefresh", QStyle.StandardPixmap.SP_BrowserReload),
            "Refresh",
            self,
        )
        self.preview_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Refresh))
        self.preview_action.setToolTip("Read both inventories and compare them (F5)")
        self.preview_action.triggered.connect(self.refresh_inventory_preview)
        self.settings_action = QAction(
            theme.icon(
                "DocumentProperties", QStyle.StandardPixmap.SP_FileDialogDetailedView
            ),
            "Settings",
            self,
        )
        self.settings_action.setShortcut(
            QKeySequence(QKeySequence.StandardKey.Preferences)
        )
        self.settings_action.setToolTip("Edit NetBox, UniFi and sync settings")
        self.settings_action.triggered.connect(self.open_settings)
        self.export_action = QAction("Export UniFi API dump...", self)
        self.export_action.triggered.connect(self.export_unifi_api_dump)
        self.history_action = QAction("Write history...", self)
        self.history_action.triggered.connect(self.show_history)
        self.copy_summary_action = QAction("Copy summary", self)
        self.copy_summary_action.triggered.connect(self.copy_summary)
        self.exit_action = QAction("Exit", self)
        self.exit_action.triggered.connect(self.close)
        for action in (self.preview_action, self.settings_action):
            self.addAction(action)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 10, 14, 10)
        layout.setSpacing(10)
        title = QLabel("unifi2netbox")
        title.setObjectName("appTitle")
        layout.addWidget(title)
        layout.addSpacing(8)
        self.netbox_chip = ConnectionChip(self.netbox, header)
        self.netbox_chip.setObjectName("netboxChip")
        self.unifi_chip = ConnectionChip(self.unifi, header)
        self.unifi_chip.setObjectName("unifiChip")
        self.protect_chip = ConnectionChip(self.protect, header)
        self.protect_chip.setObjectName("protectChip")
        layout.addWidget(self.netbox_chip)
        layout.addWidget(self.unifi_chip)
        layout.addWidget(self.protect_chip)
        layout.addStretch()
        check = QToolButton()
        check.setDefaultAction(self.check_action)
        check.setProperty("variant", "ghost")
        check.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        layout.addWidget(check)
        self.refresh_button = QPushButton(self.preview_action.icon(), "Refresh")
        self.refresh_button.setObjectName("refreshButton")
        self.refresh_button.setProperty("variant", "primary")
        self.refresh_button.setToolTip(self.preview_action.toolTip())
        self.refresh_button.clicked.connect(self.preview_action.trigger)
        layout.addWidget(self.refresh_button)
        settings = QToolButton()
        settings.setDefaultAction(self.settings_action)
        settings.setProperty("variant", "ghost")
        settings.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        layout.addWidget(settings)
        layout.addWidget(self._build_theme_button())
        more = QToolButton()
        more.setObjectName("moreButton")
        more.setText("⋯")
        more.setToolTip("More actions")
        more.setProperty("variant", "ghost")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        menu.addAction(self.history_action)
        menu.addAction(self.export_action)
        menu.addAction(self.copy_summary_action)
        menu.addSeparator()
        menu.addAction(self.exit_action)
        more.setMenu(menu)
        layout.addWidget(more)
        return header

    def _build_theme_button(self) -> QToolButton:
        button = QToolButton()
        button.setObjectName("themeButton")
        button.setProperty("variant", "ghost")
        button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        button.clicked.connect(self.toggle_theme)
        menu = QMenu(button)
        self.theme_actions: dict[str, QAction] = {}
        group = QActionGroup(menu)
        for choice, text in (
            ("system", "Follow system"),
            ("light", "Light"),
            ("dark", "Dark"),
        ):
            action = QAction(text, menu)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _c=False, value=choice: self.set_theme(value)
            )
            group.addAction(action)
            menu.addAction(action)
            self.theme_actions[choice] = action
        button.setMenu(menu)
        self.theme_button = button
        self.update_theme_button()
        return button

    def toggle_theme(self) -> None:
        """Switch between light and dark, starting from what is shown now."""
        self.set_theme("light" if theme.is_dark() else "dark")

    def set_theme(self, choice: str) -> None:
        app = QApplication.instance()
        if isinstance(app, QApplication):
            theme.apply_theme(app, theme.dark_for(choice))
        self.ui = UiConfig(theme=choice)
        try:
            save_ui_config(self.path, self.ui)
        except ConfigError as error:
            self.statusBar().showMessage(f"Theme not saved: {error}")
        self.update_theme_button()
        self.table.viewport().update()

    def update_theme_button(self) -> None:
        dark = theme.is_dark()
        font = self.theme_button.font()
        font.setPointSizeF(13)
        self.theme_button.setFont(font)
        self.theme_button.setText("☀" if dark else "☾")
        self.theme_button.setToolTip(
            "Switch to light mode" if dark else "Switch to dark mode"
        )
        self.theme_actions[self.ui.theme].setChecked(True)

    def _build_empty_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch()
        self.empty_title = plain_label("Compare UniFi with NetBox", "emptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_text = plain_label("", "secondary")
        self.empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_button = QPushButton()
        self.empty_button.setObjectName("emptyAction")
        self.empty_button.setProperty("variant", "primary")
        self.empty_button.clicked.connect(self.empty_action)
        layout.addWidget(self.empty_title)
        layout.addWidget(self.empty_text)
        layout.addSpacing(8)
        layout.addWidget(self.empty_button, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        return page

    def _build_review_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.cards: dict[str, SummaryCard] = {}
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        for category, caption in (
            (CREATE, "new devices"),
            (UPDATE, "with changes"),
            (IN_SYNC, "in sync"),
            (ATTENTION, "need attention"),
            (NETBOX_ONLY, "only in NetBox"),
            (NETWORKS, "network changes"),
            (INTERFACES, "interface changes"),
            (CABLES, "cable suggestions"),
        ):
            card = SummaryCard(category, caption)
            card.setObjectName(f"card_{category}")
            card.clicked.connect(lambda _c=False, cat=category: self.set_filter(cat))
            self.cards[category] = card
            cards.addWidget(card)
        layout.addLayout(cards)

        filters = QHBoxLayout()
        filters.setSpacing(4)
        self.segments: dict[str, QPushButton] = {}
        for category in (
            ALL,
            CREATE,
            UPDATE,
            IN_SYNC,
            ATTENTION,
            NETBOX_ONLY,
            NETWORKS,
            INTERFACES,
            CABLES,
        ):
            button = QPushButton(CATEGORY_LABELS[category])
            button.setObjectName(f"filter_{category}")
            button.setCheckable(True)
            button.setProperty("segment", True)
            button.clicked.connect(lambda _c=False, cat=category: self.set_filter(cat))
            self.filter_group.addButton(button)
            self.segments[category] = button
            filters.addWidget(button)
        filters.addStretch()
        self.search = QLineEdit()
        self.search.setObjectName("deviceSearch")
        self.search.setPlaceholderText("Filter by name, model, port, VLAN or subnet")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(lambda _t: self.apply_filter())
        filters.addWidget(self.search)
        layout.addLayout(filters)

        self.table_model = ReviewTableModel(self)
        self.table_model.selection_changed.connect(self.on_selection_changed)
        self.table = QTableView()
        self.table.setObjectName("reviewTable")
        self.table.setModel(self.table_model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        badge = BadgeDelegate(self.table)
        self.table.setItemDelegateForColumn(COL_CHANGE, badge)
        self.table.setItemDelegateForColumn(COL_STATUS, badge)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(COL_SELECT, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(COL_SELECT, 36)
        header.setSectionResizeMode(COL_DEVICE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_CHANGE, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(COL_CHANGE, 120)
        header.setSectionResizeMode(COL_MODEL, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(COL_MODEL, 150)
        header.setSectionResizeMode(COL_NETBOX, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(COL_STATUS, 190)
        self.table.selectionModel().currentRowChanged.connect(
            lambda current, _previous: self.show_detail(
                self.table_model.key_at(current.row())
            )
        )

        self.network_model = NetworkTableModel(self)
        self.network_model.selection_changed.connect(self.on_selection_changed)
        self.network_table = QTableView()
        self.network_table.setObjectName("networkTable")
        self.network_table.setModel(self.network_model)
        self.network_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.network_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.network_table.setShowGrid(False)
        self.network_table.verticalHeader().hide()
        self.network_table.verticalHeader().setDefaultSectionSize(38)
        self.network_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        net_badge = BadgeDelegate(self.network_table)
        self.network_table.setItemDelegateForColumn(4, net_badge)
        self.network_table.setItemDelegateForColumn(5, net_badge)
        net_header = self.network_table.horizontalHeader()
        net_header.setHighlightSections(False)
        net_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        net_header.resizeSection(0, 36)
        net_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        net_header.resizeSection(2, 70)
        net_header.resizeSection(3, 150)
        net_header.resizeSection(4, 120)
        net_header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.network_table.selectionModel().currentRowChanged.connect(
            lambda current, _previous: self.show_detail(
                self.network_model.key_at(current.row())
            )
        )
        self.interface_model = InterfaceTableModel(self)
        self.interface_model.selection_changed.connect(self.on_selection_changed)
        self.interface_table = QTableView()
        self.interface_table.setObjectName("interfaceTable")
        self.interface_table.setModel(self.interface_model)
        self.interface_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.interface_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.interface_table.setShowGrid(False)
        self.interface_table.setWordWrap(False)
        self.interface_table.verticalHeader().hide()
        self.interface_table.verticalHeader().setDefaultSectionSize(38)
        self.interface_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        if_badge = BadgeDelegate(self.interface_table)
        self.interface_table.setItemDelegateForColumn(5, if_badge)
        self.interface_table.setItemDelegateForColumn(6, if_badge)
        if_header = self.interface_table.horizontalHeader()
        if_header.setHighlightSections(False)
        if_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        if_header.resizeSection(0, 36)
        if_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        if_header.resizeSection(2, 90)
        if_header.resizeSection(3, 150)
        if_header.resizeSection(4, 170)
        if_header.resizeSection(5, 100)
        if_header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.interface_table.selectionModel().currentRowChanged.connect(
            lambda current, _previous: self.show_detail(
                self.interface_model.key_at(current.row())
            )
        )
        self.cable_model = CableTableModel(self)
        self.cable_model.selection_changed.connect(self.on_selection_changed)
        self.cable_table = QTableView()
        self.cable_table.setObjectName("cableTable")
        self.cable_table.setModel(self.cable_model)
        self.cable_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.cable_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.cable_table.setShowGrid(False)
        self.cable_table.setWordWrap(False)
        self.cable_table.verticalHeader().hide()
        self.cable_table.verticalHeader().setDefaultSectionSize(38)
        self.cable_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        cable_badge = BadgeDelegate(self.cable_table)
        self.cable_table.setItemDelegateForColumn(3, cable_badge)
        self.cable_table.setItemDelegateForColumn(4, cable_badge)
        cable_header = self.cable_table.horizontalHeader()
        cable_header.setHighlightSections(False)
        cable_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        cable_header.resizeSection(0, 36)
        cable_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        cable_header.resizeSection(2, 120)
        cable_header.resizeSection(3, 110)
        cable_header.resizeSection(4, 120)
        self.cable_table.selectionModel().currentRowChanged.connect(
            lambda current, _previous: self.show_detail(
                self.cable_model.key_at(current.row())
            )
        )
        self.table_stack = QStackedWidget()
        self.table_stack.addWidget(self.table)
        self.table_stack.addWidget(self.network_table)
        self.table_stack.addWidget(self.interface_table)
        self.table_stack.addWidget(self.cable_table)

        self.detail = DetailPanel()
        self.detail.setObjectName("detailPanel")
        self.detail.changed.connect(self.on_detail_changed)
        self.detail.apply_requested.connect(self.execute_selected_preview_row)
        self.detail.export_requested.connect(self.export_unifi_row_dump)
        self.detail.copy_requested.connect(self.copy_device_details)
        detail_frame = QFrame()
        detail_frame.setProperty("card", True)
        detail_layout = QVBoxLayout(detail_frame)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.addWidget(self.detail)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.table_stack)
        splitter.addWidget(detail_frame)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([700, 400])
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        self.segments[ALL].setChecked(True)
        return page

    def _build_apply_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("applyBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 10, 20, 10)
        self.selection_label = plain_label("", "secondary")
        self.selection_label.setWordWrap(False)
        self.selection_label.setObjectName("selectionLabel")
        layout.addWidget(self.selection_label)
        self.select_all_button = QPushButton("Select all")
        self.select_all_button.setProperty("variant", "ghost")
        self.select_all_button.clicked.connect(lambda: self.select_visible(True))
        self.select_none_button = QPushButton("Select none")
        self.select_none_button.setProperty("variant", "ghost")
        self.select_none_button.clicked.connect(lambda: self.select_visible(False))
        layout.addWidget(self.select_all_button)
        layout.addWidget(self.select_none_button)
        layout.addStretch()
        self.dry_run_only = QCheckBox("Dry run (no changes)")
        self.dry_run_only.setObjectName("dryRun")
        self.dry_run_only.setToolTip("Simulate the writes and report what would happen")
        self.dry_run_only.toggled.connect(lambda _c: self.update_apply_bar())
        layout.addWidget(self.dry_run_only)
        self.execute_plan_button = QPushButton("Apply changes")
        self.execute_plan_button.setObjectName("applyButton")
        self.execute_plan_button.setProperty("variant", "primary")
        self.execute_plan_button.clicked.connect(self.execute_write_plan_from_preview)
        layout.addWidget(self.execute_plan_button)
        self.apply_bar = bar
        return bar

    # -- compatibility properties ---------------------------------------------

    @property
    def current_difference_preview(self) -> DifferencePreview | None:
        return self.review.diff

    @property
    def current_write_plan(self) -> WritePlan | None:
        return self.review.plan

    @property
    def create_device_type_by_device_key(self) -> dict[str, str]:
        return self.review.type_by_key

    # -- state rendering -------------------------------------------------------

    def set_banner(self, text: str, tone: str = "neutral", action: str = "") -> None:
        self.clear_banner()
        if not text:
            return
        frame = banner(text, tone)
        frame.setObjectName("mainBanner")
        if action == "refresh":
            button = QPushButton("Refresh now")
            button.setObjectName("bannerRefresh")
            button.clicked.connect(self.refresh_inventory_preview)
            frame.layout().addWidget(button)
        self.banner_area.addWidget(frame)

    def clear_banner(self) -> None:
        while self.banner_area.count():
            widget = self.banner_area.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()

    def banner_text(self) -> str:
        """Text of the current banner, empty when none is shown."""
        for index in range(self.banner_area.count()):
            widget = self.banner_area.itemAt(index).widget()
            if widget is not None:
                text = widget.findChild(QLabel, "bannerText")
                if text is not None:
                    return text.text()
        return ""

    def update_empty_state(self) -> None:
        configured = self.netbox.config.configured and self.unifi.config.configured
        if not configured:
            self.empty_text.setText(
                "Connect NetBox and your UniFi Network console to get started."
            )
            self.empty_button.setText("Open settings")
        else:
            self.empty_text.setText(
                "Refresh reads both inventories and shows what is new, changed "
                "or already in sync. Nothing is written until you apply."
            )
            self.empty_button.setText("Refresh now")

    def empty_action(self) -> None:
        if self.netbox.config.configured and self.unifi.config.configured:
            self.refresh_inventory_preview()
        else:
            self.open_settings()

    def update_review(self, keep_key: str = "") -> None:
        has_rows = bool(
            self.review.rows()
            or self.review.network_rows()
            or self.review.interface_rows()
            or self.review.cable_rows()
        )
        self.pages.setCurrentIndex(1 if has_rows else 0)
        self.network_model.set_state(self.review)
        self.interface_model.set_state(self.review)
        self.cable_model.set_state(self.review)
        self.update_counts_only()
        self.apply_filter(keep_key)

    def set_filter(self, category: str) -> None:
        self.segments[category].setChecked(True)
        for name, card in self.cards.items():
            card.setChecked(name == category)
        self.apply_filter()

    def current_filter(self) -> str:
        return next(
            (name for name, button in self.segments.items() if button.isChecked()), ALL
        )

    def apply_filter(self, keep_key: str = "") -> None:
        views = {
            NETWORKS: (
                self.network_table,
                self.network_model,
                self.review.network_plan,
                "UniFi reports no networks.",
            ),
            INTERFACES: (
                self.interface_table,
                self.interface_model,
                self.review.interface_plan,
                "No matched device has paired ports with configuration.",
            ),
            CABLES: (
                self.cable_table,
                self.cable_model,
                self.review.cable_plan,
                "UniFi reported no links between devices.",
            ),
        }
        if self.current_filter() in views:
            table, model, plan, empty = views[self.current_filter()]
            self.table_stack.setCurrentWidget(table)
            model.set_filter(self.search.text())
            key = keep_key or self.detail.key
            row = model.row_of(key) if key else -1
            if row < 0 and model.rowCount() > 0:
                row = 0
            if row >= 0:
                table.selectionModel().setCurrentIndex(
                    model.index(row, 1),
                    QItemSelectionModel.SelectionFlag.ClearAndSelect
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
                self.show_detail(model.key_at(row))
            else:
                self.detail.show_placeholder(
                    plan.blocker if plan is not None and plan.blocker else empty
                )
            return
        self.table_stack.setCurrentWidget(self.table)
        key = keep_key or self.detail.key
        self.table_model.set_filter(self.current_filter(), self.search.text())
        row = self.table_model.row_of(key) if key else -1
        if row < 0 and self.table_model.rowCount() > 0:
            row = 0
        if row >= 0:
            self.table.selectionModel().setCurrentIndex(
                self.table_model.index(row, COL_DEVICE),
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )
            self.show_detail(self.table_model.key_at(row))
        else:
            self.detail.show_placeholder()

    def show_detail(self, key: str) -> None:
        if key.startswith("network"):
            self.detail.show_network(self.review, key)
        elif key.startswith("interface:"):
            self.detail.show_interface(self.review, key)
        elif key.startswith("cable:"):
            self.detail.show_cable(self.review, key)
        elif key:
            self.detail.show_device(self.review, key)
        else:
            self.detail.show_placeholder()

    def on_selection_changed(self) -> None:
        self.update_counts_only()
        if self.detail.key:
            self.show_detail(self.detail.key)

    def on_detail_changed(self) -> None:
        self.table_model.refresh_rows()
        self.network_model.refresh_rows()
        self.interface_model.refresh_rows()
        self.cable_model.refresh_rows()
        self.update_counts_only()

    def update_counts_only(self) -> None:
        counts = self.review.counts()
        for category, card in self.cards.items():
            card.set_count(
                self.review.network_changes()
                if category == NETWORKS
                else self.review.interface_changes()
                if category == INTERFACES
                else self.review.cable_changes()
                if category == CABLES
                else counts[category]
            )
        for category, button in self.segments.items():
            button.setText(f"{CATEGORY_LABELS[category]} {counts[category]}")
        self.update_apply_bar()

    def update_apply_bar(self) -> None:
        busy = self.closing or self.inventory_runner.busy or self.write_runner.busy
        plan = self.review.plan
        network_ops = self.review.network_operation_count()
        interface_ops = self.review.interface_operation_count()
        cable_ops = self.review.cable_operation_count()
        operations = (
            (len(plan.operations) if plan is not None else 0)
            + network_ops
            + interface_ops
            + cable_ops
        )
        selectable = self.review.selectable_count()
        selected = self.review.selected_count()
        parts = []
        if selectable:
            parts.append(f"{selected} of {selectable} devices selected")
        if network_ops:
            parts.append(f"{network_ops} network writes")
        if interface_ops:
            parts.append(f"{interface_ops} interface writes")
        if cable_ops:
            parts.append(f"{cable_ops} cables")
        self.selection_label.setText(", ".join(parts))
        for button in (self.select_all_button, self.select_none_button):
            button.setVisible(
                bool(
                    selectable
                    or self.review.network_rows()
                    or self.review.interface_rows()
                    or self.review.cable_rows()
                )
            )
        noun = "change" if operations == 1 else "changes"
        self.execute_plan_button.setText(
            f"Dry run {operations} {noun}..."
            if self.dry_run_only.isChecked()
            else f"Apply {operations} {noun}..."
        )
        self.execute_plan_button.setEnabled(not busy and operations > 0)
        self.apply_bar.setVisible(self.pages.currentIndex() == 1)

    def select_visible(self, selected: bool) -> None:
        if self.current_filter() == NETWORKS:
            for row in self.network_model.items:
                self.review.set_network_selected(row.key, "all", selected)
            self.network_model.refresh_rows()
            self.on_selection_changed()
            return
        if self.current_filter() == INTERFACES:
            for row in self.interface_model.items:
                self.review.set_interface_selected(row.key, "all", selected)
            self.interface_model.refresh_rows()
            self.on_selection_changed()
            return
        if self.current_filter() == CABLES:
            for row in self.cable_model.items:
                self.review.set_cable_selected(row.key, selected)
            self.cable_model.refresh_rows()
            self.on_selection_changed()
            return
        keys = tuple(
            item.key
            for item in self.table_model.items
            if item.category in (CREATE, UPDATE)
        )
        self.review.set_all_selected(keys, selected)
        self.table_model.refresh_rows()
        self.on_selection_changed()

    # -- settings and connections ---------------------------------------------

    def open_settings(self, page: str = "") -> None:
        dialog = SettingsDialog(
            self.path,
            self.netbox.config,
            self.pool,
            self.netbox.checker,
            self,
            unifi_config=self.unifi.config,
            unifi_checker=self.unifi.checker,
            sites=self.unifi.site_choices,
            protect_config=self.protect.config,
            protect_checker=self.protect.checker,
        )
        if page:
            dialog.show_page(page)
        if (
            dialog.exec() == QDialog.DialogCode.Accepted
            and dialog.saved_config is not None
            and dialog.saved_unifi_config is not None
        ):
            self.netbox.apply_config(dialog.saved_config)
            self.unifi.apply_config(dialog.saved_unifi_config)
            if dialog.saved_protect_config is not None:
                self.protect.apply_config(dialog.saved_protect_config)
            if dialog.saved_behavior_config is not None:
                self.behavior = dialog.saved_behavior_config
                self.review.behavior = self.behavior
            self.update_empty_state()
        dialog.deleteLater()

    def apply_config(self, config: NetBoxConfig) -> None:
        self.netbox.apply_config(config)

    def recheck(self) -> None:
        self.netbox.recheck()
        self.unifi.recheck()
        self.protect.recheck()

    # -- refresh ---------------------------------------------------------------

    def refresh_inventory_preview(self) -> None:
        if self.closing or self.inventory_runner.busy:
            return
        if not self.netbox.config.configured or not self.unifi.config.configured:
            self.set_banner(
                "Configure NetBox and UniFi Network in Settings before refreshing.",
                "warning",
            )
            return
        self.set_banner("Reading NetBox and UniFi inventories...", "accent")
        self.inventory_runner.start(
            self.netbox.config,
            self.unifi.config,
            include_all_netbox_delete_candidates=(
                self.behavior.include_all_netbox_delete_candidates
            ),
            netbox_site_name=self.behavior.netbox_site_name,
            protect_config=self.protect.config,
        )
        self.update_check_action()

    def inventory_preview_finished(self, result: InventoryPreviewResult) -> None:
        self.last_result = result
        if result.difference_preview is not None:
            self.review = ReviewState(result, self.behavior)
            self.table_model.set_state(self.review)
            self.clear_banner()
            if result.status != "Ready":
                self.set_banner(result.details, "warning")
        else:
            tone = "danger" if result.status == "Error" else "warning"
            detail = result.detail_lines[0] if result.detail_lines else result.details
            self.set_banner(f"{result.status}: {detail}", tone)
        self.update_review()
        when = humanize_timestamp(result.last_updated)
        self.statusBar().showMessage(f"Last refresh {when}  ·  {self.path}")
        self.update_check_action()

    # -- apply -----------------------------------------------------------------

    def execute_write_plan_from_preview(self) -> None:
        self._execute(None)

    def execute_selected_preview_row(self, device_key: str) -> None:
        self._execute(device_key)

    def _execute(self, device_key: str | None) -> None:
        if self.write_runner.busy or self.closing:
            return
        if not self.review.ready:
            self.statusBar().showMessage("Refresh before applying changes.")
            return
        plan = self.review.plan_for(device_key)
        network_plan = self.review.network_plan if device_key is None else None
        interface_plan = self.review.interface_plan if device_key is None else None
        network_ops = network_plan.operation_count if network_plan else 0
        cable_plan = self.review.cable_plan if device_key is None else None
        network_ops += interface_plan.operation_count if interface_plan else 0
        network_ops += cable_plan.operation_count if cable_plan else 0
        if plan is None or (not plan.operations and not network_ops):
            self.statusBar().showMessage(
                "This device has nothing selected to write."
                if device_key
                else "Nothing is selected to write."
            )
            return
        dry_run = self.dry_run_only.isChecked()
        dialog = ConfirmDialog(
            self.review,
            plan,
            dry_run=dry_run,
            single=device_key is not None,
            parent=self,
            network_plan=network_plan,
            interface_plan=interface_plan,
            cable_plan=cable_plan,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        overrides = self.review.overrides(plan)
        self.set_banner(
            "Running dry run..." if dry_run else "Writing changes to NetBox...",
            "accent",
        )
        self.write_runner.start(
            self.netbox.config,
            self.behavior,
            self.review.diff,
            plan,
            overrides["role"],
            overrides["site"],
            overrides["status"],
            overrides["type"],
            dry_run=dry_run,
            unifi_config=self.unifi.config,
            journal_path=self.journal_path,
            network_plan=network_plan,
            interface_plan=interface_plan,
            cable_plan=cable_plan,
        )
        self.update_check_action()

    def write_execution_finished(self, result: WriteExecutionReport) -> None:
        self.review.record_report(result)
        self.table_model.refresh_rows()
        self.network_model.refresh_rows()
        self.interface_model.refresh_rows()
        self.cable_model.refresh_rows()
        failed = sum(o.status == "failed" for o in result.outcomes)
        skipped = sum(o.status == "skipped" for o in result.outcomes)
        if result.status == "Error":
            tone = "danger"
        elif failed:
            tone = "danger"
        elif skipped and not result.dry_run:
            tone = "warning"
        else:
            tone = "success"
        written = any(o.status == "success" for o in result.outcomes)
        action = "refresh" if written and not result.dry_run else ""
        text = result.details
        if result.status == "Error" and result.detail_lines:
            text = result.detail_lines[0]
        elif action:
            text += " Refresh to compare with the updated NetBox."
        self.set_banner(text, tone, action)
        if self.detail.key:
            self.show_detail(self.detail.key)
        self.statusBar().showMessage(result.details)
        self.update_check_action()

    # -- clipboard and exports ---------------------------------------------------

    def show_history(self) -> None:
        try:
            runs = JournalStore(self.journal_path).recent()
        except (JournalStoreError, OSError) as error:
            self.statusBar().showMessage(f"Write history unavailable: {error}")
            return
        dialog = HistoryDialog(runs, self)
        dialog.exec()
        dialog.deleteLater()

    def copy_device_details(self, key: str) -> None:
        item = self.review.row(key)
        if item is None:
            return
        QApplication.clipboard().setText(device_summary(item))
        self.statusBar().showMessage("Device details copied.")

    def copy_summary(self) -> None:
        if self.last_result is None:
            self.statusBar().showMessage("Refresh first to copy a summary.")
            return
        counts = self.review.counts()
        when = humanize_timestamp(self.last_result.last_updated)
        lines = [
            f"unifi2netbox summary ({when})",
            f"New devices: {counts[CREATE]}",
            f"With changes: {counts[UPDATE]}",
            f"In sync: {counts[IN_SYNC]}",
            f"Need attention: {counts[ATTENTION]}",
            f"Only in NetBox: {counts[NETBOX_ONLY]}",
            f"Network changes: {self.review.network_changes()}",
            f"Interface changes: {self.review.interface_changes()}",
            f"Cable suggestions: {self.review.cable_changes()}",
            *self.last_result.detail_lines,
        ]
        QApplication.clipboard().setText("\n".join(lines))
        self.statusBar().showMessage("Summary copied.")

    def export_unifi_api_dump(self) -> None:
        result = self.last_result
        if result is None or not result.unifi_api_feedback:
            self.statusBar().showMessage("Refresh first; no UniFi API data to export.")
            return
        default_name = f"unifi-api-dump-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save UniFi API dump", default_name, "JSON files (*.json)"
        )
        if not filename:
            return
        payload = {
            "schema_version": 1,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "snapshot": {
                "captured_at": result.unifi_captured_at,
                "scope": result.unifi_scope,
                "source_version": result.unifi_version,
            },
            "api_feedback": list(result.unifi_api_feedback),
            "raw_devices": list(result.unifi_raw_devices),
        }
        self._write_json_dump(Path(filename), payload)

    def export_unifi_row_dump(self, device_key: str) -> None:
        source_id = _unifi_source_id_from_device_key(device_key)
        if not source_id:
            self.statusBar().showMessage("This device has no UniFi data to export.")
            return
        raw_devices = self.last_result.unifi_raw_devices if self.last_result else ()
        raw_row = _find_unifi_raw_device(raw_devices, source_id)
        if raw_row is None:
            self.statusBar().showMessage("No raw UniFi data found for this device.")
            return
        safe_id = "".join(ch for ch in source_id if ch.isalnum() or ch in "-_")
        default_name = (
            f"unifi-row-dump-{safe_id or 'device'}-"
            f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        )
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save UniFi device data", default_name, "JSON files (*.json)"
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
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.statusBar().showMessage(f"Saved {path}")

    # -- busy state and closing ------------------------------------------------

    def update_check_action(self) -> None:
        connections_busy = (
            self.netbox.runner.busy
            or self.unifi.runner.busy
            or self.protect.runner.busy
        )
        self.settings_action.setEnabled(not self.closing)
        self.check_action.setEnabled(not self.closing and not connections_busy)
        refresh_enabled = (
            not self.closing
            and not self.inventory_runner.busy
            and not self.write_runner.busy
            and not connections_busy
        )
        self.preview_action.setEnabled(refresh_enabled)
        self.refresh_button.setEnabled(refresh_enabled)
        self.refresh_button.setText(
            "Refreshing..." if self.inventory_runner.busy else "Refresh"
        )
        self.update_apply_bar()

    def finish_close(self) -> None:
        if self.closing and not (
            self.netbox.runner.busy
            or self.unifi.runner.busy
            or self.protect.runner.busy
            or self.inventory_runner.busy
            or self.write_runner.busy
        ):
            self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.closing = True
        self.netbox.stop_for_close()
        self.unifi.stop_for_close()
        self.protect.stop_for_close()
        self.update_check_action()
        if (
            self.netbox.runner.busy
            or self.unifi.runner.busy
            or self.protect.runner.busy
            or self.inventory_runner.busy
            or self.write_runner.busy
        ):
            event.ignore()
            return
        super().closeEvent(event)


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
