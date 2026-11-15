"""Wireless LANs, DHCP IP ranges and reserved IPs (M11 slice 6)."""

import requests

from unifi2netbox.details import InventoryDhcpRange, InventoryReservation, InventoryWlan
from unifi2netbox.inventory import (
    InventoryIpAddress,
    InventoryIpRange,
    InventoryNetwork,
    InventorySite,
    InventoryVlan,
    InventoryVlanGroup,
    InventoryWirelessLan,
)
from unifi2netbox.site_details import (
    CONFLICT,
    CREATE,
    IN_SYNC,
    NOTE,
    RANGE,
    RESERVATION,
    UPDATE,
    WLAN,
    build_site_detail_plan,
    select_site_detail,
)
from unifi2netbox.site_details_execute import execute_site_detail_plan, source_items

SITE = InventorySite("3", "Home")
NETWORKS = (
    InventoryNetwork("n1", "Default", 1, subnet="10.10.0.0/24"),
    InventoryNetwork("n2", "IoT", 30, subnet="10.10.30.0/24"),
)
GROUP = InventoryVlanGroup("8", "UniFi Home", "unifi-home", "dcim.site", "3")
VLANS = (InventoryVlan("20", 1, "Default", "8"), InventoryVlan("21", 30, "IoT", "8"))
HOME = InventoryWlan("w1", "Home", security="wpapsk", wpa_enc="ccmp", vlan_id=30)
CORP = InventoryWlan("w2", "Corp", security="wpaeap", wpa_enc="ccmp", vlan_id=99)
OFF = InventoryWlan("w3", "Guest", enabled=False, security="open", vlan_id=1)
POOL = InventoryDhcpRange(1, "Default", "10.10.0.200", "10.10.0.250")
NAS = InventoryReservation("AA:BB:CC:00:00:01", "10.10.0.5", "NAS", "nas", "nas.lan")
TV = InventoryReservation("AA:BB:CC:00:00:02", "10.10.30.7", "", "tv")
LOST = InventoryReservation("AA:BB:CC:00:00:03", "192.168.9.9", "Lost")


def plan(
    wlans=(HOME, CORP, OFF),
    ranges=(POOL,),
    reservations=(NAS, TV, LOST),
    wireless_lans=(),
    ip_ranges=(),
    ip_addresses=(),
    **kwargs,
):
    return build_site_detail_plan(
        wlans=wlans,
        dhcp_ranges=ranges,
        reservations=reservations,
        networks=NETWORKS,
        sites=(SITE,),
        vlan_groups=(GROUP,),
        vlans=VLANS,
        wireless_lans=wireless_lans,
        ip_ranges=ip_ranges,
        ip_addresses=ip_addresses,
        site_name=kwargs.pop("site_name", "Home"),
        **kwargs,
    )


def row(result, key):
    return next(item for item in result.rows if item.key == key)


def test_wireless_lans_are_planned_with_vlan_auth_and_site_scope():
    result = plan()
    home, corp, off = (
        row(result, "wlan:w1"),
        row(result, "wlan:w2"),
        row(result, "wlan:w3"),
    )

    assert home.action == CREATE and home.selected and home.label == "Wireless LAN Home"
    assert dict(home.desired) == {
        "ssid": "Home",
        "status": "active",
        "auth_type": "wpa-personal",
        "auth_cipher": "aes",
        "vlan": "21",
        "scope_type": "dcim.site",
        "scope_id": "3",
    }
    assert dict(corp.desired)["auth_type"] == "wpa-enterprise"
    assert dict(corp.desired)["vlan"] == "" and "VLAN 99" in corp.notes[0]
    assert off.action == CREATE and not off.selected
    assert dict(off.desired)["status"] == "disabled"
    assert dict(off.desired)["auth_cipher"] == ""


def test_existing_wireless_lan_updates_auth_but_never_relinks_the_vlan():
    stale = InventoryWirelessLan("60", "Home", "21", "active", "open", "", "", "", "")
    synced = InventoryWirelessLan(
        "61", "Corp", "", "active", "wpa-enterprise", "aes", "", "dcim.site", "3"
    )
    other = InventoryWirelessLan(
        "62", "Guest", "20", "disabled", "open", "", "", "dcim.site", "4"
    )
    result = plan(wireless_lans=(stale, synced, other))

    home = row(result, "wlan:w1")
    assert home.action == UPDATE and home.selected and home.netbox_id == "60"
    assert {f for f, _, _ in home.changes()} == {
        "auth_type",
        "auth_cipher",
        "scope_type",
        "scope_id",
    }
    assert row(result, "wlan:w2").action == IN_SYNC
    guest = row(result, "wlan:w3")
    assert guest.action == CONFLICT and "scope_id" in guest.notes[-1]

    duplicate = plan(wireless_lans=(stale, stale.__class__("63", "Home")))
    assert row(duplicate, "wlan:w1").action == CONFLICT


