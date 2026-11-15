from unifi2netbox.details import (
    InventoryDhcpRange,
    InventoryReservation,
    InventorySfp,
    InventoryWlan,
    network_vlans,
    read_dhcp_ranges,
    read_reservations,
    read_sfps,
    read_wlans,
)
from unifi2netbox.inventory import (
    InventoryCustomField,
    InventoryDevice,
    InventoryIpAddress,
    InventorySnapshot,
    InventorySource,
    _normalize_netbox_custom_field,
    _normalize_netbox_ip_address,
    _normalize_netbox_ip_range,
    _normalize_netbox_wireless_lan,
    _normalize_unifi_device,
    normalize_netbox_device,
)
from unifi2netbox.port_config import allowed_profiles, resolve_port_configs
from unifi2netbox.snapshots import _decode, _encode

NETWORKS = [
    {"_id": "lan", "name": "Default", "purpose": "corporate"},
    {
        "_id": "iot",
        "name": "IoT",
        "purpose": "corporate",
        "vlan_enabled": True,
        "vlan": 20,
    },
    {
        "_id": "guest",
        "name": "Guest",
        "purpose": "guest",
        "vlan_enabled": True,
        "vlan": 40,
    },
    {"_id": "wan", "name": "WAN", "purpose": "wan", "x_wan_password": "secret"},
]


def test_network_vlans_maps_lan_networks_only():
    assert network_vlans(NETWORKS) == {
        "lan": (1, "Default"),
        "iot": (20, "IoT"),
        "guest": (40, "Guest"),
    }


def test_sfps_need_a_present_module_and_a_known_device():
    devices = [
        {
            "mac": "aa:bb:cc:00:00:01",
            "port_table": [
                {
                    "port_idx": 2,
                    "sfp_found": True,
                    "sfp_part": "UDC-1",
                    "sfp_rev": "A1",
                },
                {"port_idx": 1, "sfp_found": False, "sfp_part": "old"},
                {"port_idx": 3, "sfp_found": "yes"},
                {"port_idx": 0, "sfp_found": True},
            ],
        },
        {
            "mac": "aa:bb:cc:00:00:02",
            "port_table": [{"port_idx": 1, "sfp_found": True}],
        },
    ]

    assert read_sfps(devices, {"aabbcc000001": "sw"}) == (
        InventorySfp("sw", 2, part="UDC-1", revision="A1"),
    )


def test_dhcp_ranges_need_enabled_server_and_valid_order():
    rows = [
        {
            **NETWORKS[1],
            "dhcpd_enabled": True,
            "dhcpd_start": "10.0.20.6",
            "dhcpd_stop": "10.0.20.254",
        },
        {
            **NETWORKS[0],
            "dhcpd_enabled": False,
            "dhcpd_start": "10.0.0.6",
            "dhcpd_stop": "10.0.0.9",
        },
        {
            **NETWORKS[2],
            "dhcpd_enabled": True,
            "dhcpd_start": "10.0.40.9",
            "dhcpd_stop": "10.0.40.6",
        },
        {
            **NETWORKS[3],
            "dhcpd_enabled": True,
            "dhcpd_start": "1.1.1.1",
            "dhcpd_stop": "1.1.1.2",
        },
    ]

    assert read_dhcp_ranges(rows) == (
        InventoryDhcpRange(20, "IoT", "10.0.20.6", "10.0.20.254"),
    )


def test_wlans_never_carry_passphrases():
    rows = [
        {
            "_id": "w2",
            "name": "Guest WiFi",
            "enabled": False,
            "security": "open",
            "networkconf_id": "guest",
            "is_guest": True,
            "x_passphrase": "synthetic-passphrase",
        },
        {"_id": "w1", "name": "Home", "networkconf_id": "unknown", "hide_ssid": True},
        {"_id": "w3", "name": ""},
    ]

    wlans = read_wlans(rows, network_vlans(NETWORKS))

    assert wlans == (
        InventoryWlan("w2", "Guest WiFi", False, "open", vlan_id=40, guest=True),
        InventoryWlan("w1", "Home", vlan_id=None, hidden=True),
    )
    assert "synthetic-passphrase" not in repr(wlans)


def test_reservations_keep_only_fixed_ips_and_drop_duplicates():
    rows = [
        {
            "mac": "aa:bb:cc:00:00:03",
            "use_fixedip": True,
            "fixed_ip": "10.0.0.30",
            "hostname": "nas",
        },
        {
            "mac": "AA-BB-CC-00-00-01",
            "use_fixedip": True,
            "fixed_ip": "10.0.0.10",
            "name": "Printer",
            "local_dns_record_enabled": False,
            "local_dns_record": "hidden.example",
        },
        {"mac": "aa:bb:cc:00:00:04", "use_fixedip": True, "fixed_ip": "10.0.0.40"},
        {"mac": "aa:bb:cc:00:00:05", "use_fixedip": True, "fixed_ip": "10.0.0.40"},
        {"mac": "aa:bb:cc:00:00:06", "use_fixedip": True, "fixed_ip": "nope"},
        {"mac": "aa:bb:cc:00:00:07", "use_fixedip": False, "fixed_ip": "10.0.0.70"},
    ]

    assert read_reservations(rows) == (
        InventoryReservation("AA:BB:CC:00:00:01", "10.0.0.10", name="Printer"),
        InventoryReservation("AA:BB:CC:00:00:03", "10.0.0.30", hostname="nas"),
    )


