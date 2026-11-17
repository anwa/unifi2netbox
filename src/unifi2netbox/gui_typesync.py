"""Sync dialogs of the device type editor (M14 slice 5).

``SyncDialog`` syncs one definition with its NetBox type: one row per
difference with the choice **Local**, **NetBox** or **Skip** (like the
review's per-row choices); **Overwrite NetBox** selects Local wherever
possible. **Apply** checks in the background (drift-free preflight), shows
blockers or asks to confirm the steps and warnings, then runs the sync
(optionally as a dry run). ``SyncAllDialog`` does the same for all checked
yellow (overwrite) and red (import) definitions in two phases: check all,
confirm once, run all.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from unifi2netbox import theme
from unifi2netbox.devicetype_update import (
    CHOICE_LABELS,
    LOCAL,
    NETBOX,
    SKIP,
    SyncPlan,
    SyncReport,
    build_sync_plan,
    overwrite_decisions,
    sync_items,
)
from unifi2netbox.gui_jobs import TaskRunner
from unifi2netbox.gui_typediff import netbox_text
from unifi2netbox.netbox_types import NetBoxTypes, TypeComparison
from unifi2netbox.type_preflight import BLOCKER, Finding


class TypeSync(Protocol):
    """NetBox access for syncs, provided by the main window (thread pool)."""

    def check(self, plan: SyncPlan, types: NetBoxTypes) -> tuple[Finding, ...]: ...

    def run(self, plan: SyncPlan, dry_run: bool, types: NetBoxTypes) -> SyncReport: ...

    def import_type(self, doc, images: dict, dry_run: bool): ...  # NetworkOutcome


def _confirm(parent: QWidget, title: str, text: str) -> bool:
    answer = QMessageBox.question(parent, title, text)
    return answer == QMessageBox.StandardButton.Yes


def _finding_item(finding: Finding) -> QListWidgetItem:
    item = QListWidgetItem(str(finding))
    item.setForeground(
        theme.tone_qcolor("danger" if finding.level == BLOCKER else "warning")
    )
    return item


class SyncDialog(QDialog):
    """Sync one definition with its NetBox type."""

    synced = Signal(object)  # SyncReport

    def __init__(
        self,
        local,
        comparison: TypeComparison,
        types: NetBoxTypes,
        sync: TypeSync,
        pool: QThreadPool,
        images: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("syncDialog")
        self.setWindowTitle("Sync with NetBox")
        self.resize(860, 560)
        self.local = local
        self.comparison = comparison
        self.types = types
        self.sync = sync
        self.images = images or {}
        self.items = sync_items(comparison)
        self.plan: SyncPlan | None = None
        self.report: SyncReport | None = None
        self.confirm: Callable[[str, str], bool] = lambda t, x: _confirm(self, t, x)
        self.runner = TaskRunner(pool, self)
        self.runner.finished.connect(self._finished)
        self._phase = ""
        layout = QVBoxLayout(self)
        found = comparison.netbox
        intro = QLabel(
            f"{local.get('manufacturer') or ''} {local.get('model') or ''}: NetBox "
            f"device type {found.id if found else '?'}, used by "
            f"{found.device_count if found else 0} device(s). "
            "Local writes the file's value to NetBox, NetBox takes NetBox's value "
            "into the file. Values missing in the file are never cleared in "
            "NetBox, and templates only in NetBox are never deleted. Existing "
            "devices keep their components."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        modes = QHBoxLayout()
        overwrite = QPushButton("Overwrite NetBox")
        overwrite.setObjectName("syncOverwrite")
        overwrite.setToolTip("Choose Local wherever possible")
        overwrite.clicked.connect(self.overwrite)
        take = QPushButton("Take all from NetBox")
        take.setObjectName("syncTakeNetBox")
        take.clicked.connect(lambda: self._set_all(NETBOX))
        modes.addWidget(overwrite)
        modes.addWidget(take)
        modes.addStretch()
        layout.addLayout(modes)
        self.table = QTableWidget(len(self.items), 4)
        self.table.setObjectName("syncItems")
        self.table.setHorizontalHeaderLabels(["Difference", "Local", "NetBox", "Use"])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.choices: dict[str, QComboBox] = {}
        for row, item in enumerate(self.items):
            title = QTableWidgetItem(item.title)
            title.setToolTip(item.detail)
            local_text = (
                netbox_text(item.local)
                if item.section is None
                else ("in the file" if item.kind != "netbox-only" else "-")
            )
            netbox_value = (
                netbox_text(item.netbox)
                if item.section is None
                else ("in NetBox" if item.kind != "local-only" else "-")
            )
            if item.columns:
                local_text = netbox_value = ", ".join(item.columns)
            for column, text in ((0, title), (1, local_text), (2, netbox_value)):
                cell = (
                    text
                    if isinstance(text, QTableWidgetItem)
                    else (QTableWidgetItem(text))
                )
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column:
                    cell.setToolTip(item.detail or text)
                self.table.setItem(row, column, cell)
            combo = QComboBox()
            combo.setObjectName(f"syncChoice_{row}")
            for choice in item.choices:
                combo.addItem(CHOICE_LABELS[choice], choice)
            self.choices[item.key] = combo
            self.table.setCellWidget(row, 3, combo)
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table, 1)
        self.findings = QListWidget()
        self.findings.setObjectName("syncFindings")
        self.findings.setMaximumHeight(120)
        layout.addWidget(self.findings)
        self.message = QLabel("")
        self.message.setObjectName("syncMessage")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        buttons = QHBoxLayout()
        self.dry_run = QCheckBox("Dry run (check only, write nothing)")
        self.dry_run.setObjectName("syncDryRun")
        buttons.addWidget(self.dry_run)
        buttons.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        self.apply_button = QPushButton("Apply")
        self.apply_button.setObjectName("syncApply")
        self.apply_button.setProperty("variant", "primary")
        self.apply_button.clicked.connect(self.apply)
        buttons.addWidget(close)
        buttons.addWidget(self.apply_button)
        layout.addLayout(buttons)
        self.overwrite()

    def decisions(self) -> dict[str, str]:
        return {key: combo.currentData() for key, combo in self.choices.items()}

    def set_choice(self, key: str, choice: str) -> None:
        combo = self.choices[key]
        index = combo.findData(choice)
        if index >= 0:
            combo.setCurrentIndex(index)

    def overwrite(self) -> None:
        for key, choice in overwrite_decisions(self.items).items():
            self.set_choice(key, choice)

    def _set_all(self, choice: str) -> None:
        for item in self.items:
            self.set_choice(item.key, choice if choice in item.choices else SKIP)

    def apply(self) -> None:
        self.plan = build_sync_plan(
            self.local, self.comparison, self.decisions(), self.images
        )
        if not self.plan.netbox_steps and not self.plan.local_changed:
            self.message.setText("Nothing is selected.")
            return
        self.apply_button.setEnabled(False)
        self.findings.clear()
        self.message.setText("Checking NetBox...")
        plan, types, sync = self.plan, self.types, self.sync
        self._phase = "check"
        self.runner.start(lambda: sync.check(plan, types))

    def _finished(self, result: object) -> None:
        phase, self._phase = self._phase, ""
        self.apply_button.setEnabled(True)
        if isinstance(result, Exception):
            self.message.setText(f"Failed: {result}")
            return
        if phase == "check":
            self._checked(tuple(result))
        elif isinstance(result, SyncReport):
            self._done(result)

    def _checked(self, findings: tuple[Finding, ...]) -> None:
        for finding in findings:
            self.findings.addItem(_finding_item(finding))
        if any(f.level == BLOCKER for f in findings):
            self.message.setText("Blocked; see above. Nothing was written.")
            return
        plan = self.plan
        dry = self.dry_run.isChecked()
        lines = plan.describe()
        warnings = [f.message for f in findings]
        text = "\n".join(f"- {line}" for line in lines)
        if warnings:
            text += "\n\nWarnings:\n" + "\n".join(f"- {w}" for w in warnings)
        title = "Dry run" if dry else "Sync with NetBox"
        if not self.confirm(title, f"{text}\n\nContinue?"):
            self.message.setText("Not synced.")
            return
        self.apply_button.setEnabled(False)
        self.message.setText("Syncing..." if not dry else "Checking (dry run)...")
        sync, types = self.sync, self.types
        self._phase = "run"
        self.runner.start(lambda: sync.run(plan, dry, types))

    def _done(self, report: SyncReport) -> None:
        self.report = report
        for finding in report.findings:
            if not any(
                self.findings.item(i).text() == str(finding)
                for i in range(self.findings.count())
            ):
                self.findings.addItem(_finding_item(finding))
        outcome = report.outcome
        text = f"{outcome.status.capitalize()}: {outcome.message}"
        if outcome.verification:
            text += f" Read-back: {outcome.verification}."
        if outcome.verification_detail:
            text += f" {outcome.verification_detail}"
        self.message.setText(text)
        self.synced.emit(report)


@dataclass
class SyncTarget:
    path: Path
    label: str
    status: str  # differs or missing
    doc: object
    comparison: TypeComparison
    images: dict


class SyncAllDialog(QDialog):
    """Overwrite NetBox for differing types and import missing ones."""

    finished_all = Signal(object)  # list of (SyncTarget, NetworkOutcome)

    def __init__(
        self,
        targets: Sequence[SyncTarget],
        types: NetBoxTypes,
        sync: TypeSync,
        pool: QThreadPool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("syncAllDialog")
        self.setWindowTitle("Sync all with NetBox")
        self.resize(760, 520)
        self.targets = list(targets)
        self.types = types
        self.sync = sync
        self.confirm: Callable[[str, str], bool] = lambda t, x: _confirm(self, t, x)
        self.runner = TaskRunner(pool, self)
        self.runner.finished.connect(self._finished)
        self._phase = ""
        self._checked_plans: list = []
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Yellow types overwrite NetBox with the local values (missing values "
            "are never cleared, NetBox-only templates never deleted); red types "
            "are imported. To decide per value, use Sync with NetBox on one type."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.list = QListWidget()
        self.list.setObjectName("syncAllList")
        for target in self.targets:
            action = "overwrite NetBox" if target.status == "differs" else "import"
            item = QListWidgetItem(f"{target.label}: {action}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setToolTip(target.comparison.summary())
            item.setForeground(
                theme.tone_qcolor("warning" if target.status == "differs" else "danger")
            )
            self.list.addItem(item)
        layout.addWidget(self.list, 1)
        self.findings = QListWidget()
        self.findings.setObjectName("syncAllFindings")
        self.findings.setMaximumHeight(140)
        layout.addWidget(self.findings)
        self.message = QLabel("")
        self.message.setObjectName("syncAllMessage")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        buttons = QHBoxLayout()
        self.dry_run = QCheckBox("Dry run (check only, write nothing)")
        self.dry_run.setObjectName("syncAllDryRun")
        buttons.addWidget(self.dry_run)
        buttons.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        self.apply_button = QPushButton("Apply")
        self.apply_button.setObjectName("syncAllApply")
        self.apply_button.setProperty("variant", "primary")
        self.apply_button.clicked.connect(self.apply)
        buttons.addWidget(close)
        buttons.addWidget(self.apply_button)
        layout.addLayout(buttons)

    def selected(self) -> list[SyncTarget]:
        return [
            target
            for index, target in enumerate(self.targets)
            if self.list.item(index).checkState() == Qt.CheckState.Checked
        ]

    def apply(self) -> None:
        targets = self.selected()
        if not targets:
            self.message.setText("Nothing is selected.")
            return
        self.apply_button.setEnabled(False)
        self.findings.clear()
        self.message.setText("Checking NetBox...")
        sync, types = self.sync, self.types

        def check():
            result = []
            for target in targets:
                if target.status != "differs":
                    result.append((target, None, ()))
                    continue
                plan = build_sync_plan(
                    target.doc,
                    target.comparison,
                    overwrite_decisions(sync_items(target.comparison)),
                    target.images,
                )
                result.append((target, plan, sync.check(plan, types)))
            return result

        self._phase = "check"
        self.runner.start(check)

    def _finished(self, result: object) -> None:
        phase, self._phase = self._phase, ""
        self.apply_button.setEnabled(True)
        if isinstance(result, Exception):
            self.message.setText(f"Failed: {result}")
            return
        if phase == "check":
            self._checked(result)
        else:
            self._done(result)

    def _checked(self, checked) -> None:
        runnable, lines = [], []
        for target, plan, findings in checked:
            for finding in findings:
                item = _finding_item(finding)
                item.setText(f"{target.label}: {finding}")
                self.findings.addItem(item)
            if any(f.level == BLOCKER for f in findings):
                lines.append(f"- {target.label}: blocked, skipped")
                continue
            if plan is not None and not plan.netbox_steps:
                continue
            runnable.append((target, plan))
            steps = "import" if plan is None else f"{plan.netbox_steps} step(s)"
            warn = sum(1 for f in findings if f.level != BLOCKER)
            lines.append(
                f"- {target.label}: {steps}" + (f", {warn} warning(s)" if warn else "")
            )
        if not runnable:
            self.message.setText("Nothing to sync.")
            return
        dry = self.dry_run.isChecked()
        if not self.confirm(
            "Dry run" if dry else "Sync all with NetBox",
            "\n".join(lines) + "\n\nContinue?",
        ):
            self.message.setText("Not synced.")
            return
        self.apply_button.setEnabled(False)
        self.message.setText("Syncing...")
        sync, types = self.sync, self.types

        def run():
            results = []
            for target, plan in runnable:
                if plan is None:
                    results.append(
                        (target, sync.import_type(target.doc, target.images, dry))
                    )
                else:
                    results.append((target, sync.run(plan, dry, types).outcome))
            return results

        self._phase = "run"
        self.runner.start(run)

    def _done(self, results) -> None:
        ok = sum(1 for _t, o in results if o.status == "success")
        for target, outcome in results:
            item = QListWidgetItem(
                f"{target.label}: {outcome.status}: {outcome.message}"
                + (f" ({outcome.verification})" if outcome.verification else "")
            )
            tone = "success" if outcome.status == "success" else "warning"
            item.setForeground(theme.tone_qcolor(tone))
            self.findings.addItem(item)
        self.message.setText(f"{ok} of {len(results)} type(s) synced.")
        self.finished_all.emit(results)


__all__ = ["LOCAL", "SyncAllDialog", "SyncDialog", "SyncTarget", "TypeSync"]