def test_dhcp_ranges_get_the_network_prefix_length():
    pool = row(plan(), "range:1:10.10.0.200")

    assert pool.action == CREATE and pool.selected
    assert pool.label == "IP range 10.10.0.200-10.10.0.250"
    assert dict(pool.desired) == {
        "start_address": "10.10.0.200/24",
        "end_address": "10.10.0.250/24",
        "status": "active",
        "description": "DHCP Default",
    }


def test_existing_and_overlapping_ranges():
    empty = InventoryIpRange("70", "10.10.0.200/24", "10.10.0.250/24", "active", "")
    named = InventoryIpRange("70", "10.10.0.200/24", "10.10.0.250/24", "active", "Pool")
    overlap = InventoryIpRange("71", "10.10.0.240/24", "10.10.0.254/24", "active")
    key = "range:1:10.10.0.200"

    filled = row(plan(ip_ranges=(empty,)), key)
    kept = row(plan(ip_ranges=(named,)), key)
    clash = row(plan(ip_ranges=(overlap,)), key)

    assert filled.action == UPDATE
    assert filled.changes() == (("description", "", "DHCP Default"),)
    assert kept.action == IN_SYNC and "keeps its description 'Pool'" in kept.notes[0]
    assert clash.action == CONFLICT and "10.10.0.240-10.10.0.254" in clash.notes[0]


def test_reservations_are_reserved_unassigned_addresses():
    result = plan()
    nas, tv, lost = (
        row(result, "reservation:10.10.0.5"),
        row(result, "reservation:10.10.30.7"),
        row(result, "reservation:192.168.9.9"),
    )

    assert nas.action == CREATE and nas.selected
    assert dict(nas.desired) == {
        "address": "10.10.0.5/24",
        "status": "reserved",
        "dns_name": "nas.lan",
        "description": "NAS",
    }
    assert dict(tv.desired)["description"] == "tv"
    assert lost.action == NOTE and not lost.selectable


def test_existing_addresses_are_only_completed():
    empty = InventoryIpAddress("80", "10.10.0.5/24", "active")
    other = InventoryIpAddress("81", "10.10.0.5/24", "active", "nas.other")
    filled = row(plan(ip_addresses=(empty,)), "reservation:10.10.0.5")
    clash = row(plan(ip_addresses=(other,)), "reservation:10.10.0.5")
    twice = row(plan(ip_addresses=(empty, other)), "reservation:10.10.0.5")

    assert filled.action == UPDATE
    assert {f for f, _, _ in filled.changes()} == {"dns_name", "description"}
    assert clash.action == CONFLICT and "dns_name" in clash.notes[-1]
    assert twice.action == CONFLICT


def test_invalid_dns_name_is_left_out():
    odd = InventoryReservation("AA:BB:CC:00:00:09", "10.10.0.9", "Odd", "", "bad name")
    (only,) = plan(wlans=(), ranges=(), reservations=(odd,)).rows

    assert dict(only.desired)["dns_name"] == "" and "not a valid" in only.notes[0]


def test_missing_site_errors_and_selection():
    assert "NetBox site" in plan(site_name="Nowhere").note
    errors = plan(address_error="HTTP 403", wireless_error="HTTP 403")
    assert {item.action for item in errors.rows} == {NOTE}
    assert plan(client_error="wlanconf failed").note == "wlanconf failed"

    result = plan()
    cleared = select_site_detail(result, "reservation:*", False)
    assert not cleared.selected_rows([RESERVATION])
    assert cleared.selected_rows([RANGE]) and cleared.selected_rows([WLAN])
    one = select_site_detail(result, "wlan:w3", True)
    assert row(one, "wlan:w3").selected


