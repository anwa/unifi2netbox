from datetime import datetime
from importlib.metadata import version
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
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

from unifi2netbox.config import ConfigError, NetBoxConfig, load_config, save_config
from unifi2netbox.connections import Checker, ConnectionRunner
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
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.saved_config: NetBoxConfig | None = None
        self.close_pending = False
        self.runner = ConnectionRunner(pool, checker, self)
        self.runner.finished.connect(self.test_finished)
        self.setWindowTitle("NetBox Settings")
        self.resize(580, 420)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.url = QLineEdit(config.url)
        self.url.setPlaceholderText("https://netbox.example.invalid")
        self.token = QLineEdit(config.token)
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.show_token = QCheckBox("Show token")
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
        form.addRow("API token", self.token)
        form.addRow("", self.show_token)
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
        return NetBoxConfig(
            url=self.url.text().strip().rstrip("/"),
            token=self.token.text().strip(),
            verify_tls=self.verify_tls.isChecked(),
            ca_bundle=self.ca_bundle.text().strip(),
            timeout=self.timeout.value(),
        )

    def save(self) -> None:
        try:
            config = self.config_from_fields()
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


class MainWindow(QMainWindow):
    def __init__(
        self,
        config_path: Path,
        pool: QThreadPool,
        checker: Checker = check_connection,
        *,
        open_first_run: bool = True,
    ) -> None:
        super().__init__()
        self.path = config_path
        self.pool = pool
        self.checker = checker
        self.closing = False
        self.pending_check = False
        self.runner = ConnectionRunner(pool, checker, self)
        self.runner.finished.connect(self.connection_finished)
        self.config_error = ""
        try:
            self.config = load_config(config_path)
        except ConfigError as error:
            self.config = NetBoxConfig()
            self.config_error = str(error)

        self.setWindowTitle(f"unifi2netbox {version('unifi2netbox')}")
        self.resize(800, 460)
        self.setMinimumSize(580, 360)
        toolbar = QToolBar("Connections")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.check_action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload),
            "Check Connection",
            self,
        )
        self.check_action.setToolTip("Check NetBox connection")
        self.check_action.triggered.connect(self.recheck)
        self.settings_action = QAction(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView),
            "Settings",
            self,
        )
        self.settings_action.setToolTip("Edit NetBox settings")
        self.settings_action.triggered.connect(self.open_settings)
        toolbar.addAction(self.check_action)
        toolbar.addAction(self.settings_action)
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self.settings_action)
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
        grid = QGridLayout()
        self.state = plain_label(ConnectionState.UNCONFIGURED)
        font = self.state.font()
        font.setBold(True)
        self.state.setFont(font)
        self.endpoint = plain_label()
        self.server_version = plain_label("Not checked")
        self.checked_at = plain_label("Not checked")
        grid.addWidget(plain_label("NetBox"), 0, 0)
        grid.addWidget(self.state, 0, 1)
        grid.addWidget(plain_label("Endpoint"), 1, 0)
        grid.addWidget(self.endpoint, 1, 1)
        grid.addWidget(plain_label("Server version"), 2, 0)
        grid.addWidget(self.server_version, 2, 1)
        grid.addWidget(plain_label("Last check"), 3, 0)
        grid.addWidget(self.checked_at, 3, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        self.details = plain_label("Set a NetBox URL and API token.")
        self.warning = plain_label()
        layout.addSpacing(12)
        layout.addWidget(self.details)
        layout.addWidget(self.warning)
        layout.addStretch()
        self.setCentralWidget(central)
        self.statusBar().showMessage(f"Configuration: {config_path}")
        self.update_config_display()
        if self.config_error:
            self.show_result(ConnectionResult(ConnectionState.ERROR, self.config_error))
        elif self.config.configured:
            QTimer.singleShot(0, self.recheck)
        elif open_first_run:
            QTimer.singleShot(0, self.open_settings)

    def update_config_display(self) -> None:
        self.endpoint.setText(self.config.url or "Not configured")
        self.warning.setText(self.config.security_warning)

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.path, self.config, self.pool, self.checker, self)
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
            self.close()
            return
        if self.pending_check or config != self.config:
            self.recheck()
            return
        self.check_action.setEnabled(True)
        self.show_result(result)

    def show_result(self, result: ConnectionResult) -> None:
        self.state.setText(result.state)
        self.details.setText(result.message)
        self.server_version.setText(result.version or "Not available")
        self.checked_at.setText(
            datetime.now().astimezone().isoformat(timespec="seconds")
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.runner.busy:
            self.closing = True
            self.check_action.setEnabled(False)
            self.settings_action.setEnabled(False)
            self.details.setText("Finishing the connection check before closing...")
            event.ignore()
            return
        super().closeEvent(event)
