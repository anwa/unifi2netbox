"""Link evidence from internal UniFi payloads (synthetic)."""

from unifi2netbox.links import LLDP, UPLINK, InventoryLink, read_links

MACS = {"aa0000000001": "sw", "aa0000000002": "udm", "aa0000000003": "ap"}


def test_uplink_and_lldp_become_links_by_device_id():
    devices = [
        {
            "mac": "AA:00:00:00:00:01",
            "uplink": {
                "type": "wire",
                "uplink_mac": "aa:00:00:00:00:02",
                "uplink_remote_port": 11,
                "port_idx": 29,
            },
            "lldp_table": [
                {
                    "local_port_idx": 29,
                    "chassis_id": "aa:00:00:00:00:02",
                    "port_id": "local Port 11",
                },
                {
                    "local_port_idx": 3,
                    "chassis_id": "aa:00:00:00:00:03",
                    "port_id": "aa:00:00:00:00:03",
                },
            ],
        }
    ]

    assert read_links(devices, MACS) == (
        InventoryLink("sw", 3, "ap", None, LLDP),
        InventoryLink("sw", 29, "udm", 11, LLDP),
        InventoryLink("sw", 29, "udm", 11, UPLINK),
    )


def test_unknown_neighbors_wireless_and_bad_entries_are_ignored():
    devices = [
        {
            "mac": "aa:00:00:00:00:01",
            "uplink": {
                "type": "wireless",
                "uplink_mac": "aa:00:00:00:00:02",
                "uplink_remote_port": 1,
            },
            "lldp_table": [
                {
                    "local_port_idx": 1,
                    "chassis_id": "ff:ff:ff:ff:ff:ff",
                    "port_id": "Port 1",
                },
                {
                    "local_port_idx": 2,
                    "chassis_id": "aa:00:00:00:00:02",
                    "is_wired": False,
                },
                {"local_port_idx": 0, "chassis_id": "aa:00:00:00:00:02"},
                "bad",
            ],
        },
        {"mac": "ff:ff:ff:ff:ff:ff", "uplink": {"type": "wire"}},
    ]

    assert read_links(devices, MACS) == ()


def test_uplink_without_local_port_keeps_it_open():
    devices = [
        {
            "mac": "aa:00:00:00:00:03",
            "uplink": {
                "type": "wire",
                "uplink_mac": "aa:00:00:00:00:01",
                "uplink_remote_port": 2,
            },
        }
    ]

    assert read_links(devices, MACS) == (InventoryLink("ap", None, "sw", 2, UPLINK),)