class FakeNetBox:
    def __init__(self, objects=None):
        self.objects = dict(objects or {})
        self.created = []
        self.updated = []
        self.fail = None

    def find_ids(self, path, **filters):
        def matches(obj):
            return all(
                str(obj.get(key, "")).split("/", 1)[0] == str(value)
                for key, value in filters.items()
            )

        return tuple(
            key
            for key, (kind_path, obj) in self.objects.items()
            if kind_path == path and matches(obj)
        )

    def read_object(self, path):
        entry = self.objects.get(path.rstrip("/").rsplit("/", 1)[-1])
        return entry[1] if entry else None

    def create_object(self, path, payload):
        stored = dict(payload)
        if "vlan" in stored:
            stored["vlan"] = {"id": stored["vlan"]}
        object_id = str(90 + len(self.objects))
        if self.fail:
            self.objects[object_id] = (path, stored)
            raise self.fail
        self.created.append((path, payload))
        self.objects[object_id] = (path, stored)
        return object_id

    def update_object(self, path, payload):
        object_id = path.rstrip("/").rsplit("/", 1)[-1]
        self.updated.append((object_id, payload))
        kind_path, obj = self.objects[object_id]
        self.objects[object_id] = (kind_path, obj | payload)


FRESH = source_items((HOME, CORP, OFF), (POOL,), (NAS, TV, LOST))


def test_creates_send_ids_as_integers_and_verify():
    backend = FakeNetBox()

    outcomes = execute_site_detail_plan(plan(), backend, source_items=FRESH)

    assert [o.status for o in outcomes] == ["success"] * 5
    assert all(o.verification == "verified" for o in outcomes)
    wlan = next(p for _, p in backend.created if p.get("ssid") == "Home")
    assert wlan["vlan"] == 21 and wlan["scope_id"] == 3
    assert "vlan" not in next(
        payload for _, payload in backend.created if payload.get("ssid") == "Corp"
    )
    (reserved,) = [p for _, p in backend.created if p.get("address") == "10.10.0.5/24"]
    assert reserved["status"] == "reserved" and "assigned_object_id" not in reserved


def test_kinds_order_and_skips():
    backend = FakeNetBox()
    first = execute_site_detail_plan(plan(), backend, kinds=(WLAN, RANGE))
    assert {o.operation for o in first} == {"create_wireless_lan", "create_ip_range"}

    changed = source_items((HOME, CORP), (POOL,), (NAS, TV))
    moved = InventoryReservation("AA:BB:CC:00:00:09", "10.10.0.5", "NAS", "nas")
    changed[(RESERVATION, "10.10.0.5")] = moved
    skipped = execute_site_detail_plan(
        plan(), FakeNetBox(), kinds=(RESERVATION,), source_items=changed
    )
    assert skipped[0].status == "skipped" and "UniFi changed" in skipped[0].message

    dry = execute_site_detail_plan(plan(), FakeNetBox(), dry_run=True)
    failed = execute_site_detail_plan(plan(), FakeNetBox(), source_error="timeout")
    assert all(o.status == "skipped" for o in dry + failed)


def test_existing_object_is_not_duplicated_and_updates_check_drift():
    path = "/api/ipam/ip-addresses/"
    backend = FakeNetBox({"5": (path, {"address": "10.10.0.5/24"})})
    (outcome,) = execute_site_detail_plan(
        plan(wlans=(), ranges=(), reservations=(NAS,)), backend
    )
    assert outcome.status == "skipped" and "since the preview" in outcome.message

    empty = InventoryIpAddress("80", "10.10.0.5/24", "active")
    update = plan(wlans=(), ranges=(), reservations=(NAS,), ip_addresses=(empty,))
    record = {"address": "10.10.0.5/24", "dns_name": "", "description": "Edited"}
    backend = FakeNetBox({"80": (path, record)})
    (drifted,) = execute_site_detail_plan(update, backend)
    assert drifted.status == "skipped" and "description" in drifted.message

    backend = FakeNetBox({"80": (path, dict(record, description=""))})
    (written,) = execute_site_detail_plan(update, backend)
    assert written.status == "success" and written.verification == "verified"
    assert backend.updated == [("80", {"dns_name": "nas.lan", "description": "NAS"})]


def test_interrupted_create_is_reconciled():
    backend = FakeNetBox()
    backend.fail = requests.exceptions.Timeout("timed out")

    (outcome,) = execute_site_detail_plan(
        plan(wlans=(), ranges=(POOL,), reservations=()), backend
    )

    assert outcome.status == "success" and "interrupted" in outcome.message
