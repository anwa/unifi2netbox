from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from unifi2netbox.access import check_access_connection as _check_access
from unifi2netbox.config import (
    AccessConfig,
    DriveConfig,
    NetBoxConfig,
    ProtectConfig,
    UniFiConfig,
)
from unifi2netbox.drive import check_drive_connection as _check_drive
from unifi2netbox.netbox import ConnectionResult, ConnectionState, check_connection
from unifi2netbox.protect import check_protect_connection as _check_protect
from unifi2netbox.unifi import check_connection as check_network_connection

type Checker = Callable[[NetBoxConfig], ConnectionResult]


def check_unifi_connection(config: NetBoxConfig) -> ConnectionResult:
    if not isinstance(config, UniFiConfig):
        raise TypeError("UniFi checks require UniFi connection settings.")
    return check_network_connection(config)


def check_protect_connection(config: NetBoxConfig) -> ConnectionResult:
    if not isinstance(config, ProtectConfig):
        raise TypeError("Protect checks require Protect connection settings.")
    return _check_protect(config)


def check_access_connection(config: NetBoxConfig) -> ConnectionResult:
    if not isinstance(config, AccessConfig):
        raise TypeError("Access checks require Access connection settings.")
    return _check_access(config)


def check_drive_connection(config: NetBoxConfig) -> ConnectionResult:
    if not isinstance(config, DriveConfig):
        raise TypeError("Drive checks require Drive connection settings.")
    return _check_drive(config)


class JobSignals(QObject):
    finished = Signal(object, object)


class ConnectionJob(QRunnable):
    def __init__(self, config: NetBoxConfig, checker: Checker) -> None:
        super().__init__()
        self.config = config
        self.checker = checker
        self.signals = JobSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.checker(self.config)
        except Exception:
            result = ConnectionResult(
                ConnectionState.ERROR, "Connection check failed unexpectedly."
            )
        self.signals.finished.emit(self.config, result)


class ConnectionRunner(QObject):
    finished = Signal(object, object)

    def __init__(
        self, pool: QThreadPool, checker: Checker = check_connection, parent=None
    ) -> None:
        super().__init__(parent)
        self.pool = pool
        self.checker = checker
        self.job: ConnectionJob | None = None

    @property
    def busy(self) -> bool:
        return self.job is not None

    def start(self, config: NetBoxConfig) -> bool:
        if self.busy:
            return False
        self.job = ConnectionJob(config, self.checker)
        self.job.signals.finished.connect(self._finished)
        self.pool.start(self.job)
        return True

    @Slot(object, object)
    def _finished(self, config: NetBoxConfig, result: ConnectionResult) -> None:
        self.job = None
        self.finished.emit(config, result)
