import requests

from unifi2netbox.inventory import (
    InventoryNetwork,
    InventoryPrefix,
    InventorySite,
    InventoryVlan,
    InventoryVlanGroup,
)
from unifi2netbox.network_execute import execute_network_plan
from unifi2netbox.networks import build_network_plan, select_network

SITES = (InventorySite("7", "Home"),)


class FakeIpam:
    """In-memory NetBox IPAM with the backend methods the executor uses."""

    def __init__(self):
        self.objects = {
            "/api/ipam/vlan-groups/": {},
            "/api/ipam/vlans/": {},
            "/api/ipam/prefixes/": {},
        }
        self.next_id = 100
        self.creates = []
        self.updates = []
        self.fail_create_once = None

    def add(self, path, row):
        self.objects[path][str(row["id"])] = row

    def _matches(self, row, filters):
        for key, value in filters.items():
            if key == "group_id":
                if str((row.get("group") or {}).get("id")) != str(value):
                    return False
            elif str(row.get(key)) != str(value):
                return False
        return True

    def find_ids(self, path, **filters):
        return tuple(
            object_id
            for object_id, row in self.objects[path].items()
            if self._matches(row, filters)
        )

    def read_object(self, path):
        base, object_id = path.rstrip("/").rsplit("/", 1)
        return self.objects[base + "/"].get(object_id)

    def create_object(self, path, payload):
        self.creates.append((path, payload))
        object_id = str(self.next_id)
        self.next_id += 1
        row = {"id": object_id, **payload}
        for key in ("group", "vlan"):
            if key in row:
                row[key] = {"id": row[key]}
        if "status" in row:
            row["status"] = {"value": row["status"]}
        self.objects[path][object_id] = row
        if self.fail_create_once == path:
            self.fail_create_once = None
            raise requests.exceptions.ReadTimeout("read timed out")
        return object_id

    def update_object(self, path, payload):
        self.updates.append((path, payload))
        row = self.read_object(path)
        for key, value in payload.items():
            row[key] = {"id": value} if key == "vlan" else value


def network(source_id, name, vid, subnet="", enabled=True):
    return InventoryNetwork(source_id, name, vid, enabled, subnet)


def make_plan(networks, groups=(), vlans=(), prefixes=()):
    return build_network_plan(
        tuple(networks),
        SITES,
        tuple(groups),
        tuple(vlans),
        tuple(prefixes),
        site_name="Home",
    )


def test_creates_group_vlans_and_linked_prefixes_in_order():
    ipam = FakeIpam()
    plan = make_plan(
        [network("n1", "IoT", 20, "10.0.20.0/24"), network("n2", "Lab", 30)]
    )

    outcomes = execute_network_plan(plan, ipam)

    assert [o.operation for o in outcomes] == [
        "create_vlan_group",
        "create_vlan",
        "create_vlan",
        "create_prefix",
    ]
    assert all(o.status == "success" and o.verification == "verified" for o in outcomes)
    group_id = outcomes[0].object_id
    vlan = ipam.objects["/api/ipam/vlans/"][outcomes[1].object_id]
    assert vlan["group"] == {"id": int(group_id)} and vlan["vid"] == 20
    prefix = ipam.objects["/api/ipam/prefixes/"][outcomes[3].object_id]
    assert prefix["vlan"] == {"id": int(outcomes[1].object_id)}
    assert prefix["scope_id"] == 7 and prefix["description"] == "IoT"


def test_dry_run_checks_without_writing():
    ipam = FakeIpam()
    plan = make_plan([network("n1", "IoT", 20, "10.0.20.0/24")])

    outcomes = execute_network_plan(plan, ipam, dry_run=True)

    assert ipam.creates == []
    assert [o.status for o in outcomes] == ["skipped", "skipped", "skipped"]
    assert outcomes[1].message == "Dry run: the VLAN group does not exist yet."


def test_objects_that_appeared_after_the_preview_are_not_duplicated():
    ipam = FakeIpam()
    plan = make_plan([network("n1", "IoT", 20, "10.0.20.0/24")])
    ipam.add("/api/ipam/vlan-groups/", {"id": "3", "slug": "unifi-home"})
    ipam.add("/api/ipam/vlans/", {"id": "9", "vid": 20, "group": {"id": "3"}})
    ipam.add("/api/ipam/prefixes/", {"id": "5", "prefix": "10.0.20.0/24"})

    outcomes = execute_network_plan(plan, ipam)

    assert ipam.creates == []
    assert outcomes[0].status == "success" and "it is used" in outcomes[0].message
    assert [o.status for o in outcomes[1:]] == ["skipped", "skipped"]
    assert "Already exists in NetBox (ID 9)" in outcomes[1].message


def test_updates_check_the_preview_baseline():
    group = InventoryVlanGroup("3", "UniFi Home", "unifi-home", "dcim.site", "7")
    vlan = InventoryVlan("9", 20, "Old", "3")
    prefix = InventoryPrefix("5", "10.0.20.0/24")
    plan = make_plan(
        [network("n1", "IoT", 20, "10.0.20.0/24")], [group], [vlan], [prefix]
    )
    ipam = FakeIpam()
    ipam.add("/api/ipam/vlans/", {"id": "9", "vid": 20, "name": "Old"})
    ipam.add("/api/ipam/prefixes/", {"id": "5", "prefix": "10.0.20.0/24", "vlan": None})

    outcomes = execute_network_plan(plan, ipam)

    assert [(o.operation, o.status, o.verification) for o in outcomes] == [
        ("update_vlan", "success", "verified"),
        ("update_prefix", "success", "verified"),
    ]

    ipam.objects["/api/ipam/vlans/"]["9"]["name"] = "Edited"
    again = execute_network_plan(plan, ipam)
    assert (
        again[0].status == "skipped" and "changed since the preview" in again[0].message
    )
    assert again[1].status == "skipped" and "got a VLAN" in again[1].message


def test_interrupted_create_is_looked_up_not_retried():
    ipam = FakeIpam()
    ipam.fail_create_once = "/api/ipam/vlans/"
    plan = make_plan([network("n1", "IoT", 20)])

    outcomes = execute_network_plan(plan, ipam)

    vlan_creates = [c for c in ipam.creates if c[0] == "/api/ipam/vlans/"]
    assert len(vlan_creates) == 1
    assert outcomes[1].status == "success" and "interrupted" in outcomes[1].message


def test_unifi_changes_and_unreadable_unifi_skip_writes():
    plan = make_plan([network("n1", "IoT", 20, "10.0.20.0/24")])
    changed = {"network:n1": network("n1", "IoT", 21, "10.0.20.0/24")}

    outcomes = execute_network_plan(plan, FakeIpam(), source_networks=changed)
    assert [o.status for o in outcomes[1:]] == ["skipped", "skipped"]
    assert "changed since the preview (VLAN)" in outcomes[1].message

    blocked = execute_network_plan(plan, FakeIpam(), source_error="timeout")
    assert blocked[0].status == "skipped"
    assert "could not be re-read" in blocked[0].message


def test_nothing_selected_means_no_operations():
    plan = make_plan([network("n1", "IoT", 20, "10.0.20.0/24")])
    plan = select_network(plan, "network:n1", "all", False)

    assert execute_network_plan(plan, FakeIpam()) == ()
