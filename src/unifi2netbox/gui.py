from dataclasses import asdict
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
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
    QMainWindow,
    QStyle,
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
    save_config,
    save_unifi_config,
)
from unifi2netbox.connections import Checker, ConnectionRunner, check_unifi_connection
from unifi2netbox.netbox import ConnectionResult, ConnectionState, check_connection


def plain_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class SettingsDialog(QDialog):
    def __init__(
        self,
        path: Path,
        config: NetBoxConfig,
        pool: QThreadPool,
        checker: Checker = check_connection,
        parent=None,
        *,
        unifi: bool = False,
        sites: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.is_unifi = unifi
        self.saved_config: NetBoxConfig | None = None
        self.close_pending = False
        self.runner = ConnectionRunner(pool, checker, self)
        self.runner.finished.connect(self.test_finished)
        self.setWindowTitle("UniFi Network Settings" if unifi else "NetBox Settings")
        self.resize(580, 420)
        self.setMinimumWidth(460)

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
        layout.addWidget(plain_label("Local token storage: plaintext"))
        layout.addWidget(plain_label(str(path)))
        self.outcome = plain_label()
        layout.addWidget(self.outcome)
        layout.addStretch()
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.test_button = self.buttons.addButton(
            "Test Connection", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.test_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.test_button.clicked.connect(self.test_connection)
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
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

    def save(self) -> None:
        try:
            config = self.config_from_fields()
            if isinstance(config, UniFiConfig):
                save_unifi_config(self.path, config)
            else:
                save_config(self.path, config)
        except ConfigError as error:
            self.outcome.setText(str(error))
            return
        self.saved_config = config
        self.accept()

    def set_busy(self, busy: bool) -> None:
        for widget in (
            self.url,
            self.token,
            self.show_token,
            self.verify_tls,
            self.ca_bundle,
            self.browse,
            self.timeout,
            self.buttons,
            self.site,
        ):
            widget.setEnabled(not busy)

    def test_connection(self) -> None:
        try:
            config = self.config_from_fields()
        except ConfigError as error:
            self.outcome.setText(str(error))
            return
        self.set_busy(True)
        self.outcome.setText("Checking...")
        self.runner.start(config)

    def test_finished(self, config: NetBoxConfig, result: ConnectionResult) -> None:
        self.set_busy(False)
        self.outcome.setText(f"{result.state}: {result.message}")
        if self.is_unifi:
            self.update_sites(result.sites, self.site_value())
        if self.close_pending:
            super().reject()

    def reject(self) -> None:
        if self.runner.busy:
            self.close_pending = True
            self.outcome.setText("Finishing the connection check before closing...")
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.runner.busy:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)


class ConnectionPanel(QWidget):
    idle = Signal()

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
        self.check_action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload),
            f"Check {name}",
            self,
        )
        self.check_action.setToolTip(f"Check {name} connection")
        self.check_action.triggered.connect(self.recheck)
        self.settings_action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView),
            f"{name} Settings",
            self,
        )
        self.settings_action.setToolTip(f"Edit {name} settings")
        self.settings_action.triggered.connect(self.open_settings)
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

    def open_settings(self) -> None:
        dialog = SettingsDialog(
            self.path,
            self.config,
            self.pool,
            self.checker,
            self,
            unifi=self.is_unifi,
            sites=self.site_choices,
        )
        if (
            dialog.exec() == QDialog.DialogCode.Accepted
            and dialog.saved_config is not None
        ):
            self.apply_config(dialog.saved_config)
        dialog.deleteLater()

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
        self.check_action.setEnabled(False)
        self.state.setText(ConnectionState.CHECKING)
        self.details.setText("Checking authenticated API access...")
        self.runner.start(self.config)

    def connection_finished(
        self, config: NetBoxConfig, result: ConnectionResult
    ) -> None:
        if self.closing:
            self.idle.emit()
            return
        if self.pending_check or config != self.config:
            self.recheck()
            return
        self.check_action.setEnabled(True)
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
        self.check_action.setEnabled(False)
        self.settings_action.setEnabled(False)
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
        self.closing = False
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
        self.check_action = self.netbox.check_action
        self.settings_action = self.netbox.settings_action
        toolbar = QToolBar("Connections")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        file_menu = self.menuBar().addMenu("File")
        for panel in (self.netbox, self.unifi):
            toolbar.addAction(panel.check_action)
            toolbar.addAction(panel.settings_action)
            file_menu.addAction(panel.settings_action)
            panel.idle.connect(self.finish_close)
            toolbar.addSeparator()
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
        self.netbox.open_settings()

    def apply_config(self, config: NetBoxConfig) -> None:
        self.netbox.apply_config(config)

    def recheck(self) -> None:
        self.netbox.recheck()

    def finish_close(self) -> None:
        if self.closing and not (self.netbox.runner.busy or self.unifi.runner.busy):
            self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.closing = True
        self.netbox.stop_for_close()
        self.unifi.stop_for_close()
        if self.netbox.runner.busy or self.unifi.runner.busy:
            event.ignore()
            return
        super().closeEvent(event)
