"""Interface configuration writes against a synthetic NetBox backend."""

import requests

from unifi2netbox.interface_execute import execute_interface_plan, read_field
from unifi2netbox.interface_plan import (
    MODE,
    TAGGED_VLANS,
    UNTAGGED,
    DevicePair,
    build_interface_plan,
    select_interface,
)
from unifi2netbox.inventory import InventoryInterface, InventoryPort, InventoryVlan
from unifi2netbox.port_config import InventoryPortConfig

CONFIG = InventoryPortConfig("a", 1, "Uplink", True, "tagged", 1, (20,))


class FakeNetBox:
    def __init__(self, interface):
        self.rows = {"/api/dcim/interfaces/10/": interface}
        self.updates = []
        self.fail = None
        self.ignore = False

    def read_object(self, path):
        return self.rows.get(path)

    def update_object(self, path, payload):
        if self.fail:
            raise self.fail
        self.updates.append((path, payload))
        if self.ignore:
            return
        row = dict(self.rows[path])
        for key, value in payload.items():
            if key == "mode":
                row[key] = {"value": value} if value else None
            elif key == "untagged_vlan":
                row[key] = {"id": value} if value else None
            elif key == "tagged_vlans":
                row[key] = [{"id": item} for item in value]
            else:
                row[key] = value
        self.rows[path] = row

    def find_ids(self, path, **filters):
        return ()

    def create_object(self, path, payload):
        raise AssertionError("interfaces are never created")


def netbox_row():
    return {
        "id": 10,
        "enabled": True,
        "mode": None,
        "untagged_vlan": None,
        "tagged_vlans": [],
    }


def make_plan():
    return build_interface_plan(
        (DevicePair("u->n", "sw-a", "a", "1"),),
        (InventoryPort("a", 1, "RJ45", 1000),),
        (InventoryInterface("10", "1", "Port 1", "1000base-t"),),
        (CONFIG,),
        (InventoryVlan("101", 1, "Default", "9"), InventoryVlan("120", 20, "IoT", "9")),
        vlan_group_id="9",
        vlan_group_name="UniFi Home",
    )


def test_selected_fields_are_patched_and_verified():
    backend = FakeNetBox(netbox_row())

    (outcome,) = execute_interface_plan(
        make_plan(), backend, source_configs={("a", 1): CONFIG}
    )

    assert backend.updates == [
        (
            "/api/dcim/interfaces/10/",
            {"mode": "tagged", "untagged_vlan": 101, "tagged_vlans": [120]},
        )
    ]
    assert (outcome.status, outcome.verification) == ("success", "verified")
    assert outcome.operation == "update_interface" and outcome.label == "sw-a Port 1"


def test_second_run_after_refresh_has_nothing_to_write():
    backend = FakeNetBox(netbox_row())
    execute_interface_plan(make_plan(), backend)
    row = backend.rows["/api/dcim/interfaces/10/"]
    refreshed = build_interface_plan(
        (DevicePair("u->n", "sw-a", "a", "1"),),
        (InventoryPort("a", 1, "RJ45", 1000),),
        (
            InventoryInterface(
                "10",
                "1",
                "Port 1",
                "1000base-t",
                mode=read_field(row, MODE),
                untagged_vlan_id=read_field(row, UNTAGGED),
                tagged_vlan_ids=read_field(row, TAGGED_VLANS),
            ),
        ),
        (CONFIG,),
        (InventoryVlan("101", 1, "Default", "9"), InventoryVlan("120", 20, "IoT", "9")),
        vlan_group_id="9",
        vlan_group_name="UniFi Home",
    )

    assert refreshed.rows[0].in_sync
    assert execute_interface_plan(refreshed, backend) == ()


def test_only_selected_fields_are_sent():
    plan = select_interface(make_plan(), "interface:10", TAGGED_VLANS, False)
    plan = select_interface(plan, "interface:10", UNTAGGED, False)
    backend = FakeNetBox(netbox_row())

    execute_interface_plan(plan, backend)

    assert backend.updates[0][1] == {"mode": "tagged"}


def test_dry_run_checks_but_does_not_write():
    backend = FakeNetBox(netbox_row())

    (outcome,) = execute_interface_plan(make_plan(), backend, dry_run=True)

    assert backend.updates == []
    assert (outcome.status, outcome.message) == (
        "skipped",
        "Dry-run mode: not updated.",
    )


def test_changed_netbox_interface_is_skipped():
    row = netbox_row() | {"mode": {"value": "access"}}
    backend = FakeNetBox(row)

    (outcome,) = execute_interface_plan(make_plan(), backend)

    assert backend.updates == []
    assert outcome.status == "skipped" and "(mode)" in outcome.message


def test_changed_or_unreadable_unifi_source_is_skipped():
    backend = FakeNetBox(netbox_row())
    changed = InventoryPortConfig("a", 1, "Uplink", True, "access", 20)

    (moved,) = execute_interface_plan(
        make_plan(), backend, source_configs={("a", 1): changed}
    )
    (offline,) = execute_interface_plan(make_plan(), backend, source_error="timeout")

    assert backend.updates == []
    assert "changed since the preview" in moved.message
    assert "could not be re-read" in offline.message


def test_missing_interface_failure_and_mismatch_are_reported():
    missing = FakeNetBox(netbox_row())
    missing.rows.clear()
    failing = FakeNetBox(netbox_row())
    failing.fail = requests.exceptions.ConnectionError("down")
    ignoring = FakeNetBox(netbox_row())
    ignoring.ignore = True

    (gone,) = execute_interface_plan(make_plan(), missing)
    (failed,) = execute_interface_plan(make_plan(), failing)
    (mismatch,) = execute_interface_plan(make_plan(), ignoring)

    assert gone.status == "skipped" and "no longer exists" in gone.message
    assert failed.status == "failed"
    assert (mismatch.status, mismatch.verification) == ("success", "mismatch")
    assert "mode: expected tagged" in mismatch.verification_detail
