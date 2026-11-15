"""Management IPs as NetBox primary IPv4 (M11 slice 3)."""

import requests

from unifi2netbox.inventory import (
    InventoryDevice,
    InventoryInterface,
    InventoryIpAddress,
    InventoryNetwork,
)
from unifi2netbox.mgmt_ip import (
    CONFLICT,
    CREATE,
    IN_SYNC,
    NOTE,
    UPDATE,
    MgmtPair,
    build_mgmt_ip_plan,
    select_mgmt_ip,
)
from unifi2netbox.mgmt_ip_execute import execute_mgmt_ip_plan

PAIR = MgmtPair("unifi_network:u1->netbox:7", "SW1", "u1", "7")
UNIFI = InventoryDevice("u1", "SW1", ip_address="10.10.0.5")
NETWORKS = (
    InventoryNetwork("n1", "Mgmt", 1, subnet="10.10.0.0/24"),
    InventoryNetwork("n2", "Wide", 2, subnet="10.0.0.0/8"),
)


def plan(netbox=None, interfaces=(), addresses=(), networks=NETWORKS, **kwargs):
    return build_mgmt_ip_plan(
        (PAIR,),
        (UNIFI,),
        (netbox or InventoryDevice("7", "SW1"),),
        interfaces,
        addresses,
        networks,
        **kwargs,
    )


def test_new_ip_creates_interface_ip_and_primary():
    (row,) = plan().rows

    assert row.action == CREATE and row.selected
    assert row.address == "10.10.0.5/24"  # the most specific network wins
    assert row.steps == ("create_interface", "create_ip", "set_primary")
    assert row.key == "mgmt-ip:7" and row.label == "SW1 10.10.0.5"


def test_existing_management_interface_and_free_ip_are_reused():
    interfaces = (
        InventoryInterface("50", "7", "eth0", "1000base-t"),
        InventoryInterface("51", "7", "mgmt", "virtual", mgmt_only=True),
    )
    free = InventoryIpAddress("90", "10.10.0.5/24")

    (row,) = plan(interfaces=interfaces, addresses=(free,)).rows

    assert row.action == UPDATE
    assert (row.interface_id, row.ip_id) == ("51", "90")
    assert row.steps == ("assign_ip", "set_primary")


def test_ip_on_an_interface_of_the_device_only_sets_primary():
    interfaces = (InventoryInterface("50", "7", "eth0", "1000base-t"),)
    held = InventoryIpAddress(
        "90",
        "10.10.0.5/24",
        assigned_object_type="dcim.interface",
        assigned_object_id="50",
    )

    (row,) = plan(interfaces=interfaces, addresses=(held,)).rows

    assert row.action == UPDATE and row.steps == ("set_primary",)
    assert row.interface_id == "50"


def test_conflicts_never_overwrite():
    other_primary = InventoryDevice(
        "7", "SW1", ip_address="10.10.0.9", primary_ip_id="3"
    )
    elsewhere = InventoryIpAddress(
        "90",
        "10.10.0.5/24",
        assigned_object_type="dcim.interface",
        assigned_object_id="999",
    )
    two_mgmt = (
        InventoryInterface("51", "7", "a", "virtual", mgmt_only=True),
        InventoryInterface("52", "7", "b", "virtual", mgmt_only=True),
    )
    duplicates = (
        InventoryIpAddress("90", "10.10.0.5/24"),
        InventoryIpAddress("91", "10.10.0.5/16"),
    )

    for rows in (
        plan(netbox=other_primary).rows,
        plan(addresses=(elsewhere,)).rows,
        plan(interfaces=two_mgmt).rows,
        plan(addresses=duplicates).rows,
    ):
        assert rows[0].action == CONFLICT and not rows[0].selectable


def test_in_sync_note_and_blocker():
    synced = InventoryDevice("7", "SW1", ip_address="10.10.0.5", primary_ip_id="90")
    assert plan(netbox=synced).rows[0].action == IN_SYNC
    (note,) = plan(networks=()).rows
    assert note.action == NOTE and "prefix length" in note.notes[0]
    wan = build_mgmt_ip_plan(
        (PAIR,),
        (InventoryDevice("u1", "UDM", ip_address="1.1.1.1"),),
        (InventoryDevice("7", "UDM"),),
        (),
        (),
        NETWORKS,
    )
    assert wan.rows[0].action == NOTE and "public (WAN)" in wan.rows[0].notes[0]
    blocked = plan(address_error="NetBox IP addresses could not be read: denied")
    assert blocked.rows == () and blocked.blocker.startswith("NetBox IP addresses")
    no_ip = build_mgmt_ip_plan(
        (PAIR,),
        (InventoryDevice("u1", "SW1"),),
        (InventoryDevice("7", "SW1"),),
        (),
        (),
        NETWORKS,
    )
    assert no_ip.rows == ()


