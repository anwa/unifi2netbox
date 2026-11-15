import json
from datetime import UTC, datetime

import httpx
import pytest
import requests

from unifi2netbox.config import NetBoxConfig, UniFiConfig
from unifi2netbox.inventory import (
    InventoryError,
    InventorySource,
    read_netbox_inventory,
    read_unifi_inventory,
)

SITE_ID = "11111111-1111-4111-8111-111111111111"
SECOND_ID = "22222222-2222-4222-8222-222222222222"


def page(rows, *, offset=0, total=None, limit=200):
    return {
        "offset": offset,
        "limit": limit,
        "count": len(rows),
        "totalCount": len(rows) if total is None else total,
        "data": rows,
    }


@pytest.fixture
def netbox_transport(monkeypatch):
    calls = []
    responses = [
        (200, {"netbox-version": "4.7.3"}),
        (
            200,
            {
                "count": 2,
                "next": "https://netbox.invalid/api/dcim/devices/?limit=1&offset=1",
                "previous": None,
                "results": [
                    {
                        "id": 7,
                        "name": "edge-a",
                        "serial": " abcd1234 ",
                        "status": {"value": "active", "label": "Active"},
                        "primary_mac_address": "00-11-22-33-44-55",
                        "device_type": {
                            "model": "USW-24",
                            "manufacturer": {"name": "Ubiquiti"},
                        },
                        "site": {"name": "HQ"},
                    }
                ],
            },
        ),
        (
            200,
            {
                "count": 2,
                "next": None,
                "previous": "https://netbox.invalid/api/dcim/devices/?limit=1&offset=0",
                "results": [
                    {
                        "id": 8,
                        "name": "edge-b",
                        "serial": "xyz",
                        "status": {"value": "planned", "label": "Planned"},
                        "primary_mac_address": "66:55:44:33:22:11",
                        "device_type": {
                            "model": "U7-Pro",
                            "manufacturer": {"name": "Ubiquiti"},
                        },
                        "site": {"name": "HQ"},
                    }
                ],
            },
        ),
        (
            200,
            {
                "count": 2,
                "next": "https://netbox.invalid/api/dcim/interfaces/?limit=1&offset=1",
                "previous": None,
                "results": [
                    {
                        "id": 501,
                        "device": {"id": 7, "name": "edge-a"},
                        "name": "Port 1",
                        "type": {"value": "1000base-t", "label": "1000BASE-T"},
                        "enabled": True,
                        "mgmt_only": False,
                        "mode": None,
                        "poe_mode": {"value": "pse", "label": "PSE"},
                        "poe_type": {"value": "type2-ieee802.3at", "label": "x"},
                        "speed": None,
                    }
                ],
            },
        ),
        (
            200,
            {
                "count": 2,
                "next": None,
                "previous": "https://netbox.invalid/api/dcim/interfaces/?limit=1&offset=0",
                "results": [
                    {
                        "id": 502,
                        "device": {"id": 7, "name": "edge-a"},
                        "name": "SFP+ 1",
                        "type": {"value": "10gbase-x-sfpp", "label": "SFP+"},
                        "enabled": False,
                        "mode": {"value": "tagged", "label": "Tagged"},
                        "speed": 10000000,
                    }
                ],
            },
        ),
        (200, {"count": 0, "next": None, "previous": None, "results": []}),
        (200, {"count": 0, "next": None, "previous": None, "results": []}),
        (200, {"count": 0, "next": None, "previous": None, "results": []}),
        # inventory items
        (200, {"count": 0, "next": None, "previous": None, "results": []}),
        # manufacturers, IP addresses, IP ranges, wireless LANs, custom fields
        *[(200, {"count": 0, "next": None, "previous": None, "results": []})] * 5,
        (
            200,
            {
                "count": 2,
                "next": "https://netbox.invalid/api/dcim/device-types/?limit=1&offset=1",
                "previous": None,
                "results": [
                    {
                        "id": 101,
                        "model": "USW-24",
                        "manufacturer": {"name": "Ubiquiti"},
                    }
                ],
            },
        ),
        (
            200,
            {
                "count": 2,
                "next": None,
                "previous": "https://netbox.invalid/api/dcim/device-types/?limit=1&offset=0",
                "results": [
                    {
                        "id": 102,
                        "model": "U7-Pro",
                        "manufacturer": {"name": "Ubiquiti"},
                    }
                ],
            },
        ),
        (
            200,
            {
                "count": 2,
                "next": "https://netbox.invalid/api/dcim/device-roles/?limit=1&offset=1",
                "previous": None,
                "results": [{"id": 201, "name": "Network Device"}],
            },
        ),
        (
            200,
            {
                "count": 2,
                "next": None,
                "previous": "https://netbox.invalid/api/dcim/device-roles/?limit=1&offset=0",
                "results": [{"id": 202, "name": "Wireless"}],
            },
        ),
        (
            200,
            {
                "count": 2,
                "next": "https://netbox.invalid/api/dcim/sites/?limit=1&offset=1",
                "previous": None,
                "results": [{"id": 301, "name": "HQ"}],
            },
        ),
        (
            200,
            {
                "count": 2,
                "next": None,
                "previous": "https://netbox.invalid/api/dcim/sites/?limit=1&offset=0",
                "results": [{"id": 302, "name": "Branch"}],
            },
        ),
        (
            200,
            {
                "actions": {
                    "POST": {
                        "status": {
                            "choices": [
                                {"value": "active", "label": "Active"},
                                {"value": "planned", "label": "Planned"},
                            ]
                        }
                    }
                }
            },
        ),
    ]

    def send(session, request, **kwargs):
        calls.append((request, kwargs))
        code, payload = responses.pop(0)
        response = requests.Response()
        response.status_code = code
        response._content = json.dumps(payload).encode()
        response.headers["Content-Type"] = "application/json"
        response.request = request
        response.url = request.url
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    return calls, responses


