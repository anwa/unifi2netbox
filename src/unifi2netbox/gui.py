import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
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
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QFontMetrics,
    QIcon,
    QKeySequence,
)
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
    AccessConfig,
    BehaviorConfig,
    ConfigError,
    DeviceTypesConfig,
    DriveConfig,
    NetBoxConfig,
    ProtectConfig,
    UiConfig,
    UniFiConfig,
    load_access_config,
    load_behavior_config,
    load_config,
    load_device_types_config,
    load_drive_config,
    load_protect_config,
    load_ui_config,
    load_unifi_config,
    local_type_folder,
    save_connections,
    save_ui_config,
)
from unifi2netbox.connections import (
    Checker,
    ConnectionRunner,
    check_access_connection,
    check_drive_connection,
    check_protect_connection,
    check_unifi_connection,
)
from unifi2netbox.custom_fields import select_custom_field
from unifi2netbox.devicetypes import LocalTypeStore, load_yaml
from unifi2netbox.gui_devicetypes import DeviceTypeSettingsPage
from unifi2netbox.gui_jobs import TaskRunner
from unifi2netbox.gui_manual import ManualWindow
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
    ObjectTableModel,
    ReviewTableModel,
    banner,
    device_summary,
)
from unifi2netbox.gui_typeeditor import DeviceTypeEditor
from unifi2netbox.gui_typepicker import DeviceTypePicker
from unifi2netbox.inventory import InventoryDevice
from unifi2netbox.journal_store import JOURNAL_FILENAME, JournalStore, JournalStoreError
from unifi2netbox.library import (
    LibraryCache,
    cache_folder,
    fetch_text,
    refresh_index,
)
from unifi2netbox.library import client as library_client
from unifi2netbox.netbox import ConnectionResult, ConnectionState, check_connection
from unifi2netbox.netbox_catalog import NetBoxCatalog, read_catalog
from unifi2netbox.netbox_objects import CreateResult, create_object
from unifi2netbox.pipeline import (
    InventoryPreviewResult,
    WriteExecutionReport,
    build_inventory_preview,
    run_write_execution,
)
from unifi2netbox.preview import FIRMWARE, DifferencePreview
from unifi2netbox.review import (
    ADDRESSES,
    ALL,
    ATTENTION,
    CABLES,
    CATEGORY_LABELS,
    CREATE,
    IN_SYNC,
    INTERFACES,
    MODULES,
    NETBOX_ONLY,
    NETWORKS,
    OBJECT_FILTERS,
    UPDATE,
    WIRELESS,
    ReviewState,
    humanize_timestamp,
    single_operation_plan,
)
from unifi2netbox.typedraft import draft_from_unifi
from unifi2netbox.typesearch import (
    SOURCE_LABELS,
    TypeCandidate,
    from_document,
    library_candidates,
    local_candidates,
    netbox_candidates,
)
from unifi2netbox.window_frame import app_icon
from unifi2netbox.write_execute import RequestsNetBoxWriteBackend
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
        access_config: AccessConfig | None = None,
        drive_config: DriveConfig | None = None,
    ) -> None:
        super().__init__()
        self.access_config = access_config
        self.drive_config = drive_config
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
                access_config=self.access_config,
                drive_config=self.drive_config,
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
        protect_config=None,
        access_config=None,
        drive_config=None,
        disk_plan=None,
        custom_field_plan=None,
        mgmt_ip_plan=None,
        sfp_plan=None,
        site_detail_plan=None,
        type_import_plan=None,
    ) -> None:
        super().__init__()
        self.site_detail_plan = site_detail_plan
        self.type_import_plan = type_import_plan
        self.custom_field_plan = custom_field_plan
        self.mgmt_ip_plan = mgmt_ip_plan
        self.sfp_plan = sfp_plan
        self.access_config = access_config
        self.drive_config = drive_config
        self.disk_plan = disk_plan
        self.unifi_config = unifi_config
        self.journal_path = journal_path
        self.network_plan = network_plan
        self.interface_plan = interface_plan
        self.cable_plan = cable_plan
        self.protect_config = protect_config
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
                protect_config=self.protect_config,
                access_config=self.access_config,
                drive_config=self.drive_config,
                disk_plan=self.disk_plan,
                custom_field_plan=self.custom_field_plan,
                mgmt_ip_plan=self.mgmt_ip_plan,
                sfp_plan=self.sfp_plan,
                site_detail_plan=self.site_detail_plan,
                type_import_plan=self.type_import_plan,
            )
        except Exception as error:
            result = WriteExecutionReport(
                status="Error",
                details="Write execution failed unexpectedly.",
                detail_lines=(f"Write execution error: {error}",),
            )
        self.signals.finished.emit(result)


