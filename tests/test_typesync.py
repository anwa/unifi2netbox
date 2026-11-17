"""Sync dialogs of the device type editor (M14 slice 5)."""

import copy

from PySide6.QtCore import QThreadPool
from test_devicetype_update import BASE, changed_local, imported, netbox_view

from unifi2netbox.devicetype_import import build_import_plan, execute_import_plan
from unifi2netbox.devicetype_update import LOCAL, NETBOX, execute_sync
from unifi2netbox.gui_typesync import SyncAllDialog, SyncDialog, SyncTarget
from unifi2netbox.inventory import InventoryManufacturer
from unifi2netbox.netbox_types import compare
from unifi2netbox.type_preflight import preflight


class FakeSync:
    def __init__(self, backend):
        self.backend = backend
        self.runs = []

    def check(self, plan, types):
        return preflight(plan, types, self.backend)

    def run(self, plan, dry_run, types):
        self.runs.append(dry_run)
        return execute_sync(plan, self.backend, dry_run=dry_run, types=types)

    def import_type(self, doc, images, dry_run):
        plan = build_import_plan(
            {"k": "c"},
            {"c": doc},
            {"c": "x"},
            [InventoryManufacturer("41", "Ubiquiti")],
            (),
        )
        outcomes, _ = execute_import_plan(plan, self.backend, dry_run=dry_run)
        return outcomes[0]


def dialog_for(qtbot, local, backend, type_id):
    types = netbox_view(backend, type_id)
    sync = FakeSync(backend)
    dialog = SyncDialog(local, compare(local, types), types, sync, QThreadPool())
    qtbot.addWidget(dialog)
    confirmations = []
    dialog.confirm = lambda title, text: confirmations.append(text) or True
    return dialog, sync, confirmations


def test_sync_dialog_overwrites_by_default_and_reports(qtbot):
    backend, type_id = imported()
    local = changed_local()
    dialog, sync, confirmations = dialog_for(qtbot, local, backend, type_id)
    assert dialog.decisions()["field:weight"] == LOCAL
    assert dialog.decisions()["field:owner"] == "skip"
    owner = dialog.choices["field:owner"]
    assert [owner.itemData(i) for i in range(owner.count())] == [NETBOX, "skip"]

    with qtbot.waitSignal(dialog.synced, timeout=5000):
        dialog.apply()
    assert "Create interfaces: eth2" in confirmations[0]
    assert dialog.report.outcome.verification == "verified"
    assert "Read-back: verified" in dialog.message.text()
    assert sync.runs == [False]


def test_sync_dialog_per_value_and_dry_run(qtbot):
    backend, type_id = imported()
    local = changed_local()
    dialog, sync, _c = dialog_for(qtbot, local, backend, type_id)
    for key in dialog.choices:
        dialog.set_choice(key, "skip")
    dialog.set_choice("field:owner", NETBOX)
    dialog.dry_run.setChecked(True)
    with qtbot.waitSignal(dialog.synced, timeout=5000):
        dialog.apply()
    assert sync.runs == [True]
    assert dialog.report.outcome.status == "skipped"  # dry run: nothing written
    assert dialog.report.local_doc is None

    dialog.dry_run.setChecked(False)
    with qtbot.waitSignal(dialog.synced, timeout=5000):
        dialog.apply()
    assert dialog.report.local_doc["owner"] == "Network team"


def test_sync_dialog_shows_blockers_without_asking(qtbot):
    backend, type_id = imported()
    backend.seed("/api/dcim/racks/", 700, name="R1", u_height=1, starting_unit=1)
    backend.seed(
        "/api/dcim/devices/",
        710,
        name="box",
        rack={"id": 700},
        device_type={"id": int(type_id)},
        position=1,
        face="front",
    )
    local = copy.deepcopy(BASE)
    local["u_height"] = 2
    types = netbox_view(backend, type_id, devices=1)
    sync = FakeSync(backend)
    dialog = SyncDialog(local, compare(local, types), types, sync, QThreadPool())
    qtbot.addWidget(dialog)
    asked = []
    dialog.confirm = lambda *a: asked.append(a) or True
    with qtbot.waitSignal(dialog.runner.finished, timeout=5000):
        dialog.apply()
    assert not asked and "Blocked" in dialog.message.text()
    assert "would leave rack R1" in dialog.findings.item(0).text()


def test_sync_all_overwrites_differing_and_imports_missing(qtbot):
    backend, type_id = imported()
    types = netbox_view(backend, type_id)
    local = changed_local()
    new = copy.deepcopy(BASE)
    new["model"], new["slug"] = "New Box", "ubiquiti-new-box"
    for section in ("inventory-items", "port-mappings", "front-ports"):
        new.pop(section, None)
    targets = [
        SyncTarget(None, "Lab Box", "differs", local, compare(local, types), {}),
        SyncTarget(None, "New Box", "missing", new, compare(new, types), {}),
    ]
    dialog = SyncAllDialog(targets, types, FakeSync(backend), QThreadPool())
    qtbot.addWidget(dialog)
    dialog.confirm = lambda *a: True
    with qtbot.waitSignal(dialog.finished_all, timeout=10000) as blocker:
        dialog.apply()
    results = blocker.args[0]
    assert [o.status for _t, o in results] == ["success", "success"], [
        o.message for _t, o in results
    ]
    assert "2 of 2 type(s) synced" in dialog.message.text()
    assert backend.find_ids("/api/dcim/device-types/", slug="ubiquiti-new-box")