@pytest.fixture
def unifi_api():
    calls = []
    responses = [
        httpx.Response(200, json={"applicationVersion": "10.6.100"}),
        httpx.Response(
            200,
            json=page(
                [
                    {
                        "id": SITE_ID,
                        "name": "Default",
                        "internalReference": "default",
                    },
                    {
                        "id": SECOND_ID,
                        "name": "Other",
                        "internalReference": "other",
                    },
                ],
                total=2,
                limit=200,
            ),
        ),
        httpx.Response(
            200,
            json=page(
                [
                    {
                        "id": "dev-1",
                        "name": "switch-1",
                        "model": "USW-24",
                        "serial": "abc123",
                        "macAddress": "001122334455",
                    }
                ],
                total=2,
                limit=1,
            ),
        ),
        httpx.Response(
            200,
            json=page(
                [
                    {
                        "id": "dev-2",
                        "hostname": "ap-2",
                        "model": "U7-Pro",
                        "serial": "def456",
                        "mac": "66:55:44:33:22:11",
                    }
                ],
                offset=1,
                total=2,
                limit=1,
            ),
        ),
        httpx.Response(200, json=page([], limit=1)),
    ]

    def handle(request):
        calls.append(request)
        return responses.pop(0)

    return calls, responses, httpx.MockTransport(handle)


def test_netbox_inventory_is_paginated_and_normalized(netbox_transport):
    captured_at = datetime(2026, 10, 28, 12, 30, 0, tzinfo=UTC)
    snapshot = read_netbox_inventory(
        NetBoxConfig("https://netbox.invalid", "synthetic-token"),
        page_size=1,
        captured_at=captured_at,
    )
    calls, _ = netbox_transport

    assert snapshot.source == InventorySource.NETBOX
    assert snapshot.source_version == "4.7.3"
    assert snapshot.captured_at == "2026-10-28T12:30:00+00:00"
    assert [device.source_id for device in snapshot.devices] == ["7", "8"]
    assert snapshot.devices[0].serial == "ABCD1234"
    assert snapshot.devices[0].mac_address == "00:11:22:33:44:55"
    assert snapshot.devices[0].manufacturer == "Ubiquiti"
    assert snapshot.devices[1].name == "edge-b"
    assert [item.source_id for item in snapshot.device_types] == ["101", "102"]
    assert snapshot.device_types[0].manufacturer == "Ubiquiti"
    assert snapshot.device_types[1].model == "U7-Pro"
    assert [item.source_id for item in snapshot.device_roles] == ["201", "202"]
    assert snapshot.device_roles[0].name == "Network Device"
    assert snapshot.device_roles[1].name == "Wireless"
    assert [item.source_id for item in snapshot.sites] == ["301", "302"]
    assert snapshot.sites[0].name == "HQ"
    assert snapshot.sites[1].name == "Branch"
    assert [item.value for item in snapshot.device_statuses] == ["active", "planned"]
    assert snapshot.device_statuses[0].label == "Active"
    first, second = snapshot.interfaces
    assert (first.source_id, first.device_id, first.name) == ("501", "7", "Port 1")
    assert (first.type, first.poe_mode, first.enabled) == ("1000base-t", "pse", True)
    assert (second.type, second.mode, second.enabled) == (
        "10gbase-x-sfpp",
        "tagged",
        False,
    )
    assert second.speed_kbps == 10000000

    for request, options in calls:
        assert request.method == "GET"
        assert options["timeout"] == (10.0, 10.0)
        assert options["allow_redirects"] is False