def test_named_interface_without_mgmt_flag_is_used_with_a_note():
    named = (InventoryInterface("53", "7", "Management", "virtual"),)

    (row,) = plan(interfaces=named).rows

    assert row.interface_id == "53" and "create_interface" not in row.steps
    assert "not marked management only" in row.notes[0]


def test_selection():
    base = plan()
    off = select_mgmt_ip(base, "mgmt-ip:7", False)
    assert base.operation_count == 1 and off.operation_count == 0


class FakeNetBox:
    def __init__(self, primary=None):
        self.objects = {
            "/api/dcim/devices/7/": {"id": 7, "primary_ip4": primary},
        }
        self.created = []
        self.updated = []
        self.fail_on = None
        self.apply_anyway = False
        self.next_id = 100

    def find_ids(self, path, **filters):
        found = []
        for key, row in self.objects.items():
            if not key.startswith(path) or key == path:
                continue
            if (
                path.endswith("interfaces/")
                and row.get("name") == filters.get("name")
                and str(row.get("device")) == str(filters.get("device_id"))
            ):
                found.append(str(row["id"]))
            if path.endswith("ip-addresses/") and row.get("address", "").split("/")[
                0
            ] == filters.get("address"):
                found.append(str(row["id"]))
        return tuple(found)

    def read_object(self, path):
        return self.objects.get(path)

    def create_object(self, path, payload):
        self.next_id += 1
        new_id = str(self.next_id)
        if self.fail_on == path:
            if self.apply_anyway:
                self.objects[f"{path}{new_id}/"] = dict(payload, id=int(new_id))
            raise requests.exceptions.Timeout("timed out")
        self.created.append((path, payload))
        self.objects[f"{path}{new_id}/"] = dict(payload, id=int(new_id))
        return new_id

    def update_object(self, path, payload):
        self.updated.append((path, payload))
        row = self.objects[path]
        for key, value in payload.items():
            row[key] = {"id": value} if key == "primary_ip4" else value


def test_execute_creates_everything_and_verifies():
    backend = FakeNetBox()

    (outcome,) = execute_mgmt_ip_plan(plan(), backend, source_devices={"u1": UNIFI})

    assert outcome.status == "success" and outcome.verification == "verified"
    interface = backend.created[0]
    assert interface[0] == "/api/dcim/interfaces/"
    assert interface[1]["mgmt_only"] is True and interface[1]["type"] == "virtual"
    address = backend.created[1][1]
    assert address["address"] == "10.10.0.5/24"
    assert address["assigned_object_id"] == 101
    assert backend.updated == [("/api/dcim/devices/7/", {"primary_ip4": 102})]


def test_dry_run_checks_and_writes_nothing():
    backend = FakeNetBox()

    (outcome,) = execute_mgmt_ip_plan(plan(), backend, dry_run=True)

    assert outcome.status == "skipped" and "Dry-run" in outcome.message
    assert backend.created == [] and backend.updated == []


def test_drift_skips():
    changed_ip = InventoryDevice("u1", "SW1", ip_address="10.10.0.6")
    (by_unifi,) = execute_mgmt_ip_plan(
        plan(), FakeNetBox(), source_devices={"u1": changed_ip}
    )
    (by_primary,) = execute_mgmt_ip_plan(plan(), FakeNetBox(primary={"id": 5}))
    racing = FakeNetBox()
    racing.objects["/api/ipam/ip-addresses/77/"] = {"id": 77, "address": "10.10.0.5/24"}
    (by_ip,) = execute_mgmt_ip_plan(plan(), racing)
    (failed_read,) = execute_mgmt_ip_plan(plan(), FakeNetBox(), source_error="timeout")

    assert by_unifi.status == "skipped" and "another IP" in by_unifi.message
    assert (
        by_primary.status == "skipped" and "primary IPv4 changed" in by_primary.message
    )
    assert by_ip.status == "skipped" and "got the IP" in by_ip.message
    assert failed_read.status == "skipped" and "re-read" in failed_read.message
    assert racing.created == []


def test_interrupted_ip_create_is_reconciled_not_retried():
    backend = FakeNetBox()
    backend.fail_on = "/api/ipam/ip-addresses/"
    backend.apply_anyway = True

    (outcome,) = execute_mgmt_ip_plan(plan(), backend)

    assert outcome.status == "success" and outcome.verification == "verified"
    assert [path for path, _ in backend.created] == ["/api/dcim/interfaces/"]


def test_partial_failure_reports_what_was_done():
    backend = FakeNetBox()
    backend.fail_on = "/api/ipam/ip-addresses/"

    (outcome,) = execute_mgmt_ip_plan(plan(), backend)

    assert outcome.status == "failed"
    assert "Already done: created interface Management" in outcome.message
    assert backend.updated == []
