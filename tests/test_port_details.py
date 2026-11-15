"""Port details in the interface plan: description, speed, duplex, PoE (M11)."""

from unifi2netbox.interface_execute import execute_interface_plan, read_field
from unifi2netbox.interface_plan import (
    DESCRIPTION,
    DUPLEX,
    POE_MODE,
    POE_TYPE,
    SPEED,
    DevicePair,
    build_interface_plan,
    select_interface,
)
from unifi2netbox.inventory import InventoryInterface, InventoryPort
from unifi2netbox.port_config import InventoryPortConfig

PAIR = DevicePair("unifi_network:a->netbox:1", "sw-a", "a", "1")
PORT = InventoryPort("a", 1, "RJ45", 1000)
POE_PORT = InventoryPort("a", 1, "RJ45", 1000, poe_standard="802.3at", poe_type=2)


def plan_for(config, interface=None, port=PORT):
    interface = interface or InventoryInterface("10", "1", "Port 1", "1000base-t")
    return build_interface_plan(
        (PAIR,),
        (port,),
        (interface,),
        (config,),
        (),
        vlan_group_id="9",
        vlan_group_name="UniFi Home",
    )


def changes(plan):
    (row,) = plan.rows
    return {c.field: c.desired for c in row.changes}, row.selected_fields, row


def test_custom_port_name_becomes_the_description():
    values, selected, _ = changes(plan_for(InventoryPortConfig("a", 1, "NAS 10G")))
    assert values == {DESCRIPTION: "NAS 10G"} and selected == (DESCRIPTION,)
    for default in ("Port 1", "SFP+ 2", "sfp28 3", ""):
        values, _, _ = changes(plan_for(InventoryPortConfig("a", 1, default)))
        assert DESCRIPTION not in values


def test_other_netbox_description_is_shown_but_not_preselected():
    interface = InventoryInterface(
        "10", "1", "Port 1", "1000base-t", description="Hand written"
    )
    values, selected, row = changes(
        plan_for(InventoryPortConfig("a", 1, "NAS"), interface)
    )
    assert values[DESCRIPTION] == "NAS" and DESCRIPTION not in selected
    assert "replaced only when checked" in row.notes[-1]


def test_fixed_speed_and_duplex_only_without_autoneg():
    fixed = InventoryPortConfig("a", 1, "Port 1", speed_mbps=10000, full_duplex=True)
    values, selected, row = changes(plan_for(fixed))
    assert values == {SPEED: 10_000_000, DUPLEX: "full"}
    assert set(selected) == {SPEED, DUPLEX}
    assert row.change(SPEED).desired_label == "10 Gbps"
    auto, _, _ = changes(plan_for(InventoryPortConfig("a", 1, "Port 1")))
    assert SPEED not in auto and DUPLEX not in auto
    synced = InventoryInterface(
        "10", "1", "Port 1", "1000base-t", speed_kbps=10_000_000, duplex="full"
    )
    assert plan_for(fixed, synced).rows[0].in_sync


def test_poe_capability_fills_empty_values_and_keeps_other_ones():
    values, selected, _ = changes(
        plan_for(InventoryPortConfig("a", 1, "Port 1"), port=POE_PORT)
    )
    assert values == {POE_MODE: "pse", POE_TYPE: "type2-ieee802.3at"}
    assert set(selected) == {POE_MODE, POE_TYPE}

    netbox_pd = InventoryInterface(
        "10", "1", "Port 1", "1000base-t", poe_mode="pd", poe_type="type2-ieee802.3at"
    )
    values, selected, row = changes(
        plan_for(InventoryPortConfig("a", 1, "Port 1"), netbox_pd, POE_PORT)
    )
    assert values == {POE_MODE: "pse"} and selected == ()
    assert "device type" in row.notes[-1]

    same = InventoryInterface(
        "10", "1", "Port 1", "1000base-t", poe_mode="pse", poe_type="type2-ieee802.3at"
    )
    assert (
        plan_for(InventoryPortConfig("a", 1, "Port 1"), same, POE_PORT).rows[0].in_sync
    )


def test_poe_type_selects_and_follows_the_poe_mode():
    plan = plan_for(InventoryPortConfig("a", 1, "Port 1"), port=POE_PORT)
    key = plan.rows[0].key

    off = select_interface(plan, key, POE_MODE, False)
    assert off.rows[0].selected_fields == ()
    on = select_interface(off, key, POE_TYPE, True)
    assert set(on.rows[0].selected_fields) == {POE_MODE, POE_TYPE}


class FakeNetBox:
    def __init__(self, row):
        self.row = row
        self.updates = []

    def read_object(self, path):
        return self.row

    def update_object(self, path, payload):
        self.updates.append(payload)
        for key, value in payload.items():
            self.row[key] = (
                {"value": value} if key in (DUPLEX, POE_MODE, POE_TYPE) else value
            )


def test_new_fields_are_patched_drift_checked_and_verified():
    config = InventoryPortConfig("a", 1, "NAS", speed_mbps=1000, full_duplex=False)
    plan = plan_for(config, port=POE_PORT)
    backend = FakeNetBox(
        {
            "id": 10,
            "description": "",
            "speed": None,
            "duplex": None,
            "poe_mode": None,
            "poe_type": None,
        }
    )

    (outcome,) = execute_interface_plan(plan, backend)

    assert outcome.status == "success" and outcome.verification == "verified"
    assert backend.updates == [
        {
            DESCRIPTION: "NAS",
            SPEED: 1_000_000,
            DUPLEX: "half",
            POE_MODE: "pse",
            POE_TYPE: "type2-ieee802.3at",
        }
    ]
    drifted = FakeNetBox({"id": 10, "description": "Changed", "speed": None})
    (skipped,) = execute_interface_plan(plan, drifted)
    assert skipped.status == "skipped" and "description" in skipped.message
    assert drifted.updates == []


def test_read_field_normalizes_netbox_rows():
    assert read_field({"speed": None}, SPEED) == 0
    assert read_field({"duplex": {"value": "full"}}, DUPLEX) == "full"
    assert read_field({"description": " x "}, DESCRIPTION) == "x"
    assert read_field({}, POE_TYPE) == ""