def test_netbox_inventory_page_limit_is_bounded(netbox_transport):
    with pytest.raises(InventoryError, match="page safety limit"):
        read_netbox_inventory(
            NetBoxConfig("https://netbox.invalid", "synthetic-token"),
            page_size=1,
            max_pages=1,
        )


def test_netbox_inventory_succeeds_when_status_choices_endpoint_is_unavailable(
    netbox_transport,
):
    _, responses = netbox_transport
    responses[-1] = (404, {"detail": "Not found."})

    snapshot = read_netbox_inventory(
        NetBoxConfig("https://netbox.invalid", "synthetic-token"),
        page_size=1,
    )

    assert snapshot.source == InventorySource.NETBOX
    assert [device.source_id for device in snapshot.devices] == ["7", "8"]
    assert [item.source_id for item in snapshot.sites] == ["301", "302"]
    assert [item.value for item in snapshot.device_statuses] == ["active", "planned"]


def test_unifi_inventory_is_paginated_and_normalized(unifi_api):
    calls, _, transport = unifi_api
    captured_at = datetime(2026, 10, 28, 13, 0, 0, tzinfo=UTC)
    snapshot = read_unifi_inventory(
        UniFiConfig("https://console.invalid", "synthetic-key", site=SITE_ID),
        page_size=1,
        captured_at=captured_at,
        transport=transport,
    )

    assert snapshot.source == InventorySource.UNIFI_NETWORK
    assert snapshot.source_version == "10.6.100"
    assert snapshot.scope == f"Default ({SITE_ID})"
    assert snapshot.captured_at == "2026-10-28T13:00:00+00:00"
    assert [device.source_id for device in snapshot.devices] == ["dev-1", "dev-2"]
    assert snapshot.devices[0].serial == "ABC123"
    assert snapshot.devices[0].mac_address == "00:11:22:33:44:55"
    assert snapshot.devices[0].manufacturer == "Ubiquiti"
    assert snapshot.devices[1].name == "ap-2"
    assert snapshot.devices[1].mac_address == "66:55:44:33:22:11"
    assert snapshot.devices[1].manufacturer == "Ubiquiti"
    assert len(snapshot.unifi_api_feedback) == 4
    assert snapshot.unifi_api_feedback[0]["endpoint"] == "info"
    assert snapshot.unifi_api_feedback[-1]["endpoint"].endswith("/devices")
    assert len(snapshot.unifi_raw_devices) == 2
    assert snapshot.unifi_raw_devices[0]["id"] == "dev-1"

    assert [request.url.path for request in calls] == [
        "/proxy/network/integration/v1/info",
        "/proxy/network/integration/v1/sites",
        f"/proxy/network/integration/v1/sites/{SITE_ID}/devices",
        f"/proxy/network/integration/v1/sites/{SITE_ID}/devices",
        f"/proxy/network/integration/v1/sites/{SITE_ID}/networks",
    ]


def test_unifi_inventory_requires_explicit_site_for_multiple_sites(unifi_api):
    with pytest.raises(InventoryError, match="Choose one accessible site"):
        read_unifi_inventory(
            UniFiConfig("https://console.invalid", "synthetic-key"),
            transport=unifi_api[2],
        )


def test_unifi_inventory_rejects_bad_pagination(unifi_api):
    unifi_api[1][2] = httpx.Response(
        200,
        json={
            "offset": 0,
            "limit": 1,
            "count": 2,
            "totalCount": 2,
            "data": [{"id": "dev-1"}],
        },
    )
    with pytest.raises(InventoryError, match="pagination metadata"):
        read_unifi_inventory(
            UniFiConfig("https://console.invalid", "synthetic-key", site=SITE_ID),
            page_size=1,
            transport=unifi_api[2],
        )


