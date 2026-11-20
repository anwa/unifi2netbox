"""Backup and restore dialogs (M15 slice 4).

**Backup NetBox...** reads the configured NetBox into one JSON or YAML file
(name chosen by the user) with progress and cancel. **Restore NetBox...**
loads a backup, takes its own target (URL, token, TLS; prefilled from the
settings and never saved), the mode, the endpoints (and in update mode the
objects) to restore, checks with a dry run, asks for confirmation (typing
the host name for "replace", after an automatic backup of the target) and
runs with progress and cancel. Every run is saved to the write history.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from unifi2netbox.config import NetBoxConfig
from unifi2netbox.gui_jobs import TaskRunner
from unifi2netbox.journal_store import JournalStore, StoredOutcome, StoredRun
from unifi2netbox.netbox_backup import (
    Backup,
    BackupError,
    create_backup,
    default_name,
    read_backup,
    write_backup,
)
from unifi2netbox.netbox_restore import (
    CREATE,
    REPLACE,
    UPDATE,
    RestoreReport,
    restore,
)
from unifi2netbox.write_execute import RequestsNetBoxWriteBackend

FILE_FILTER = "JSON backup (*.json);;YAML backup (*.yaml *.yml)"
MODE_TEXT = {
    CREATE: "Create missing objects (existing ones stay unchanged)",
    UPDATE: "Create missing and update differing objects (backup values, also "
    "empty ones)",
    REPLACE: "Empty NetBox first, then restore (deletes the selected endpoints' "
    "objects)",
}


class _Progress(QObject):
    changed = Signal(int, int, str)  # done, total, text


def _label(text: str = "", role: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    if role:
        label.setProperty("role", role)
    return label


def save_restore_run(path: Path | None, report: RestoreReport, label: str) -> None:
    """One write-history run with one outcome per restored endpoint."""
    if path is None:
        return
    now = datetime.now(UTC).isoformat(timespec="seconds")
    outcomes = tuple(
        StoredOutcome(
            device_key=f"restore:{endpoint}",
            label=f"{label}: {endpoint}",
            operation_type="restore_netbox",
            status="failed" if result.failed else "success",
            message=(
                f"{result.deleted} deleted, {result.create} created, "
                f"{result.update} updated, {result.equal} equal, "
                f"{result.failed} failed"
            ),
            netbox_object_id="",
            verification=report.verification,
        )
        for endpoint, result in report.endpoints.items()
        if result.writes or result.failed
    )
    if not outcomes:
        return
    try:
        JournalStore(path).save(
            StoredRun(str(uuid.uuid4()), now, now, report.dry_run, outcomes)
        )
    except Exception:  # noqa: BLE001 - history is best effort here
        pass


class BackupDialog(QDialog):
    """Back up the configured NetBox into a file."""

    def __init__(
        self,
        config: NetBoxConfig,
        pool: QThreadPool,
        parent: QWidget | None = None,
        folder: Path | None = None,
        backup_fn: Callable = create_backup,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("backupDialog")
        self.setWindowTitle("Backup NetBox")
        self.resize(640, 360)
        self.config = config
        self.backup_fn = backup_fn
        self.result: Backup | None = None
        self.cancel_event = threading.Event()
        self.progress_signal = _Progress()
        self.progress_signal.changed.connect(self._progress)
        self.runner = TaskRunner(pool, self)
        self.runner.finished.connect(self._finished)
        layout = QVBoxLayout(self)
        layout.addWidget(
            _label(
                f"Reads all data of {config.url or 'the configured NetBox'} into one "
                "file: devices, device types, IPAM, circuits, tenancy, "
                "virtualization, VPN, wireless, tags, custom fields, owners and "
                "images. Never users, tokens, permissions, secrets or the change "
                "log. NetBox is only read."
            )
        )
        row = QHBoxLayout()
        self.path_edit = QLineEdit(str((folder or Path.home()) / default_name(config)))
        self.path_edit.setObjectName("backupPath")
        choose = QPushButton("Choose...")
        choose.clicked.connect(self.choose)
        row.addWidget(self.path_edit, 1)
        row.addWidget(choose)
        layout.addLayout(row)
        self.images = QCheckBox("Include images (device type images, attachments)")
        self.images.setObjectName("backupImages")
        self.images.setChecked(True)
        layout.addWidget(self.images)
        self.bar = QProgressBar()
        self.bar.setObjectName("backupProgress")
        layout.addWidget(self.bar)
        self.message = _label()
        self.message.setObjectName("backupMessage")
        layout.addWidget(self.message, 1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setEnabled(False)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        self.start_button = QPushButton("Back up")
        self.start_button.setObjectName("backupStart")
        self.start_button.setProperty("variant", "primary")
        self.start_button.clicked.connect(self.start)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(close)
        buttons.addWidget(self.start_button)
        layout.addLayout(buttons)

    def choose(self) -> None:
        name, _ = QFileDialog.getSaveFileName(
            self, "Save the backup", self.path_edit.text(), FILE_FILTER
        )
        if name:
            self.path_edit.setText(name)

    def start(self) -> None:
        path = Path(self.path_edit.text().strip())
        if not path.name:
            self.message.setText("Choose a file.")
            return
        self.cancel_event.clear()
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.message.setText("Reading NetBox...")
        config, images, signal = (
            self.config,
            self.images.isChecked(),
            self.progress_signal,
        )
        backup_fn, cancel = self.backup_fn, self.cancel_event

        def task():
            backup = backup_fn(
                config,
                include_files=images,
                progress=lambda p: signal.changed.emit(p.done, p.total, p.endpoint),
                cancelled=cancel.is_set,
            )
            write_backup(backup, path)
            return backup, path

        self.runner.start(task)

    def cancel(self) -> None:
        self.cancel_event.set()
        self.message.setText("Cancelling...")

    def _progress(self, done: int, total: int, text: str) -> None:
        self.bar.setMaximum(max(total, 1))
        self.bar.setValue(done)
        self.message.setText(f"Read {text} ({done} of {total})")

    def _finished(self, result: object) -> None:
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if isinstance(result, Exception):
            self.message.setText(f"No backup written: {result}")
            return
        backup, path = result
        self.result = backup
        size = path.stat().st_size / 1_000_000
        text = (
            f"Saved {backup.total()} objects of {len(backup.counts())} endpoints and "
            f"{len(backup.data['files'])} images to {path} ({size:.1f} MB)."
        )
        if backup.data["omitted"]:
            text += f" Left out (secrets): {', '.join(backup.data['omitted'])}."
        if not backup.complete:
            text += " INCOMPLETE: " + "; ".join(backup.data["errors"][:5])
        self.message.setText(text)


class RestoreDialog(QDialog):
    """Restore a backup into a target NetBox chosen here."""

    def __init__(
        self,
        config: NetBoxConfig,
        pool: QThreadPool,
        parent: QWidget | None = None,
        journal_path: Path | None = None,
        backend_factory: Callable = RequestsNetBoxWriteBackend,
        backup_fn: Callable = create_backup,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("restoreDialog")
        self.setWindowTitle("Restore NetBox")
        self.resize(900, 720)
        self.base_config = config
        self.journal_path = journal_path
        self.backend_factory = backend_factory
        self.backup_fn = backup_fn
        self.backup: Backup | None = None
        self.backup_path: Path | None = None
        self.check_report: RestoreReport | None = None
        self.checked_with: tuple | None = None
        self.report: RestoreReport | None = None
        self.cancel_event = threading.Event()
        self.confirm_host: Callable[[str, str], str | None] = self._ask_host
        self.confirm: Callable[[str], bool] = self._ask
        self.progress_signal = _Progress()
        self.progress_signal.changed.connect(self._progress)
        self.runner = TaskRunner(pool, self)
        self.runner.finished.connect(self._finished)
        self._phase = ""
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setObjectName("restoreFile")
        self.file_edit.setPlaceholderText("Backup file (.json or .yaml)")
        choose = QPushButton("Choose...")
        choose.clicked.connect(self.choose)
        load = QPushButton("Load")
        load.clicked.connect(lambda: self.load(Path(self.file_edit.text().strip())))
        row.addWidget(self.file_edit, 1)
        row.addWidget(choose)
        row.addWidget(load)
        layout.addLayout(row)
        self.summary = _label("", "secondary")
        self.summary.setObjectName("restoreSummary")
        layout.addWidget(self.summary)
        form = QFormLayout()
        self.url = QLineEdit(config.url)
        self.url.setObjectName("restoreUrl")
        self.token = QLineEdit(config.token)
        self.token.setObjectName("restoreToken")
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.verify = QCheckBox("Verify TLS certificate")
        self.verify.setChecked(config.verify_tls)
        form.addRow("Target NetBox URL", self.url)
        form.addRow("API token", self.token)
        form.addRow("", self.verify)
        layout.addLayout(form)
        layout.addWidget(
            _label(
                "The target is used for this restore only and is not saved.",
                "caption",
            )
        )
        self.modes = QButtonGroup(self)
        for mode in (CREATE, UPDATE, REPLACE):
            button = QRadioButton(MODE_TEXT[mode])
            button.setObjectName(f"restoreMode_{mode}")
            button.setProperty("mode", mode)
            self.modes.addButton(button)
            layout.addWidget(button)
            if mode == CREATE:
                button.setChecked(True)
        self.tree = QTreeWidget()
        self.tree.setObjectName("restoreEndpoints")
        self.tree.setHeaderLabels(["Endpoint", "Objects"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.tree, 2)
        self.results = QTableWidget(0, 7)
        self.results.setObjectName("restoreResults")
        self.results.setHorizontalHeaderLabels(
            [
                "Endpoint",
                "Delete",
                "Create",
                "Update",
                "Equal",
                "Not matchable",
                "Failed",
            ]
        )
        self.results.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.results.verticalHeader().hide()
        layout.addWidget(self.results, 2)
        self.changes = QTreeWidget()
        self.changes.setObjectName("restoreChanges")
        self.changes.setHeaderLabels(["Object to update", "Fields"])
        self.changes.setVisible(False)
        layout.addWidget(self.changes, 1)
        self.bar = QProgressBar()
        layout.addWidget(self.bar)
        self.message = _label()
        self.message.setObjectName("restoreMessage")
        layout.addWidget(self.message)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        self.check_button = QPushButton("Check (dry run)")
        self.check_button.setObjectName("restoreCheck")
        self.check_button.clicked.connect(self.check)
        self.restore_button = QPushButton("Restore")
        self.restore_button.setObjectName("restoreRun")
        self.restore_button.setProperty("variant", "primary")
        self.restore_button.setEnabled(False)
        self.restore_button.clicked.connect(self.run)
        for button in (
            self.cancel_button,
            close,
            self.check_button,
            self.restore_button,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        for widget in (self.url, self.token):
            widget.textChanged.connect(self._invalidate)
        self.verify.toggled.connect(self._invalidate)
        self.modes.buttonToggled.connect(lambda *_a: self._invalidate())
        self.tree.itemChanged.connect(lambda *_a: self._invalidate())

    # -- inputs ---------------------------------------------------------------

    def choose(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "Open a backup", "", FILE_FILTER)
        if name:
            self.file_edit.setText(name)
            self.load(Path(name))

    def load(self, path: Path) -> None:
        try:
            backup = read_backup(path)
        except (BackupError, OSError) as error:
            self.summary.setText(f"Not loaded: {error}")
            return
        self.backup, self.backup_path = backup, path
        self.file_edit.setText(str(path))
        data = backup.data
        apps: dict[str, int] = {}
        for endpoint, count in backup.counts().items():
            apps[endpoint.split("/")[0]] = apps.get(endpoint.split("/")[0], 0) + count
        text = (
            f"Backup of {data.get('source')} (NetBox {data.get('netbox_version')}) "
            f"from {data.get('created')}: {backup.total()} objects, "
            f"{len(data.get('files', ()))} images. "
            + ", ".join(f"{app} {n}" for app, n in sorted(apps.items()))
        )
        if not data.get("complete", True):
            text += " The backup is INCOMPLETE."
        self.summary.setText(text)
        self.tree.blockSignals(True)
        self.tree.clear()
        nodes: dict[str, QTreeWidgetItem] = {}
        for endpoint, count in sorted(backup.counts().items()):
            app = endpoint.split("/")[0]
            if app not in nodes:
                node = QTreeWidgetItem([app, ""])
                node.setFlags(
                    node.flags()
                    | Qt.ItemFlag.ItemIsAutoTristate
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                node.setCheckState(0, Qt.CheckState.Checked)
                self.tree.addTopLevelItem(node)
                nodes[app] = node
            child = QTreeWidgetItem([endpoint, str(count)])
            child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            child.setCheckState(0, Qt.CheckState.Checked)
            child.setData(0, Qt.ItemDataRole.UserRole, endpoint)
            nodes[app].addChild(child)
        self.tree.blockSignals(False)
        self._invalidate()

    def target(self) -> NetBoxConfig:
        return replace(
            self.base_config,
            url=self.url.text().strip(),
            token=self.token.text().strip(),
            verify_tls=self.verify.isChecked(),
        )

    def mode(self) -> str:
        button = self.modes.checkedButton()
        return button.property("mode") if button else CREATE

    def selection(self) -> list[str]:
        result = []
        for index in range(self.tree.topLevelItemCount()):
            node = self.tree.topLevelItem(index)
            for child_index in range(node.childCount()):
                child = node.child(child_index)
                if child.checkState(0) == Qt.CheckState.Checked:
                    result.append(child.data(0, Qt.ItemDataRole.UserRole))
        return result

    def skipped(self) -> list[tuple[str, int]]:
        result = []
        for index in range(self.changes.topLevelItemCount()):
            node = self.changes.topLevelItem(index)
            for child_index in range(node.childCount()):
                child = node.child(child_index)
                if child.checkState(0) != Qt.CheckState.Checked:
                    result.append(child.data(0, Qt.ItemDataRole.UserRole))
        return result

    def _state(self) -> tuple:
        target = self.target()
        return (
            target.url,
            target.token,
            target.verify_tls,
            self.mode(),
            tuple(self.selection()),
        )

    def _invalidate(self) -> None:
        if self.checked_with is not None and self.checked_with != self._state():
            self.restore_button.setEnabled(False)
            self.message.setText("Settings changed: check again before restoring.")

    # -- check and run -----------------------------------------------------------

    def check(self) -> None:
        if self.backup is None:
            self.message.setText("Load a backup first.")
            return
        target = self.target()
        if not target.configured:
            self.message.setText("Enter the target URL and token.")
            return
        backup, mode, selection = self.backup, self.mode(), self.selection()
        factory, signal = self.backend_factory, self.progress_signal
        self.cancel_event.clear()
        cancel = self.cancel_event
        self._busy(True, "Checking the target (dry run, nothing is written)...")
        self.checked_with = self._state()

        def task():
            return restore(
                backup,
                factory(target),
                mode=mode,
                selection=selection,
                dry_run=True,
                progress=lambda e, i, n: signal.changed.emit(i, n, e),
                cancelled=cancel.is_set,
            )

        self._phase = "check"
        self.runner.start(task)

    def run(self) -> None:
        if self.check_report is None or self.checked_with != self._state():
            self.message.setText("Check again before restoring.")
            return
        target, mode = self.target(), self.mode()
        report = self.check_report
        host = urlparse(target.url).netloc
        lines = [
            f"Target: {target.url}",
            f"Mode: {MODE_TEXT[mode]}",
            report.summary(),
        ]
        auto_backup = None
        if mode == REPLACE:
            auto_backup = self._auto_backup_path(host)
            lines.append(
                f"First the target is backed up to {auto_backup}, then "
                f"{report.total('deleted')} objects are deleted."
            )
            typed = self.confirm_host("\n".join(lines), host)
            if typed != host:
                self.message.setText("Not restored: the host name did not match.")
                return
        elif not self.confirm("\n".join(lines) + "\n\nRestore now?"):
            self.message.setText("Not restored.")
            return
        backup, selection, skipped = self.backup, self.selection(), self.skipped()
        factory, signal, backup_fn = (
            self.backend_factory,
            self.progress_signal,
            self.backup_fn,
        )
        counts = dict(report.counts_before)
        self.cancel_event.clear()
        cancel = self.cancel_event
        self._busy(True, "Restoring...")

        def task():
            if auto_backup is not None:
                write_backup(backup_fn(target, include_files=True), auto_backup)
            return restore(
                backup,
                factory(target),
                mode=mode,
                selection=selection,
                skip=skipped,
                dry_run=False,
                progress=lambda e, i, n: signal.changed.emit(i, n, e),
                cancelled=cancel.is_set,
                expected_counts=counts,
            )

        self._phase = "run"
        self.runner.start(task)

    def _auto_backup_path(self, host: str) -> Path:
        folder = self.backup_path.parent if self.backup_path else Path.home()
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        safe = host.replace(":", "-")
        return folder / f"netbox-backup-{safe}-before-restore-{stamp}.json"

    def cancel(self) -> None:
        self.cancel_event.set()
        self.message.setText("Cancelling after the current step...")

    def _busy(self, busy: bool, text: str = "") -> None:
        self.check_button.setEnabled(not busy)
        self.restore_button.setEnabled(False)
        self.cancel_button.setEnabled(busy)
        if text:
            self.message.setText(text)

    def _progress(self, done: int, total: int, text: str) -> None:
        self.bar.setMaximum(max(total, 1))
        self.bar.setValue(done)

    def _finished(self, result: object) -> None:
        phase, self._phase = self._phase, ""
        self._busy(False)
        if isinstance(result, Exception):
            self.message.setText(f"Failed: {result}")
            return
        self.bar.setValue(self.bar.maximum())
        self._show(result)
        if phase == "check":
            self.check_report = result
            blocked = bool(result.errors) and not result.endpoints
            self.restore_button.setEnabled(
                not blocked and self.checked_with == self._state()
            )
            self.message.setText(
                f"Check: {result.summary()}"
                + (
                    f" {len(result.errors)} problem(s): {result.errors[0]}"
                    if result.errors
                    else ""
                )
            )
        else:
            self.report = result
            save_restore_run(
                self.journal_path, result, f"Restore into {self.target().url}"
            )
            self.message.setText(
                f"Restore: {result.summary()} Read-back: {result.verification or '-'}. "
                + (
                    f"{len(result.errors)} problem(s): {result.errors[0]}"
                    if result.errors
                    else ""
                )
            )
            self.check_report = None
            self.checked_with = None

    def _show(self, report: RestoreReport) -> None:
        rows = [
            r
            for r in report.endpoints.values()
            if r.writes or r.equal or r.unmatched or r.failed
        ]
        self.results.setRowCount(len(rows))
        for index, result in enumerate(rows):
            values = [
                result.endpoint,
                result.deleted,
                result.create,
                result.update,
                result.equal,
                result.unmatched,
                result.failed,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.results.setItem(index, column, item)
        self.changes.clear()
        changed = [r for r in rows if r.changes]
        self.changes.setVisible(bool(changed) and report.dry_run)
        for result in changed:
            node = QTreeWidgetItem([result.endpoint, f"{len(result.changes)} objects"])
            self.changes.addTopLevelItem(node)
            for old_id, label, fields in result.changes:
                child = QTreeWidgetItem([label, ", ".join(fields)])
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Checked)
                child.setData(
                    0, Qt.ItemDataRole.UserRole, (result.endpoint, int(old_id))
                )
                node.addChild(child)
        self.changes.expandAll()

    def _ask(self, text: str) -> bool:
        answer = QMessageBox.question(self, "Restore NetBox", text)
        return answer == QMessageBox.StandardButton.Yes

    def _ask_host(self, text: str, host: str) -> str | None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Empty NetBox and restore")
        layout = QVBoxLayout(dialog)
        layout.addWidget(_label(text))
        layout.addWidget(_label(f"Type the host name {host} to continue."))
        edit = QLineEdit()
        layout.addWidget(edit)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dialog.reject)
        ok = QPushButton("Empty and restore")
        ok.setProperty("variant", "danger")
        ok.clicked.connect(dialog.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        layout.addLayout(buttons)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return edit.text().strip() if accepted else None
