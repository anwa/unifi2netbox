"""SFP modules as NetBox inventory items (M11 slice 5)."""

import requests

from unifi2netbox.details import InventorySfp
from unifi2netbox.interface_plan import DevicePair
from unifi2netbox.inventory import (
    InventoryInterface,
    InventoryItem,
    InventoryManufacturer,
    InventoryPort,
)
from unifi2netbox.sfp import (
    CONFLICT,
    CREATE,
    IN_SYNC,
    NOTE,
    REFERENCE,
    UPDATE,
    build_sfp_plan,
    describe,
    select_sfp,
    vendor_key,
)
from unifi2netbox.sfp_execute import execute_sfp_plan

PAIR = DevicePair("unifi_network:a->netbox:1", "sw-a", "a", "1")
PORTS = (
    InventoryPort("a", 1, "SFPPLUS", 10000),
    InventoryPort("a", 2, "SFPPLUS", 10000),
)
INTERFACES = (
    InventoryInterface("10", "1", "SFP+ 1", "10gbase-x-sfpp"),
    InventoryInterface("11", "1", "SFP+ 2", "10gbase-x-sfpp"),
)
MANUFACTURERS = (
    InventoryManufacturer("5", "Ubiquiti"),
    InventoryManufacturer("6", "Cisco"),
)
SFP1 = InventorySfp("a", 1, "UBNT", "UF-MM-10G", "S1", "10GBase-SR", "A1")
SFP2 = InventorySfp("a", 2, "H3C-OEM", "SFP-GE-LX", "S2", "1000LX")


def plan(sfps=(SFP1, SFP2), items=(), ports=PORTS, **kwargs):
    return build_sfp_plan(
        (PAIR,), sfps, ports, INTERFACES, items, MANUFACTURERS, **kwargs
    )


def test_vendor_names_match_netbox_manufacturers():
    assert vendor_key("UBNT") == vendor_key("Ubiquiti Inc.") == vendor_key("Ubiquiti")
    assert vendor_key("H3C-OEM") == "h3c"
    assert describe(SFP1) == "10GBase-SR, rev A1" and describe(SFP2) == "1000LX"


def test_new_modules_are_created_and_linked_to_the_interface():
    first, second = plan().rows

    assert first.action == CREATE and first.selected
    assert (
        first.name == "Transceiver SFP+ 1" and first.label == "sw-a Transceiver SFP+ 1"
    )
    assert dict(first.desired) == {
        "part_id": "UF-MM-10G",
        "serial": "S1",
        "description": "10GBase-SR, rev A1",
        "manufacturer": "5",
        "component_type": "dcim.interface",
        "component_id": "10",
    }
    assert dict(second.desired)["manufacturer"] == ""
    assert "No single NetBox manufacturer matches 'H3C-OEM'" in second.notes[0]


def test_update_in_sync_conflict_and_reference():
    synced = InventoryItem(
        "40",
        "1",
        "Transceiver SFP+ 1",
        "UF-MM-10G",
        "S1",
        "10GBase-SR, rev A1",
        "5",
        "dcim.interface",
        "10",
    )
    replaced = InventoryItem("41", "1", "Transceiver SFP+ 2", "OLD", "S-OLD", "")
    leftover = InventoryItem("42", "1", "Transceiver SFP+ 9", "X", "Y", "")
    rows = {row.name: row for row in plan(items=(synced, replaced, leftover)).rows}

    assert rows["Transceiver SFP+ 1"].action == IN_SYNC
    update = rows["Transceiver SFP+ 2"]
    assert update.action == UPDATE and update.selected
    assert [f for f, _, _ in update.changes()] == [
        "part_id",
        "serial",
        "description",
        "component_type",
        "component_id",
    ]
    assert "replaced" in update.notes[-1]
    assert rows["Transceiver SFP+ 9"].action == REFERENCE
    duplicates = (
        InventoryItem("43", "1", "Transceiver SFP+ 1", "", "", ""),
        InventoryItem("44", "1", "Transceiver SFP+ 1", "", "", ""),
    )
    assert plan(sfps=(SFP1,), items=duplicates).rows[0].action == CONFLICT