OBJECT_KEY_PREFIXES = (
    "mgmt-ip:",
    "sfp:",
    "sfp-item:",
    "wlan:",
    "range:",
    "reservation:",
)


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
        protect_config=None,
        access_config=None,
        drive_config=None,
        disk_plan=None,
        custom_field_plan=None,
        mgmt_ip_plan=None,
        sfp_plan=None,
        site_detail_plan=None,
        type_import_plan=None,
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
            protect_config=protect_config,
            access_config=access_config,
            drive_config=drive_config,
            disk_plan=disk_plan,
            custom_field_plan=custom_field_plan,
            mgmt_ip_plan=mgmt_ip_plan,
            sfp_plan=sfp_plan,
            site_detail_plan=site_detail_plan,
            type_import_plan=type_import_plan,
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
        access_config: AccessConfig | None = None,
        drive_config: DriveConfig | None = None,
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
            access_config,
            drive_config,
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


@dataclass(frozen=True)
class OptionalService:
    """Texts and config type of an optional UniFi application connection."""

    key: str
    name: str
    short: str
    description: str
    placeholder: str
    token_label: str
    details: str
    config_type: type
    loader: Callable[[Path], NetBoxConfig]


OPTIONAL_SERVICES = {
    "protect": OptionalService(
        "protect",
        "UniFi Protect",
        "Protect",
        "Optional. Console running UniFi Protect, for example a UNVR. Use a "
        "local integration API key created on that console. Protect is only "
        "read; recordings and streams are never accessed.",
        "https://unvr.example.lan",
        "Local API key",
        "Optional. Set the URL and local API key of the console running UniFi Protect.",
        ProtectConfig,
        load_protect_config,
    ),
    "access": OptionalService(
        "access",
        "UniFi Access",
        "Access",
        "Optional. UniFi Access API of the console running Access, with port "
        "12445. Create an API token in the Access app with device-read "
        "permission only. Only devices are read; users, logs and doors never.",
        "https://unifi.example.lan:12445",
        "API token",
        "Optional. Set the Access API URL (port 12445) and an Access API token.",
        AccessConfig,
        load_access_config,
    ),
    "drive": OptionalService(
        "drive",
        "UniFi Drive",
        "Drive",
        "Optional. Management address of your UNAS console and a local API key "
        "created on it. Ubiquiti documents no Drive device API yet; the app "
        "reads the public system information and, with the key, the drive bays "
        "(model, serial, size, state). File contents are never accessed.",
        "https://unas.example.lan",
        "Local API key",
        "Optional. Set the UNAS console URL and its local API key.",
        DriveConfig,
        load_drive_config,
    ),
}


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
        service: str = "",
        sites: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__(parent)
        self.service = OPTIONAL_SERVICES.get(service or ("protect" if protect else ""))
        self.is_unifi = unifi and self.service is None
        self.is_protect = self.service is not None and self.service.key == "protect"
        unifi = unifi or self.service is not None
        self.state = ConnectionState.UNCONFIGURED
        self.runner = ConnectionRunner(pool, checker, self)
        self.runner.finished.connect(self.test_finished)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        svc = self.service
        heading = svc.name if svc else "UniFi Network" if unifi else "NetBox"
        layout.addWidget(plain_label(heading, "heading"))
        layout.addWidget(
            plain_label(
                (
                    svc.description
                    if svc
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
            svc.placeholder
            if svc
            else "https://unifi.example.lan"
            if unifi
            else "https://netbox.example.lan"
        )
        self.token = QLineEdit(config.token)
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        token_label = (
            svc.token_label if svc else "Local API key" if unifi else "API token"
        )
        self.show_token = QCheckBox(
            "Show API key" if "key" in token_label else "Show token"
        )
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
        form.addRow(token_label, self.token)
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
        if self.service is not None:
            return self.service.config_type(**asdict(config))
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
    PAGES = (
        "NetBox",
        "UniFi Network",
        "UniFi Protect",
        "UniFi Access",
        "UniFi Drive",
        "Sync defaults",
        "Device types",
    )

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
        access_config: AccessConfig | None = None,
        access_checker: Checker = check_access_connection,
        drive_config: DriveConfig | None = None,
        drive_checker: Checker = check_drive_connection,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.saved_config: NetBoxConfig | None = None
        self.saved_unifi_config: UniFiConfig | None = None
        self.saved_protect_config: ProtectConfig | None = None
        self.saved_access_config: AccessConfig | None = None
        self.saved_drive_config: DriveConfig | None = None
        self.saved_behavior_config: BehaviorConfig | None = None
        self.saved_device_types_config: DeviceTypesConfig | None = None
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
        if access_config is None:
            try:
                access_config = load_access_config(path)
            except ConfigError:
                access_config = AccessConfig()
        self.access = ConnectionSettingsForm(
            access_config, pool, access_checker, service="access"
        )
        if drive_config is None:
            try:
                drive_config = load_drive_config(path)
            except ConfigError:
                drive_config = DriveConfig()
        self.drive = ConnectionSettingsForm(
            drive_config, pool, drive_checker, service="drive"
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

        try:
            device_types_config = load_device_types_config(path)
        except ConfigError:
            device_types_config = DeviceTypesConfig()
        self.device_types = DeviceTypeSettingsPage(device_types_config, path, pool)
        self.device_types.changed.connect(self.update_activity)

        self.nav = QListWidget()
        self.nav.setObjectName("settingsNav")
        self.nav.setFixedWidth(170)
        self.nav.addItems(list(self.PAGES))
        self.pages = QStackedWidget()
        for page in (
            self.netbox,
            self.unifi,
            self.protect,
            self.access,
            self.drive,
            sync_page,
            self.device_types,
        ):
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
        self.access.changed.connect(self.update_activity)
        self.drive.changed.connect(self.update_activity)

    def show_page(self, name: str) -> None:
        if name in self.PAGES:
            self.nav.setCurrentRow(self.PAGES.index(name))

    @property
    def busy(self) -> bool:
        return (
            self.netbox.runner.busy
            or self.unifi.runner.busy
            or self.protect.runner.busy
            or self.access.runner.busy
            or self.drive.runner.busy
            or self.device_types.busy
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
            access = self.access.config_from_fields()
            if not isinstance(access, AccessConfig):
                raise ConfigError("Access settings are invalid.")
            drive = self.drive.config_from_fields()
            if not isinstance(drive, DriveConfig):
                raise ConfigError("Drive settings are invalid.")
            behavior = BehaviorConfig(
                include_all_netbox_delete_candidates=(
                    self.include_all_netbox_delete_candidates.isChecked()
                ),
                default_device_role_name=self.default_device_role_name.text().strip(),
                netbox_site_name=self.netbox_site_name.text().strip(),
            )
            device_types = self.device_types.config_from_fields()
            save_connections(
                self.path,
                netbox,
                unifi,
                behavior,
                protect,
                access,
                drive,
                device_types,
            )
        except ConfigError as error:
            self.outcome.setText(str(error))
            return
        self.saved_config = netbox
        self.saved_unifi_config = unifi
        self.saved_protect_config = protect
        self.saved_access_config = access
        self.saved_drive_config = drive
        self.saved_behavior_config = behavior
        self.saved_device_types_config = device_types
        self.accept()

    def test_connections(self) -> None:
        if self.busy:
            return
        self.netbox.test_connection()
        self.unifi.test_connection()
        self.protect.test_connection()
        self.access.test_connection()
        self.drive.test_connection()
        self.update_activity()

    def update_activity(self) -> None:
        busy = self.busy
        self.pages.setEnabled(not busy)
        self.nav.setEnabled(not busy)
        self.buttons.setEnabled(not busy)
        self.outcome.setText(
            f"NetBox: {self.netbox.state}\nUniFi Network: {self.unifi.state}"
            f"\nUniFi Protect: {self.protect.state}"
            f"\nUniFi Access: {self.access.state}"
            f"\nUniFi Drive: {self.drive.state}"
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
        service: str = "",
    ) -> None:
        super().__init__()
        self.path = config_path
        self.pool = pool
        self.checker = checker
        self.service = OPTIONAL_SERVICES.get(service or ("protect" if protect else ""))
        self.is_unifi = unifi and self.service is None
        self.is_protect = self.service is not None and self.service.key == "protect"
        self.closing = False
        self.pending_check = False
        self.site_choices = ()
        svc = self.service
        self.name = svc.name if svc else "UniFi Network" if unifi else "NetBox"

        self.runner = ConnectionRunner(pool, checker, self)
        self.runner.finished.connect(self.connection_finished)
        self.config_error = ""
        try:
            self.config = (
                svc.loader(config_path)
                if svc
                else load_unifi_config(config_path)
                if unifi
                else load_config(config_path)
            )
        except ConfigError as error:
            self.config = (
                svc.config_type() if svc else UniFiConfig() if unifi else NetBoxConfig()
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
            svc.details
            if svc
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
        short = (
            self.service.short
            if self.service
            else "UniFi"
            if self.is_unifi
            else "NetBox"
        )
        state = self.current_state
        if state == ConnectionState.UNCONFIGURED:
            # Short chip text; the panel still shows the full state.
            return f"{short} · {'Off' if self.service is not None else 'Not set'}"
        version_text = self.server_version.text()
        if version_text in ("Not available", "Not checked"):
            version_text = ""
        if state == ConnectionState.ONLINE:
            # The UniFi site stays in the tooltip and detail card: five chips
            # must fit the header at the default window width.
            return f"{short} {version_text}".strip()
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
        # Compact chips show only the service name (state by color, details in
        # the tooltip) when the header is too narrow for the full text.
        self.compact = False
        self.full_width = 0
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
        summary = self.panel.summary()
        short = summary.split(" ", 1)[0]
        self.setText(f"●  {short if self.compact else summary}")
        # Optional services (Protect, Access) only take header space once set.
        self.setVisible(self.panel.service is None or self.panel.config.configured)
        self.updateGeometry()
        self.adjustSize()
        tip = self.panel.details.text()
        site = self.panel.selected_site.text() if self.panel.is_unifi else ""
        if site and site != "Not selected":
            tip = f"Site: {site}\n{tip}"
        if self.panel.config.security_warning:
            tip += f"\n{self.panel.config.security_warning}"
        if self.compact:
            tip = f"{summary}\n{tip}"
        self.setToolTip(tip)
        theme.set_variant(self, "chip", tone)
        # The style sheet draws the text bold, but the size hint is measured
        # with the regular font; reserve the bold width plus the pill padding
        # so the layout never squeezes the text (e.g. "UniFi 11.0.99 · Default").
        bold = self.font()
        bold.setBold(True)
        metrics = QFontMetrics(bold)
        text_width = metrics.horizontalAdvance(self.text())
        self.full_width = metrics.horizontalAdvance(f"●  {summary}") + 2 * 14 + 8
        self.setMinimumWidth(max(self.sizeHint().width(), text_width + 2 * 14 + 8))

    def set_compact(self, compact: bool) -> None:
        if compact != self.compact:
            self.compact = compact
            self.update_chip()

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
        access_checker: Checker = check_access_connection,
        drive_checker: Checker = check_drive_connection,
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
            self.device_types_config = load_device_types_config(config_path)
        except ConfigError:
            self.device_types_config = DeviceTypesConfig()
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
        self.access = ConnectionPanel(
            config_path, pool, access_checker, service="access"
        )
        self.drive = ConnectionPanel(config_path, pool, drive_checker, service="drive")
        self.setWindowTitle(f"unifi2netbox {version('unifi2netbox')}")
        self.resize(1180, 760)
        self.setMinimumSize(860, 560)
        self.manual_window: ManualWindow | None = None
        self.type_editor: DeviceTypeEditor | None = None
        # Create row waiting for a type saved in the editor (picker New).
        self.pending_type_key = ""
        self.type_download = TaskRunner(pool, self)
        self.type_download.finished.connect(self._type_downloaded)
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

        for panel in (self.netbox, self.unifi, self.protect, self.access, self.drive):
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
        self.manual_action = QAction(
            theme.icon("HelpContents", QStyle.StandardPixmap.SP_DialogHelpButton),
            "Manual",
            self,
        )
        self.manual_action.setShortcut(
            QKeySequence(QKeySequence.StandardKey.HelpContents)
        )
        self.manual_action.setToolTip("Open the user manual (F1)")
        self.manual_action.triggered.connect(lambda: self.show_manual())
        self.types_action = QAction(
            theme.icon(
                "x-office-document", QStyle.StandardPixmap.SP_FileDialogListView
            ),
            "Device types...",
            self,
        )
        self.types_action.setToolTip(
            "Edit device type definitions in the local type folder"
        )
        self.types_action.triggered.connect(lambda: self.show_type_editor())
        self.exit_action = QAction("Exit", self)
        self.exit_action.triggered.connect(self.close)
        for action in (self.preview_action, self.settings_action, self.manual_action):
            self.addAction(action)

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 10, 14, 10)
        layout.setSpacing(10)
        logo = QLabel()
        logo.setObjectName("appLogo")
        logo.setPixmap(app_icon().pixmap(28, 28))
        logo.setAccessibleName("unifi2netbox logo")
        layout.addWidget(logo)
        title = QLabel("unifi2netbox")
        title.setObjectName("appTitle")
        layout.addWidget(title)
        self.app_title = title
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
        self.access_chip = ConnectionChip(self.access, header)
        self.access_chip.setObjectName("accessChip")
        layout.addWidget(self.access_chip)
        self.drive_chip = ConnectionChip(self.drive, header)
        self.drive_chip.setObjectName("driveChip")
        layout.addWidget(self.drive_chip)
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
        self.manual_button = QPushButton("Manual")
        self.manual_button.setObjectName("manualButton")
        self.manual_button.setProperty("variant", "ghost")
        self.manual_button.setToolTip(self.manual_action.toolTip())
        self.manual_button.clicked.connect(self.manual_action.trigger)
        layout.addWidget(self.manual_button)
        self.types_button = QPushButton("Device types")
        self.types_button.setObjectName("typesButton")
        self.types_button.setProperty("variant", "ghost")
        self.types_button.setToolTip(self.types_action.toolTip())
        self.types_button.clicked.connect(self.types_action.trigger)
        layout.addWidget(self.types_button)
        self.header = header
        for chip in self._chips():
            chip.panel.status_changed.connect(self.update_header_mode)
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
        menu.addAction(self.types_action)
        menu.addAction(self.manual_action)
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
        try:
            # Keep the other [ui] values (for example the editor layout).
            self.ui = replace(load_ui_config(self.path), theme=choice)
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

        # Two rows so every segment keeps its full label at the default width:
        # device filters with the search field, then networks and objects.
        filters = QHBoxLayout()
        filters.setSpacing(4)
        object_filters = QHBoxLayout()
        object_filters.setSpacing(4)
        self.segments: dict[str, QPushButton] = {}
        for row, categories in (
            (filters, (ALL, CREATE, UPDATE, IN_SYNC, ATTENTION, NETBOX_ONLY)),
            (
                object_filters,
                (NETWORKS, INTERFACES, CABLES, ADDRESSES, WIRELESS, MODULES),
            ),
        ):
            for category in categories:
                button = QPushButton(CATEGORY_LABELS[category])
                button.setObjectName(f"filter_{category}")
                button.setCheckable(True)
                button.setProperty("segment", True)
                button.clicked.connect(
                    lambda _c=False, cat=category: self.set_filter(cat)
                )
                self.filter_group.addButton(button)
                self.segments[category] = button
                row.addWidget(button)
        filters.addStretch()
        object_filters.addStretch()
        self.search = QLineEdit()
        self.search.setObjectName("deviceSearch")
        self.search.setPlaceholderText("Filter by name, model, port, VLAN or subnet")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(lambda _t: self.apply_filter())
        filters.addWidget(self.search)
        layout.addLayout(filters)
        layout.addLayout(object_filters)

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
        self.object_model = ObjectTableModel(self)
        self.object_model.selection_changed.connect(self.on_selection_changed)
        self.object_table = QTableView()
        self.object_table.setObjectName("objectTable")
        self.object_table.setModel(self.object_model)
        self.object_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.object_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.object_table.setShowGrid(False)
        self.object_table.setWordWrap(False)
        self.object_table.verticalHeader().hide()
        self.object_table.verticalHeader().setDefaultSectionSize(38)
        self.object_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        object_badge = BadgeDelegate(self.object_table)
        self.object_table.setItemDelegateForColumn(3, object_badge)
        self.object_table.setItemDelegateForColumn(4, object_badge)
        object_header = self.object_table.horizontalHeader()
        object_header.setHighlightSections(False)
        object_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        object_header.resizeSection(0, 36)
        object_header.resizeSection(1, 120)
        object_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        object_header.resizeSection(3, 100)
        object_header.resizeSection(4, 130)
        self.object_table.selectionModel().currentRowChanged.connect(
            lambda current, _previous: self.show_detail(
                self.object_model.key_at(current.row())
            )
        )
        self.table_stack = QStackedWidget()
        self.table_stack.addWidget(self.table)
        self.table_stack.addWidget(self.object_table)
        self.table_stack.addWidget(self.network_table)
        self.table_stack.addWidget(self.interface_table)
        self.table_stack.addWidget(self.cable_table)

        self.detail = DetailPanel()
        self.detail.setObjectName("detailPanel")
        self.detail.changed.connect(self.on_detail_changed)
        self.detail.apply_requested.connect(self.execute_selected_preview_row)
        self.detail.export_requested.connect(self.export_unifi_row_dump)
        self.detail.copy_requested.connect(self.copy_device_details)
        self.detail.type_requested.connect(self.choose_device_type)
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
            or any(self.review.object_rows(name) for name in OBJECT_FILTERS)
        )
        self.pages.setCurrentIndex(1 if has_rows else 0)
        self.network_model.set_state(self.review)
        self.interface_model.set_state(self.review)
        self.cable_model.set_state(self.review)
        self.object_model.set_state(self.review)
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
        if self.current_filter() in OBJECT_FILTERS:
            self.apply_object_filter(keep_key)
            return
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

    def apply_object_filter(self, keep_key: str = "") -> None:
        category = self.current_filter()
        self.table_stack.setCurrentWidget(self.object_table)
        self.object_model.category = category
        self.object_model.set_filter(self.search.text())
        key = keep_key or self.detail.key
        row = self.object_model.row_of(key) if key else -1
        if row < 0 and self.object_model.rowCount() > 0:
            row = 0
        if row >= 0:
            self.object_table.selectionModel().setCurrentIndex(
                self.object_model.index(row, 2),
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )
            self.show_detail(self.object_model.key_at(row))
        else:
            empty = {
                ADDRESSES: "No management IPs, DHCP ranges or reservations.",
                WIRELESS: "UniFi reports no wireless LANs.",
                MODULES: "No SFP modules in ports of matched devices.",
            }[category]
            self.detail.show_placeholder(self.review.object_note(category) or empty)

    def show_detail(self, key: str) -> None:
        if key.startswith(OBJECT_KEY_PREFIXES):
            self.detail.show_object(self.review, key)
        elif key.startswith("network"):
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
        self.object_model.refresh_rows()
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
        disk_ops = self.review.disk_operation_count()
        field_ops = self.review.custom_field_operation_count()
        ip_ops = self.review.mgmt_ip_operation_count()
        sfp_ops = self.review.sfp_operation_count()
        detail_ops = self.review.site_detail_operation_count()
        type_ops = self.review.type_import_count()
        operations = (
            (len(plan.operations) if plan is not None else 0)
            + network_ops
            + interface_ops
            + cable_ops
            + disk_ops
            + field_ops
            + ip_ops
            + sfp_ops
            + detail_ops
            + type_ops
        )
        selectable = self.review.selectable_count()
        selected = self.review.selected_count()
        parts = []
        if field_ops:
            parts.append("1 Custom Field")
        if type_ops:
            parts.append(f"{type_ops} device type{'s' if type_ops != 1 else ''}")
        if selectable:
            parts.append(f"{selected} of {selectable} devices selected")
        if network_ops:
            parts.append(f"{network_ops} network writes")
        if interface_ops:
            parts.append(f"{interface_ops} interface writes")
        if cable_ops:
            parts.append(f"{cable_ops} cables")
        if ip_ops:
            parts.append(f"{ip_ops} management IPs")
        if sfp_ops:
            parts.append(f"{sfp_ops} SFP modules")
        if detail_ops:
            parts.append(f"{detail_ops} WLANs, ranges and reservations")
        self.selection_label.setText(", ".join(parts))
        for button in (self.select_all_button, self.select_none_button):
            button.setVisible(
                bool(
                    selectable
                    or self.review.network_rows()
                    or self.review.interface_rows()
                    or self.review.cable_rows()
                    or any(self.review.object_rows(n) for n in OBJECT_FILTERS)
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
        if self.current_filter() in OBJECT_FILTERS:
            for row in self.object_model.items:
                self.review.set_object_selected(row.key, selected)
            self.object_model.refresh_rows()
            self.on_selection_changed()
            return
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
            access_config=self.access.config,
            access_checker=self.access.checker,
            drive_config=self.drive.config,
            drive_checker=self.drive.checker,
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
            if dialog.saved_access_config is not None:
                self.access.apply_config(dialog.saved_access_config)
            if dialog.saved_drive_config is not None:
                self.drive.apply_config(dialog.saved_drive_config)
            if dialog.saved_behavior_config is not None:
                self.behavior = dialog.saved_behavior_config
                self.review.behavior = self.behavior
            if dialog.saved_device_types_config is not None:
                self.device_types_config = dialog.saved_device_types_config
            self.update_empty_state()
        dialog.deleteLater()

    def apply_config(self, config: NetBoxConfig) -> None:
        self.netbox.apply_config(config)

    def recheck(self) -> None:
        self.netbox.recheck()
        self.unifi.recheck()
        self.protect.recheck()
        self.access.recheck()
        self.drive.recheck()

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
            access_config=self.access.config,
            drive_config=self.drive.config,
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
        disk_plan = self.review.disk_plan if device_key is None else None
        network_ops += disk_plan.operation_count if disk_plan else 0
        custom_field_plan = self.review.custom_field_plan
        if (
            custom_field_plan is not None
            and device_key is not None
            and plan is not None
            and not any(FIRMWARE in op.selected_fields for op in plan.operations)
        ):
            # A single device without firmware must not create the field.
            custom_field_plan = select_custom_field(custom_field_plan, False)
        network_ops += custom_field_plan.operation_count if custom_field_plan else 0
        mgmt_ip_plan = self.review.mgmt_ip_plan_for(device_key)
        network_ops += mgmt_ip_plan.operation_count if mgmt_ip_plan else 0
        sfp_plan = self.review.sfp_plan if device_key is None else None
        network_ops += sfp_plan.operation_count if sfp_plan else 0
        site_detail_plan = self.review.site_detail_plan if device_key is None else None
        network_ops += site_detail_plan.operation_count if site_detail_plan else 0
        type_import_plan = self.review.type_import_plan(
            [device_key] if device_key is not None else None
        )
        network_ops += type_import_plan.operation_count
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
            disk_plan=disk_plan,
            custom_field_plan=custom_field_plan,
            mgmt_ip_plan=mgmt_ip_plan,
            sfp_plan=sfp_plan,
            site_detail_plan=site_detail_plan,
            type_import_plan=type_import_plan,
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
            protect_config=self.protect.config,
            access_config=self.access.config,
            drive_config=self.drive.config,
            disk_plan=disk_plan,
            custom_field_plan=custom_field_plan,
            mgmt_ip_plan=mgmt_ip_plan,
            sfp_plan=sfp_plan,
            site_detail_plan=site_detail_plan,
            type_import_plan=type_import_plan,
        )
        self.update_check_action()

    def write_execution_finished(self, result: WriteExecutionReport) -> None:
        self.review.record_report(result)
        self.table_model.refresh_rows()
        self.network_model.refresh_rows()
        self.interface_model.refresh_rows()
        self.cable_model.refresh_rows()
        self.object_model.refresh_rows()
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

    def show_manual(self, page: str = "") -> None:
        """Open (or raise) the manual window at a page or the overview."""
        if self.manual_window is None:
            self.manual_window = ManualWindow(self)
        if page:
            self.manual_window.show_page(page)
        self.manual_window.show()
        self.manual_window.raise_()
        self.manual_window.activateWindow()

    def _hook_editor(self, editor: DeviceTypeEditor) -> None:
        if not editor.property("typeSavedHooked"):
            editor.saved.connect(self._type_saved)
            editor.setProperty("typeSavedHooked", True)

    def _chips(self) -> tuple[ConnectionChip, ...]:
        return (
            self.netbox_chip,
            self.unifi_chip,
            self.protect_chip,
            self.access_chip,
            self.drive_chip,
        )

    def update_header_mode(self) -> None:
        """Compact chips and icon-only buttons when the header would not fit."""
        header = getattr(self, "header", None)
        if header is None or not self.isVisible():
            return  # decided once the window is shown (with its theme)
        chips = [chip for chip in self._chips() if chip.isVisibleTo(self)]
        current = sum(chip.minimumWidth() for chip in chips)
        full = sum(chip.full_width for chip in chips)
        buttons = (self.manual_button, self.types_button)
        button_now = sum(button.sizeHint().width() for button in buttons)
        button_full = sum(
            button.fontMetrics().horizontalAdvance(text) + 32
            for button, text in zip(buttons, ("Manual", "Device types"), strict=True)
        )
        title = self.app_title.sizeHint().width() if self.app_title.isHidden() else 0
        rest = header.minimumSizeHint().width() - current - button_now + title
        compact = rest + full + button_full > self.width()
        # The logo stays; the name gives way first on narrow windows.
        self.app_title.setVisible(not compact)
        for chip in chips:
            chip.set_compact(compact)
        for button, text, icon in (
            (self.manual_button, "Manual", self.manual_action.icon()),
            (self.types_button, "Device types", self.types_action.icon()),
        ):
            button.setText("" if compact else text)
            button.setIcon(icon if compact else QIcon())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self.update_header_mode()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self.update_header_mode()

    def type_store(self) -> LocalTypeStore:
        return LocalTypeStore(local_type_folder(self.device_types_config, self.path))

    def show_type_editor(self) -> DeviceTypeEditor:
        """Open (or raise) the device type editor for the local type folder."""
        store = self.type_store()
        editor = self.type_editor
        if editor is not None and (
            editor.store.root != store.root or editor.config != self.device_types_config
        ):
            if editor.dirty:
                editor.config = self.device_types_config
            else:
                editor.close()
                editor.deleteLater()
                editor = None
        if editor is None:
            editor = DeviceTypeEditor(
                store,
                self.device_types_config,
                self.pool,
                self,
                settings_path=self.path,
                catalog_loader=self.type_catalog,
                creator=self.create_netbox_object,
            )
            self.type_editor = editor
            self._hook_editor(editor)
        editor.show()
        editor.raise_()
        editor.activateWindow()
        return editor

    def type_catalog(self) -> NetBoxCatalog:
        """NetBox drop-down lists for the editor (runs on the thread pool)."""
        config = self.netbox.config
        if not config.configured:
            return NetBoxCatalog(errors=("NetBox is not configured.",))
        return read_catalog(config)

    def create_netbox_object(
        self, kind: str, values: dict, catalog: NetBoxCatalog
    ) -> CreateResult:
        """Create from a New dialog (its Create button is the approval)."""
        backend = RequestsNetBoxWriteBackend(self.netbox.config)
        return create_object(kind, values, catalog, backend, self.journal_path)

    # -- device type picker ---------------------------------------------------

    def type_candidates(self) -> tuple[list[TypeCandidate], str]:
        """NetBox, local and (when enabled) library candidates plus a note."""
        records = self.last_result.netbox_type_records if self.last_result else ()
        if records:
            candidates = netbox_candidates(records)
        else:
            candidates = [
                TypeCandidate("netbox", manufacturer, model, netbox_id=type_id)
                for type_id, manufacturer, model in self.review.device_types
            ]
        store = self.type_store()
        candidates += local_candidates(store.files(), store.read)
        note = ""
        if self.device_types_config.use_library:
            cache = LibraryCache(cache_folder(self.path))
            index = cache.load_index(self.device_types_config)
            candidates += library_candidates(index, cache)
        else:
            note = "The devicetype-library is switched off in Settings."
        return candidates, note

    def choose_device_type(self, key: str) -> None:
        item = self.review.row(key)
        if item is None:
            return
        candidates, note = self.type_candidates()
        config = self.device_types_config
        path = self.path

        def refresh():
            index = refresh_index(config, path)
            return library_candidates(index, LibraryCache(cache_folder(path)))

        picker = DeviceTypePicker(
            candidates,
            hint=item.source_value("model"),
            hint_manufacturer=item.source_value("manufacturer"),
            note=note,
            refresh_library=refresh if config.use_library else None,
            pool=self.pool,
            parent=self,
        )
        if picker.exec() == QDialog.DialogCode.Accepted:
            if picker.new_requested:
                self.new_device_type_for(key)
            elif picker.selected is not None:
                self.set_device_type_choice(key, picker.selected)
        picker.deleteLater()

    def set_device_type_choice(self, key: str, candidate: TypeCandidate) -> None:
        if candidate.source == "netbox":
            self._apply_type_choice(key, candidate.netbox_id)
            return
        value = f"{candidate.source}:{candidate.path}"
        name = candidate.model or candidate.part_number or candidate.path
        self.review.type_labels[value] = (
            f"{candidate.manufacturer} {name} "
            f"({SOURCE_LABELS[candidate.source].lower()}, imported on apply)"
        )
        if candidate.source == "local":
            try:
                self.review.import_docs[value] = self.type_store().read(
                    Path(candidate.path)
                )
            except Exception as error:  # noqa: BLE001 - shown to the user
                self.statusBar().showMessage(f"Cannot read the definition: {error}")
                return
            self._apply_type_choice(key, value)
            return
        entry = candidate.entry
        cache = LibraryCache(cache_folder(self.path))
        text = cache.cached_text(entry) if entry is not None else None
        if text is not None:
            self.review.import_docs[value] = load_yaml(text)
            self._apply_type_choice(key, value)
            return
        if entry is None or self.type_download.busy:
            return
        config = self.device_types_config

        def download():
            with library_client() as http:
                return fetch_text(config, entry, http, cache)

        self.statusBar().showMessage(f"Downloading {entry.path} from the library...")
        self._pending_download = (key, value)
        self.type_download.start(download)

    def _type_downloaded(self, result: object) -> None:
        key, value = getattr(self, "_pending_download", ("", ""))
        if isinstance(result, Exception) or not isinstance(result, str):
            self.statusBar().showMessage(f"Library file not downloaded: {result}")
            return
        try:
            self.review.import_docs[value] = load_yaml(result)
        except ValueError as error:
            self.statusBar().showMessage(f"The library file is invalid: {error}")
            return
        self.statusBar().showMessage("Library definition downloaded.")
        self._apply_type_choice(key, value)

    def _apply_type_choice(self, key: str, value: str) -> None:
        self.review.set_choice("type", key, value)
        self.on_detail_changed()
        self.show_detail(key)

    def new_device_type_for(self, key: str) -> None:
        """Open the editor with a draft from the create row's UniFi data."""
        item = self.review.row(key)
        if item is None:
            return
        unifi_id = _unifi_source_id_from_device_key(key)
        device = InventoryDevice(
            unifi_id,
            item.source_value("name") or item.name,
            serial=item.source_value("serial"),
            model=item.source_value("model"),
            manufacturer=item.source_value("manufacturer"),
        )
        ports = [p for p in self.review.unifi_ports if p.device_id == unifi_id]
        doc, notes = draft_from_unifi(device, ports)
        editor = self.show_type_editor()
        if not editor.open_new(doc, notes):
            return
        self.pending_type_key = key
        self._hook_editor(editor)
        if (
            self.device_types_config.use_techspecs
            and device.manufacturer.lower() == "ubiquiti"
        ):
            editor.look_up_specs()

    def _type_saved(self, path: Path) -> None:
        # Keep chosen local definitions current when they are edited.
        value = f"local:{path}"
        if value in self.review.import_docs:
            try:
                self.review.import_docs[value] = self.type_store().read(path)
            except Exception:  # noqa: BLE001 - the previous version stays
                pass
            self.on_detail_changed()
        key = self.pending_type_key
        if not key or self.review.row(key) is None:
            return
        store = self.type_store()
        try:
            doc = store.read(path)
        except Exception:  # noqa: BLE001 - keep the choice open if unreadable
            return
        self.pending_type_key = ""
        self.set_device_type_choice(key, from_document(doc, "local", str(path)))

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
            or self.access.runner.busy
            or self.drive.runner.busy
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
            or self.access.runner.busy
            or self.drive.runner.busy
            or self.inventory_runner.busy
            or self.write_runner.busy
        ):
            self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.closing = True
        self.netbox.stop_for_close()
        self.unifi.stop_for_close()
        self.protect.stop_for_close()
        self.access.stop_for_close()
        self.drive.stop_for_close()
        self.update_check_action()
        if (
            self.netbox.runner.busy
            or self.unifi.runner.busy
            or self.protect.runner.busy
            or self.access.runner.busy
            or self.drive.runner.busy
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