def test_unifi_inventory_reads_ports_from_device_details():
    responses = {
        "info": {"applicationVersion": "11.0.99"},
        "sites": page([{"id": SITE_ID, "name": "Default", "internalReference": "d"}]),
        f"sites/{SITE_ID}/devices": page(
            [
                {
                    "id": "sw",
                    "name": "switch",
                    "model": "US 8 60W",
                    "macAddress": "aa:bb:cc:00:00:01",
                    "interfaces": ["ports"],
                },
                {
                    "id": "ap",
                    "name": "ap",
                    "model": "U6 Lite",
                    "interfaces": ["radios"],
                },
            ]
        ),
        f"sites/{SITE_ID}/networks": page([]),
        f"sites/{SITE_ID}/devices/sw": {
            "id": "sw",
            "interfaces": {
                "ports": [
                    {
                        "idx": 2,
                        "state": "DOWN",
                        "connector": "RJ45",
                        "maxSpeedMbps": 1000,
                    },
                    {
                        "idx": 1,
                        "state": "UP",
                        "connector": "rj45",
                        "maxSpeedMbps": 1000,
                        "speedMbps": 100,
                        "poe": {
                            "standard": "802.3at",
                            "type": 2,
                            "enabled": True,
                            "state": "UP",
                        },
                    },
                ]
            },
        },
    }
    internal = {
        "stat/device": [
            {
                "mac": "AA:BB:CC:00:00:01",
                "port_table": [
                    {
                        "port_idx": 1,
                        "name": "Uplink",
                        "enable": True,
                        "forward": "all",
                        "sfp_found": True,
                        "sfp_vendor": "UBNT",
                        "sfp_part": "UF-MM-10G",
                        "sfp_serial": "SYNTH-SFP-1",
                        "sfp_compliance": "10GBase-SR",
                    },
                    {
                        "port_idx": 2,
                        "name": "Port 2",
                        "enable": False,
                        "forward": "disabled",
                        "sfp_found": False,
                        "sfp_part": "stale",
                    },
                ],
                "port_overrides": [
                    {
                        "port_idx": 1,
                        "autoneg": False,
                        "speed": 10000,
                        "full_duplex": True,
                    }
                ],
            }
        ],
        "rest/portconf": [],
        "rest/networkconf": [
            {
                "_id": "lan",
                "name": "Default",
                "purpose": "corporate",
                "vlan_enabled": False,
                "dhcpd_enabled": True,
                "dhcpd_start": "192.0.2.100",
                "dhcpd_stop": "192.0.2.200",
            },
            {"_id": "wan", "purpose": "wan", "x_password": "synthetic-secret"},
        ],
        "rest/wlanconf": [
            {
                "_id": "w1",
                "name": "Synthetic WLAN",
                "enabled": True,
                "security": "wpapsk",
                "wpa_mode": "wpa2",
                "wpa_enc": "ccmp",
                "networkconf_id": "lan",
                "x_passphrase": "synthetic-passphrase",
            }
        ],
        "rest/user": [
            {
                "mac": "aa:bb:cc:00:00:99",
                "use_fixedip": True,
                "fixed_ip": "192.0.2.50",
                "name": "Printer",
                "note": "synthetic-note",
                "local_dns_record_enabled": True,
                "local_dns_record": "printer.home.arpa",
            },
            {"mac": "aa:bb:cc:00:00:98", "use_fixedip": False, "name": "Phone"},
        ],
    }
    requested = []

    def handle(request):
        assert request.method == "GET"
        if "/api/s/d/" in request.url.path:
            path = request.url.path.split("/api/s/d/", 1)[1]
            requested.append("internal:" + path)
            return httpx.Response(200, json={"data": internal[path]})
        path = request.url.path.split("/integration/v1/", 1)[1]
        requested.append(path)
        return httpx.Response(200, json=responses[path])

    snapshot = read_unifi_inventory(
        UniFiConfig("https://console.invalid", "synthetic-key"),
        transport=httpx.MockTransport(handle),
    )

    assert f"sites/{SITE_ID}/devices/ap" not in requested
    assert snapshot.port_config_error == ""
    uplink, disabled = snapshot.port_configs
    assert (uplink.device_id, uplink.name, uplink.summary()) == (
        "sw",
        "Uplink",
        "tagged-all, native 1",
    )
    assert (disabled.enabled, disabled.summary()) == (False, "disabled")
    assert (uplink.speed_mbps, uplink.full_duplex) == (10000, True)
    assert disabled.speed_mbps is None
    assert "synthetic-secret" not in repr(snapshot)
    assert "synthetic-passphrase" not in repr(snapshot)
    assert "synthetic-note" not in repr(snapshot)
    (sfp,) = snapshot.sfps
    assert (sfp.device_id, sfp.port_idx, sfp.part, sfp.serial) == (
        "sw",
        1,
        "UF-MM-10G",
        "SYNTH-SFP-1",
    )
    (pool,) = snapshot.dhcp_ranges
    assert (pool.vlan_id, pool.start, pool.end) == (1, "192.0.2.100", "192.0.2.200")
    (wlan,) = snapshot.wlans
    assert (wlan.ssid, wlan.security, wlan.vlan_id) == ("Synthetic WLAN", "wpapsk", 1)
    (reservation,) = snapshot.reservations
    assert (reservation.ip_address, reservation.name, reservation.dns_name) == (
        "192.0.2.50",
        "Printer",
        "printer.home.arpa",
    )
    assert reservation.mac_address == "AA:BB:CC:00:00:99"
    assert snapshot.client_error == ""
    first, second = snapshot.ports
    assert (first.device_id, first.idx, first.connector) == ("sw", 1, "RJ45")
    assert (first.link_state, first.speed_mbps) == ("UP", 100)
    assert (first.poe_standard, first.poe_type, first.poe_enabled) == (
        "802.3at",
        2,
        True,
    )
    assert (second.idx, second.link_state, second.speed_mbps) == (2, "DOWN", 0)
    assert second.poe_enabled is None