def test_unpaired_port_blocker_and_selection():
    (row,) = plan(sfps=(InventorySfp("a", 7, part="X"),)).rows
    assert row.action == NOTE and not row.selectable
    failed = plan(item_error="NetBox inventory items could not be read: denied")
    assert failed.rows == () and failed.blocker.startswith("NetBox inventory items")
    base = plan()
    assert select_sfp(base, base.rows[0].key, False).operation_count == 1


class FakeNetBox:
    def __init__(self, items=None):
        self.items = dict(items or {})
        self.created = []
        self.updated = []
        self.fail = None
        self.apply_anyway = False

    def find_ids(self, path, **filters):
        return tuple(
            key
            for key, item in self.items.items()
            if str(item["device"]) == str(filters["device_id"])
            and item["name"] == filters["name"]
        )

    def read_object(self, path):
        return self.items.get(path.rstrip("/").rsplit("/", 1)[-1])

    def create_object(self, path, payload):
        stored = dict(payload)
        if "manufacturer" in stored:
            stored["manufacturer"] = {"id": stored["manufacturer"]}
        if self.fail:
            if self.apply_anyway:
                self.items["77"] = stored
            raise self.fail
        self.created.append(payload)
        self.items["70"] = stored
        return "70"

    def update_object(self, path, payload):
        item_id = path.rstrip("/").rsplit("/", 1)[-1]
        self.updated.append((item_id, payload))
        self.items[item_id] = self.items[item_id] | payload


def fresh(*sfps):
    return {(s.device_id, s.port_idx): s for s in sfps}


def test_create_sends_ids_as_integers_and_verifies():
    backend = FakeNetBox()

    first, _ = execute_sfp_plan(plan(), backend, source_sfps=fresh(SFP1, SFP2))

    assert first.status == "success" and first.verification == "verified"
    payload = backend.created[0]
    assert payload["manufacturer"] == 5 and payload["component_id"] == 10
    assert payload["component_type"] == "dcim.interface" and payload["discovered"]


def test_changed_module_and_dry_run_skip():
    other = InventorySfp("a", 1, "UBNT", "UF-MM-10G", "S9")
    backend = FakeNetBox()

    moved, _ = execute_sfp_plan(plan(), backend, source_sfps=fresh(other, SFP2))
    dry = execute_sfp_plan(plan(), backend, dry_run=True)
    failed = execute_sfp_plan(plan(), backend, source_error="timeout")

    assert moved.status == "skipped" and "another module" in moved.message
    assert all(o.status == "skipped" for o in dry + failed)
    assert backend.created[1:] == []


def test_update_is_drift_checked_and_interrupted_create_reconciled():
    item = {
        "device": 1,
        "name": "Transceiver SFP+ 2",
        "part_id": "OLD",
        "serial": "S-OLD",
        "description": "",
    }
    backend = FakeNetBox({"41": item})
    replaced = InventoryItem("41", "1", "Transceiver SFP+ 2", "OLD", "S-OLD", "")
    (update,) = [
        r for r in plan(items=(replaced,)).selected_rows() if r.action == UPDATE
    ]

    backend.items["41"] = dict(item, serial="CHANGED")
    (skipped,) = execute_sfp_plan(
        select_sfp(plan(items=(replaced,)), "sfp:a:1", False), backend
    )
    assert skipped.status == "skipped" and "serial" in skipped.message

    backend = FakeNetBox()
    backend.fail = requests.exceptions.Timeout("timed out")
    backend.apply_anyway = True
    (created, _) = execute_sfp_plan(plan(), backend)
    assert created.status == "success" and "interrupted" in created.message
    assert update.key == "sfp:a:2"
