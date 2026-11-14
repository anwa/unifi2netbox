"""Drive inventory-item plans and writes against a synthetic NetBox backend."""

import requests

from unifi2netbox.disk_execute import execute_disk_plan
from unifi2netbox.disks import (
    CONFLICT,
    CREATE,
    IN_SYNC,
    REFERENCE,
    UPDATE,
    build_disk_plan,
    describe,
    select_disk,
)
from unifi2netbox.inventory import InventoryDisk, InventoryItem
from unifi2netbox.write_execute import AmbiguousWriteError

UNAS = "drive:u1"
DISK1 = InventoryDisk(UNAS, "1", "WD80", "S1", "81.0", "HDD", 8 * 10**12, "optimal")
DISK2 = InventoryDisk(UNAS, "2", "WD80", "S2", "81.0", "HDD", 8 * 10**12, "optimal")
EMPTY = InventoryDisk(UNAS, "3", state="empty")


def plan(items=(), disks=(DISK1, DISK2, EMPTY), ids=None, **kwargs):
    return build_disk_plan(
        disks, {UNAS: "9"} if ids is None else ids, {UNAS: "NAS"}, items, **kwargs
    )


def test_description_holds_hardware_only():
    assert describe(DISK1) == "HDD 8.0 TB, firmware 81.0"
    assert describe(InventoryDisk(UNAS, "1", firmware="1.0")) == "firmware 1.0"
    assert describe(EMPTY) == ""


def test_plan_creates_updates_and_keeps_items():
    items = (
        InventoryItem("40", "9", "Disk 2", "WD80", "OLD", "HDD 8.0 TB, firmware 81.0"),
        InventoryItem("41", "9", "Disk 3", "X", "Y", ""),
        InventoryItem("50", "8", "Disk 1", "other device", "", ""),
    )

    rows = {row.disk.slot: row for row in plan(items).rows}

    assert rows["1"].action == CREATE and rows["1"].selected
    assert rows["1"].key == "disk:drive:u1:1" and rows["1"].label == "NAS Disk 1"
    assert rows["2"].action == UPDATE and rows["2"].selected
    assert rows["2"].changes() == (("serial", "OLD", "S2"),)
    assert "replaced" in rows["2"].notes[0]
    assert rows["3"].action == REFERENCE and not rows["3"].selectable
    assert "never deleted" in rows["3"].notes[0]


def test_equal_items_are_in_sync_and_empty_values_never_clear():
    same = InventoryItem("40", "9", "Disk 1", "WD80", "S1", describe(DISK1))
    no_serial = InventoryDisk(UNAS, "1", "WD80", "", "81.0", "HDD", 8 * 10**12)
    kept = InventoryItem("40", "9", "Disk 1", "WD80", "NB-SERIAL", describe(DISK1))

    assert plan((same,), disks=(DISK1,)).rows[0].action == IN_SYNC
    assert plan((kept,), disks=(no_serial,)).rows[0].action == IN_SYNC


def test_duplicate_names_conflict_and_unmatched_unas_blocks():
    items = (
        InventoryItem("40", "9", "Disk 1", "", "", ""),
        InventoryItem("41", "9", "Disk 1", "", "", ""),
    )

    (row,) = plan(items, disks=(DISK1,)).rows
    unmatched = plan(ids={})
    failed = plan(item_error="NetBox inventory items could not be read: denied")

    assert row.action == CONFLICT and not row.selectable
    assert unmatched.rows == () and "Create NAS in NetBox" in unmatched.blocker
    assert failed.rows == () and failed.blocker.startswith("NetBox inventory items")
    assert plan(disks=()).rows == ()


def test_selection_only_toggles_writable_rows():
    base = plan((InventoryItem("41", "9", "Disk 3", "X", "Y", ""),))

    off = select_disk(base, "disk:drive:u1:1", False)

    assert off.operation_count == base.operation_count - 1
    assert select_disk(base, "disk:drive:u1:3", True).operation_count == 2