@pytest.mark.parametrize(
    "ports",
    [
        "not-a-list",
        [{"state": "UP"}],
        [{"idx": 1}, {"idx": 1}],
    ],
)
def test_unifi_port_lists_are_validated(ports):
    from unifi2netbox.inventory import _normalize_unifi_ports

    with pytest.raises(InventoryError):
        _normalize_unifi_ports("sw", {"interfaces": {"ports": ports}})


def test_unifi_networks_carry_vlan_and_subnet():
    from unifi2netbox.inventory import _normalize_unifi_network

    row = {"id": "n1", "name": "IoT", "vlanId": 20, "enabled": True}
    detail = {"ipv4Configuration": {"hostIpAddress": "10.0.20.1", "prefixLength": 24}}

    network = _normalize_unifi_network(row, detail)

    assert (network.name, network.vlan_id, network.subnet, network.gateway_ip) == (
        "IoT",
        20,
        "10.0.20.0/24",
        "10.0.20.1",
    )
    assert _normalize_unifi_network(row, {}).subnet == ""
    assert _normalize_unifi_network({"id": "n2", "name": "x"}, {}) is None
    bad = {"ipv4Configuration": {"hostIpAddress": "nope", "prefixLength": 24}}
    assert _normalize_unifi_network(row, bad).subnet == ""


def test_netbox_ipam_rows_are_normalized():
    from unifi2netbox.inventory import (
        _normalize_netbox_prefix,
        _normalize_netbox_vlan,
        _normalize_netbox_vlan_group,
    )

    group = _normalize_netbox_vlan_group(
        {
            "id": 3,
            "name": "UniFi Home",
            "slug": "unifi-home",
            "scope_type": "dcim.site",
            "scope_id": 7,
        }
    )
    vlan = _normalize_netbox_vlan(
        {
            "id": 9,
            "vid": 20,
            "name": "IoT",
            "group": {"id": 3},
            "status": {"value": "active"},
        }
    )
    prefix = _normalize_netbox_prefix(
        {
            "id": 5,
            "prefix": "10.0.20.0/24",
            "vlan": {"id": 9},
            "scope_type": "dcim.site",
            "scope_id": 7,
            "status": {"value": "active"},
        }
    )

    assert (group.source_id, group.scope_type, group.scope_id) == (
        "3",
        "dcim.site",
        "7",
    )
    assert (vlan.vid, vlan.group_id, vlan.status) == (20, "3", "active")
    assert (prefix.prefix, prefix.vlan_id, prefix.scope_id) == (
        "10.0.20.0/24",
        "9",
        "7",
    )
    assert _normalize_netbox_vlan({"id": 1, "vid": "20"}) is None


def test_netbox_inventory_survives_missing_ipam_permission(netbox_transport):
    _, responses = netbox_transport
    responses[5] = (403, {"detail": "You do not have permission."})
    del responses[6:8]

    snapshot = read_netbox_inventory(
        NetBoxConfig("https://netbox.invalid", "synthetic-token"),
        page_size=1,
    )

    assert [device.source_id for device in snapshot.devices] == ["7", "8"]
    assert snapshot.vlans == ()
    assert snapshot.ipam_error.startswith("NetBox IPAM could not be read")