def test_fixed_speed_comes_from_override_then_profile():
    profiles = allowed_profiles(
        [
            {
                "_id": "p1",
                "name": "Fixed",
                "forward": "native",
                "autoneg": False,
                "speed": 1000,
                "full_duplex": True,
            },
            {
                "_id": "p2",
                "name": "Auto",
                "forward": "native",
                "autoneg": True,
                "speed": None,
            },
        ]
    )
    networks = {}
    device = {
        "mac": "aa:bb:cc:00:00:01",
        "port_table": [
            {"port_idx": 1, "forward": "all"},
            {"port_idx": 2, "portconf_id": "p1"},
            {"port_idx": 3, "portconf_id": "p1"},
            {"port_idx": 4, "portconf_id": "p2"},
            {"port_idx": 5, "forward": "all"},
        ],
        "port_overrides": [
            {"port_idx": 1, "autoneg": False, "speed": 10000, "full_duplex": True},
            {"port_idx": 3, "autoneg": True},
            {"port_idx": 5, "autoneg": False, "speed": 0},
        ],
    }

    configs = resolve_port_configs([device], profiles, networks, {"aabbcc000001": "sw"})

    assert [(c.idx, c.speed_mbps, c.full_duplex) for c in configs] == [
        (1, 10000, True),
        (2, 1000, True),
        (3, None, None),
        (4, None, None),
        (5, None, None),
    ]


def test_device_ip_and_firmware_from_both_sources():
    unifi = _normalize_unifi_device(
        {
            "id": "d1",
            "name": "sw",
            "ipAddress": "10.0.0.2",
            "firmwareVersion": "7.2.123",
        },
        "Home",
    )
    bad = _normalize_unifi_device({"id": "d2", "ipAddress": "fe80::1"}, "Home")
    netbox = normalize_netbox_device(
        {
            "id": 7,
            "name": "sw",
            "primary_ip4": {"id": 31, "address": "10.0.0.2/24"},
            "custom_fields": {"firmware": "7.1.0", "other": 1},
        }
    )
    empty = normalize_netbox_device({"id": 8, "primary_ip4": None, "custom_fields": {}})

    assert (unifi.ip_address, unifi.firmware) == ("10.0.0.2", "7.2.123")
    assert bad.ip_address == ""
    assert (netbox.ip_address, netbox.primary_ip_id, netbox.firmware) == (
        "10.0.0.2",
        "31",
        "7.1.0",
    )
    assert (empty.ip_address, empty.primary_ip_id, empty.firmware) == ("", "", "")


def test_netbox_detail_rows_are_normalized():
    address = _normalize_netbox_ip_address(
        {
            "id": 5,
            "address": "10.0.0.10/24",
            "status": {"value": "reserved"},
            "dns_name": "printer.home.arpa",
            "assigned_object_type": "dcim.interface",
            "assigned_object_id": 12,
        }
    )
    ip_range = _normalize_netbox_ip_range(
        {"id": 6, "start_address": "10.0.0.100/24", "end_address": "10.0.0.200/24"}
    )
    wlan = _normalize_netbox_wireless_lan(
        {
            "id": 7,
            "ssid": "Home",
            "vlan": {"id": 9},
            "auth_type": {"value": "wpa-personal"},
        }
    )
    field = _normalize_netbox_custom_field(
        {
            "id": 8,
            "name": "firmware",
            "type": {"value": "text"},
            "object_types": ["dcim.device"],
        }
    )

    assert address == InventoryIpAddress(
        "5", "10.0.0.10/24", "reserved", "printer.home.arpa", "", "dcim.interface", "12"
    )
    assert (ip_range.start_address, ip_range.end_address) == (
        "10.0.0.100/24",
        "10.0.0.200/24",
    )
    assert (wlan.ssid, wlan.vlan_id, wlan.auth_type) == ("Home", "9", "wpa-personal")
    assert field == InventoryCustomField("8", "firmware", "text", ("dcim.device",))
    assert _normalize_netbox_ip_address({"id": 1}) is None


def test_snapshot_round_trip_keeps_details_and_reads_old_snapshots():
    snapshot = InventorySnapshot(
        source=InventorySource.UNIFI_NETWORK,
        captured_at="2026-11-15T00:00:00+00:00",
        devices=(InventoryDevice("d1", "sw", ip_address="10.0.0.2", firmware="7.2"),),
        sfps=(InventorySfp("d1", 1, part="UDC-1"),),
        dhcp_ranges=(InventoryDhcpRange(1, "Default", "10.0.0.6", "10.0.0.9"),),
        wlans=(InventoryWlan("w1", "Home", vlan_id=1),),
        reservations=(InventoryReservation("AA:BB:CC:00:00:01", "10.0.0.10"),),
        client_error="",
        custom_fields=(
            InventoryCustomField("8", "firmware", "text", ("dcim.device",)),
        ),
        address_error="synthetic",
    )

    assert _decode(_encode(snapshot)) == snapshot
    old = _decode(
        '{"source": "netbox", "captured_at": "x",'
        ' "devices": [{"source_id": "1", "name": "a"}]}'
    )
    assert old.sfps == () and old.custom_fields == () and old.address_error == ""
    assert old.devices[0].firmware == ""