class FakeNetBox:
    def __init__(self, items=None):
        self.items = dict(items or {})
        self.created = []
        self.updated = []
        self.fail = None
        self.apply_anyway = False

    def find_ids(self, path, **filters):
        assert path == "/api/dcim/inventory-items/"
        return tuple(
            key
            for key, item in self.items.items()
            if str(item["device"]) == str(filters["device_id"])
            and item["name"] == filters["name"]
        )

    def read_object(self, path):
        return self.items.get(path.rstrip("/").rsplit("/", 1)[-1])

    def create_object(self, path, payload):
        assert path == "/api/dcim/inventory-items/"
        if self.fail:
            if self.apply_anyway:
                self.items["77"] = dict(payload)
            raise self.fail
        self.created.append(payload)
        self.items["70"] = dict(payload)
        return "70"

    def update_object(self, path, payload):
        item_id = path.rstrip("/").rsplit("/", 1)[-1]
        self.updated.append((item_id, payload))
        self.items[item_id] = self.items[item_id] | payload


def fresh(*disks):
    return {(d.device_id, d.slot): d for d in disks}


def test_create_writes_hardware_fields_and_verifies():
    backend = FakeNetBox()

    (outcome,) = execute_disk_plan(
        plan(disks=(DISK1,)), backend, source_disks=fresh(DISK1)
    )

    assert (outcome.status, outcome.verification) == ("success", "verified")
    assert outcome.operation == "create_inventory_item"
    assert backend.created == [
        {
            "device": 9,
            "name": "Disk 1",
            "discovered": True,
            "part_id": "WD80",
            "serial": "S1",
            "description": "HDD 8.0 TB, firmware 81.0",
        }
    ]


def test_update_patches_only_changed_fields_and_skips_drift():
    item = {"device": 9, "name": "Disk 2", "part_id": "WD80", "serial": "OLD"}
    item["description"] = describe(DISK2)
    items = (InventoryItem("40", "9", "Disk 2", "WD80", "OLD", describe(DISK2)),)
    backend = FakeNetBox({"40": item})

    (outcome,) = execute_disk_plan(
        plan(items, disks=(DISK2,)), backend, source_disks=fresh(DISK2)
    )
    assert (outcome.status, outcome.verification) == ("success", "verified")
    assert backend.updated == [("40", {"serial": "S2"})]

    drifted = FakeNetBox({"40": item | {"serial": "CHANGED"}})
    (skipped,) = execute_disk_plan(plan(items, disks=(DISK2,)), drifted)
    assert skipped.status == "skipped" and "serial" in skipped.message
    assert drifted.updated == []


def test_writes_are_skipped_when_unifi_changed_or_unreadable():
    backend = FakeNetBox()
    swapped = InventoryDisk(UNAS, "1", "WD80", "NEW", "81.0", "HDD", 8 * 10**12)

    (changed,) = execute_disk_plan(
        plan(disks=(DISK1,)), backend, source_disks=fresh(swapped)
    )
    (gone,) = execute_disk_plan(plan(disks=(DISK1,)), backend, source_disks={})
    (error,) = execute_disk_plan(
        plan(disks=(DISK1,)), backend, source_error="UniFi timed out"
    )

    assert changed.status == gone.status == error.status == "skipped"
    assert "other hardware" in changed.message
    assert "UniFi timed out" in error.message
    assert backend.created == []


def test_create_never_duplicates_and_dry_run_writes_nothing():
    taken = FakeNetBox({"40": {"device": 9, "name": "Disk 1"}})
    (skipped,) = execute_disk_plan(plan(disks=(DISK1,)), taken)
    assert skipped.status == "skipped" and taken.created == []

    backend = FakeNetBox()
    (dry,) = execute_disk_plan(plan(disks=(DISK1,)), backend, dry_run=True)
    assert dry.status == "skipped" and "Dry-run" in dry.message
    assert backend.created == []


def test_interrupted_create_is_looked_up_not_retried():
    landed = FakeNetBox()
    landed.fail = AmbiguousWriteError("timeout")
    landed.apply_anyway = True
    (found,) = execute_disk_plan(plan(disks=(DISK1,)), landed)
    assert found.status == "success" and "now has it" in found.message
    assert found.object_id == "77"

    lost = FakeNetBox()
    lost.fail = requests.exceptions.ReadTimeout("slow")
    (failed,) = execute_disk_plan(plan(disks=(DISK1,)), lost)
    assert failed.status == "failed" and "before retrying" in failed.message