def test_port_config_is_skipped_for_unvalidated_versions(unifi_api):
    calls, _, transport = unifi_api
    snapshot = read_unifi_inventory(
        UniFiConfig("https://console.invalid", "synthetic-key", site=SITE_ID),
        page_size=1,
        transport=transport,
    )

    assert not any("/api/s/" in str(call) for call in calls)

    assert snapshot.port_configs == ()
    assert "validated UniFi Network 11.0" in snapshot.port_config_error
    assert "10.6.100" in snapshot.port_config_error


def test_port_config_failure_keeps_the_official_inventory():
    from unifi2netbox.inventory import _read_port_configs

    def handle(request):
        return httpx.Response(403, json={"secret": "synthetic-secret"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        details = _read_port_configs(
            client,
            UniFiConfig("https://console.invalid", "synthetic-key"),
            "11.0.99",
            "d",
            [],
        )

    assert details.port_configs == () and details.links == ()
    assert details.sfps == () and details.wlans == ()
    assert details.error == "Port configuration unavailable: permission denied."


def test_client_read_failure_keeps_port_configuration():
    from unifi2netbox.inventory import _read_port_configs

    def handle(request):
        path = request.url.path.split("/api/s/d/", 1)[1]
        if path in {"rest/wlanconf", "rest/user"}:
            return httpx.Response(403, json={})
        return httpx.Response(200, json={"data": []})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        details = _read_port_configs(
            client,
            UniFiConfig("https://console.invalid", "synthetic-key"),
            "11.0.99",
            "d",
            [],
        )

    assert details.error == ""
    assert details.wlans == () and details.reservations == ()
    assert details.client_error == (
        "Wireless LANs and reservations unavailable: permission denied."
    )


def test_netbox_interfaces_carry_vlan_assignments_and_lag():
    from unifi2netbox.inventory import _normalize_netbox_interface

    interface = _normalize_netbox_interface(
        {
            "id": 10,
            "device": {"id": 1},
            "name": "Port 1",
            "type": {"value": "1000base-t"},
            "mode": {"value": "tagged"},
            "untagged_vlan": {"id": 5},
            "tagged_vlans": [{"id": 11}, {"id": 7}, {"id": 7}, "bad"],
            "lag": {"id": 12},
        }
    )

    assert (interface.mode, interface.untagged_vlan_id) == ("tagged", "5")
    assert interface.tagged_vlan_ids == ("7", "11")
    assert interface.lag_id == "12"


def test_netbox_interfaces_carry_their_cable_and_interface_peers():
    from unifi2netbox.inventory import _normalize_netbox_interface

    cabled = _normalize_netbox_interface(
        {
            "id": 10,
            "device": {"id": 1},
            "name": "Port 1",
            "cable": {"id": 4},
            "link_peers_type": "dcim.interface",
            "link_peers": [{"id": 22}],
        }
    )
    to_port = _normalize_netbox_interface(
        {
            "id": 11,
            "device": {"id": 1},
            "name": "Port 2",
            "cable": {"id": 5},
            "link_peers_type": "dcim.frontport",
            "link_peers": [{"id": 3}],
        }
    )

    assert (cabled.cable_id, cabled.link_peer_ids) == ("4", ("22",))
    assert (to_port.cable_id, to_port.link_peer_ids) == ("5", ())


def test_netbox_inventory_items_are_optional(netbox_transport):
    _, responses = netbox_transport
    responses[8] = (403, {"detail": "You do not have permission."})

    snapshot = read_netbox_inventory(
        NetBoxConfig("https://netbox.invalid", "synthetic-token"),
        page_size=1,
    )

    assert [device.source_id for device in snapshot.devices] == ["7", "8"]
    assert snapshot.inventory_items == ()
    assert snapshot.inventory_item_error.startswith(
        "NetBox inventory items could not be read"
    )


def test_netbox_inventory_items_are_normalized():
    from unifi2netbox.inventory import InventoryItem, _normalize_netbox_inventory_item

    assert _normalize_netbox_inventory_item(
        {
            "id": 4,
            "device": {"id": 9},
            "name": "Disk 1",
            "part_id": "WD80",
            "serial": " S1 ",
            "description": "HDD",
        }
    ) == InventoryItem("4", "9", "Disk 1", "WD80", "S1", "HDD")
    assert _normalize_netbox_inventory_item({"id": 4, "name": "x"}) is None
