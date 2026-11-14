"""Cable suggestions from synthetic UniFi link evidence."""

from unifi2netbox.cables import (
    CONFLICT,
    CREATE,
    IN_SYNC,
    REFERENCE,
    build_cable_plan,
    select_cable,
)
from unifi2netbox.inventory import InventoryInterface, InventoryPort
from unifi2netbox.links import LLDP, UPLINK, InventoryLink

NAMES = {"udm": "UDM", "rps": "RPS", "sw": "SW", "ap": "AP"}
NETBOX = {"udm": "1", "rps": "2", "ap": "4"}
PORTS = (
    InventoryPort("udm", 4, "RJ45", 1000),
    InventoryPort("udm", 5, "RJ45", 1000),
    InventoryPort("rps", 1, "RJ45", 1000),
)


def interfaces(**cables):
    """NetBox interfaces; keyword ``iN=(cable, peer)`` adds cable state."""
    rows = [
        InventoryInterface("i4", "1", "port.4", "1000base-t"),
        InventoryInterface("i5", "1", "port.5", "1000base-t"),
        InventoryInterface("r1", "2", "eth0", "1000base-t"),
        InventoryInterface("a1", "4", "eth0", "1000base-t"),
        InventoryInterface("a2", "4", "wifi0", "ieee802.11ax"),
    ]
    out = []
    for row in rows:
        if row.source_id in cables:
            cable, peer = cables[row.source_id]
            row = InventoryInterface(
                row.source_id,
                row.device_id,
                row.name,
                row.type,
                cable_id=cable,
                link_peer_ids=(peer,) if peer else (),
            )
        out.append(row)
    return tuple(out)


def plan(links, items=None):
    return build_cable_plan(links, NAMES, NETBOX, PORTS, items or interfaces())


RPS_UPLINK = InventoryLink("rps", 1, "udm", 5, UPLINK)
UDM_LLDP = InventoryLink("udm", 5, "rps", None, LLDP)


def test_two_agreeing_observations_become_a_preselected_cable():
    result = plan((RPS_UPLINK, UDM_LLDP))

    (row,) = result.rows
    assert row.action == CREATE and row.selected
    assert (row.a.interface_id, row.b.interface_id) == ("r1", "i5")
    assert row.label == "RPS eth0 ↔ UDM port.5"
    assert row.sources == ("LLDP from UDM", "Uplink from RPS")
    assert result.operation_count == 1


def test_single_observation_is_offered_but_not_selected():
    (row,) = plan((RPS_UPLINK,)).rows

    assert row.action == CREATE and not row.selected
    assert any("one observation" in note for note in row.notes)


def test_existing_cable_between_the_same_interfaces_is_in_sync():
    items = interfaces(i5=("9", "r1"), r1=("9", "i5"))

    (row,) = plan((RPS_UPLINK, UDM_LLDP), items).rows

    assert row.action == IN_SYNC


def test_other_cable_is_never_replaced():
    items = interfaces(i5=("9", "x"))

    (row,) = plan((RPS_UPLINK, UDM_LLDP), items).rows

    assert row.action == CONFLICT and not row.selected
    assert any("never replaced" in note for note in row.notes)


def test_disagreeing_ports_are_a_conflict():
    (row,) = plan((RPS_UPLINK, InventoryLink("udm", 4, "rps", 1, LLDP))).rows

    assert row.action == CONFLICT
    assert "different ports" in row.notes[0]


def test_port_claimed_by_two_neighbors_is_a_conflict():
    rows = plan((RPS_UPLINK, InventoryLink("ap", 1, "udm", 5, UPLINK))).rows

    assert {row.action for row in rows} == {CONFLICT}
    assert all("more than one neighbor" in " ".join(row.notes) for row in rows)


def test_unmatched_device_is_reference_only():
    (row,) = plan((InventoryLink("sw", 3, "udm", 4, UPLINK),)).rows

    assert row.action == REFERENCE
    assert "SW: not matched to a NetBox device." in row.notes


def test_device_without_port_data_uses_its_only_physical_interface():
    (row,) = plan(
        (
            InventoryLink("ap", None, "udm", 4, UPLINK),
            InventoryLink("udm", 4, "ap", None, LLDP),
        )
    ).rows

    assert row.action == CREATE
    assert {row.a.interface_id, row.b.interface_id} == {"a1", "i4"}


def test_unknown_port_on_a_device_with_port_data_is_reference_only():
    (row,) = plan((InventoryLink("rps", 1, "udm", None, UPLINK),)).rows

    assert row.action == REFERENCE
    assert any("port number is unknown" in note for note in row.notes)


def test_selection_and_blocker():
    result = plan((RPS_UPLINK, UDM_LLDP))
    key = result.rows[0].key

    assert select_cable(result, key, False).operation_count == 0
    assert (
        build_cable_plan((), NAMES, NETBOX, PORTS, (), port_config_error="x").blocker
        == "x"
    )
