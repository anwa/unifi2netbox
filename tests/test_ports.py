import pytest

from unifi2netbox.inventory import InventoryInterface, InventoryPort
from unifi2netbox.ports import (
    COPPER,
    OPTICAL,
    connector_family,
    interface_family,
    interface_speed_mbps,
    match_ports,
)


def port(idx, connector="RJ45", speed=1000, poe=""):
    return InventoryPort("sw", idx, connector, speed, "DOWN", 0, poe, 2 if poe else 0)


def interface(name, kind="1000base-t", poe_mode="", mgmt=False):
    return InventoryInterface(
        f"if-{name}", "7", name, kind, mgmt_only=mgmt, poe_mode=poe_mode
    )


@pytest.mark.parametrize(
    ("value", "family"),
    [("RJ45", COPPER), ("SFP", OPTICAL), ("SFPPLUS", OPTICAL), ("SFP28", OPTICAL)],
)
def test_connector_families(value, family):
    assert connector_family(value) == family


@pytest.mark.parametrize(
    ("value", "family", "speed"),
    [
        ("1000base-t", COPPER, 1000),
        ("2.5gbase-t", COPPER, 2500),
        ("100base-tx", COPPER, 100),
        ("10gbase-x-sfpp", OPTICAL, 10000),
        ("25gbase-x-sfp28", OPTICAL, 25000),
        ("1000base-x-sfp", OPTICAL, 1000),
        ("ieee802.11ax", "", 0),
        ("virtual", "", 0),
    ],
)
def test_interface_families_and_speeds(value, family, speed):
    assert interface_family(value) == family
    assert interface_speed_mbps(value) == speed


def test_ports_pair_with_template_interfaces_per_family_and_number():
    ports = [port(i) for i in range(1, 11)] + [
        port(11, "SFPPLUS", 10000),
        port(12, "SFPPLUS", 10000),
    ]
    interfaces = [interface(f"Port {i}") for i in range(10, 0, -1)] + [
        interface("SFP+ 2", "10gbase-x-sfpp"),
        interface("SFP+ 1", "10gbase-x-sfpp"),
        interface("WLAN", "ieee802.11ax"),
    ]

    matches = match_ports(ports, interfaces)

    pairs = [(m.port.idx, m.interface.name) for m in matches]
    assert pairs[0] == (1, "Port 1")
    assert pairs[9] == (10, "Port 10")
    assert pairs[10:] == [(11, "SFP+ 1"), (12, "SFP+ 2")]
    assert all(m.matched and not m.notes for m in matches)


def test_unmatched_ports_and_interfaces_are_reported():
    matches = match_ports(
        [port(1), port(2)],
        [interface("Port 1"), interface("SFP+ 1", "10gbase-x-sfpp")],
    )

    notes = {m.port.idx if m.port else m.interface.name: m.notes for m in matches}
    assert notes[2] == ("No NetBox interface for this UniFi port.",)
    assert notes["SFP+ 1"] == ("No UniFi port for this NetBox interface.",)


def test_speed_and_poe_differences_become_notes():
    matches = match_ports(
        [port(1, speed=2500, poe="802.3at"), port(2)],
        [interface("Port 1"), interface("Port 2", poe_mode="pse")],
    )

    assert matches[0].notes == (
        "UniFi port supports 2.5 Gbit/s, NetBox type 1000base-t is 1 Gbit/s.",
        "UniFi port supplies PoE; NetBox interface has no PSE mode.",
    )
    assert matches[1].notes == ("NetBox marks PoE supply; UniFi port has no PoE.",)


def test_management_interfaces_and_unknown_connectors_are_kept_apart():
    matches = match_ports(
        [port(1), port(2, "XYZ")],
        [interface("Port 1"), interface("MGMT", mgmt=True)],
    )

    assert [(m.port.idx if m.port else None) for m in matches] == [1, 2]
    assert matches[1].notes == ("Unknown connector 'XYZ'.",)
    assert all(m.interface is None or m.interface.name != "MGMT" for m in matches)


def test_mixed_optical_templates_pair_by_exact_connector_kind():
    ports = [port(i, "SFPPLUS", 10000) for i in range(1, 9)]
    interfaces = [interface(f"SFP+ {i}", "10gbase-x-sfpp") for i in range(1, 29)] + [
        interface(f"SFP28 {i}", "25gbase-x-sfp28") for i in range(1, 5)
    ]

    matches = match_ports(ports, interfaces)

    paired = [(m.port.idx, m.interface.name) for m in matches if m.matched]
    assert paired == [(i, f"SFP+ {i}") for i in range(1, 9)]
    assert all(not m.notes for m in matches if m.matched)
    leftovers = [m.interface.name for m in matches if m.port is None]
    assert leftovers[:2] == ["SFP+ 9", "SFP+ 10"]
    assert leftovers[-1] == "SFP28 4"
    assert len(leftovers) == 24


def test_leftover_optical_ports_pair_across_kinds_with_speed_note():
    matches = match_ports(
        [port(1, "SFPPLUS", 10000)], [interface("SFP 1", "1000base-x-sfp")]
    )

    assert matches[0].matched
    assert "NetBox type 1000base-x-sfp is 1 Gbit/s" in matches[0].notes[0]


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        ("1000base-t", "RJ45"),
        ("1000base-x-sfp", "SFP"),
        ("10gbase-x-sfpp", "SFPPLUS"),
        ("25gbase-x-sfp28", "SFP28"),
        ("100gbase-x-qsfp28", "QSFP"),
        ("virtual", ""),
    ],
)
def test_interface_kinds(value, kind):
    from unifi2netbox.ports import interface_kind

    assert interface_kind(value) == kind
