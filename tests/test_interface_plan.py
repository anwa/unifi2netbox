"""Interface configuration plan from UniFi port config (synthetic)."""

from unifi2netbox.interface_plan import (
    ENABLED,
    MODE,
    TAGGED_VLANS,
    UNTAGGED,
    DevicePair,
    build_interface_plan,
    select_interface,
)
from unifi2netbox.inventory import InventoryInterface, InventoryPort, InventoryVlan
from unifi2netbox.port_config import InventoryPortConfig

PAIR = DevicePair("unifi_network:a->netbox:1", "sw-a", "a", "1")
VLANS = (
    InventoryVlan("101", 1, "Default", "9"),
    InventoryVlan("120", 20, "IoT", "9"),
    InventoryVlan("130", 30, "Cams", "9"),
    InventoryVlan("999", 20, "Other group", "8"),
)


def plan_for(config, interface=None, *, group="9", vlans=VLANS, error=""):
    interface = interface or InventoryInterface("10", "1", "Port 1", "1000base-t")
    return build_interface_plan(
        (PAIR,),
        (InventoryPort("a", 1, "RJ45", 1000),),
        (interface,),
        (config,) if config else (),
        vlans,
        vlan_group_id=group,
        vlan_group_name="UniFi Home",
        port_config_error=error,
    )


def config(**values):
    return InventoryPortConfig("a", 1, "Port 1", **values)


def test_access_port_plans_mode_and_untagged_vlan():
    plan = plan_for(config(enabled=True, mode="access", native_vid=20))

    (row,) = plan.rows
    assert row.key == "interface:10" and row.label == "sw-a Port 1"
    assert [c.field for c in row.changes] == [MODE, UNTAGGED]
    assert row.change(UNTAGGED).desired == "120"
    assert row.change(UNTAGGED).desired_label == "VLAN 20 IoT"
    assert row.selected_fields == (MODE, UNTAGGED)
    assert plan.operation_count == 1


def test_tagged_port_lists_vlans_and_tagged_all_stays_without_list():
    tagged = plan_for(config(mode="tagged", native_vid=1, tagged_vids=(30, 20)))
    every = plan_for(config(mode="tagged-all", native_vid=1))

    assert tagged.rows[0].change(TAGGED_VLANS).desired == ("120", "130")
    assert every.rows[0].change(TAGGED_VLANS) is None
    assert every.rows[0].change(MODE).desired == "tagged-all"


def test_matching_interface_is_in_sync():
    interface = InventoryInterface(
        "10", "1", "Port 1", "1000base-t", True, mode="access", untagged_vlan_id="120"
    )

    (row,) = plan_for(
        config(enabled=True, mode="access", native_vid=20), interface
    ).rows

    assert row.in_sync and row.selected_fields == ()


def test_disabled_port_only_changes_enabled():
    interface = InventoryInterface(
        "10", "1", "Port 1", "1000base-t", True, mode="access", untagged_vlan_id="120"
    )

    (row,) = plan_for(config(enabled=False, mode="disabled"), interface).rows

    assert [(c.field, c.desired) for c in row.changes] == [(ENABLED, False)]


def test_leftover_tagged_vlans_are_cleared_outside_tagged_mode():
    interface = InventoryInterface(
        "10", "1", "Port 1", "1000base-t", mode="tagged", tagged_vlan_ids=("130",)
    )

    (row,) = plan_for(config(mode="access", native_vid=20), interface).rows

    assert row.change(TAGGED_VLANS).desired == ()


def test_missing_vlans_and_group_are_notes_not_writes():
    no_group = plan_for(config(mode="access", native_vid=20), group="").rows[0]
    missing = plan_for(config(mode="tagged", native_vid=1, tagged_vids=(20, 77))).rows[
        0
    ]

    assert [c.field for c in no_group.changes] == [MODE]
    assert "write the networks first" in no_group.notes[0]
    assert missing.change(TAGGED_VLANS) is None
    assert any("77" in note for note in missing.notes)


def test_vlans_from_other_groups_are_never_used():
    vlans = (InventoryVlan("999", 20, "Other group", "8"),)

    (row,) = plan_for(config(mode="access", native_vid=20), vlans=vlans).rows

    assert row.change(UNTAGGED) is None
    assert any("VLAN 20 is not in NetBox" in note for note in row.notes)


def test_unknown_config_and_missing_values_never_clear_netbox():
    interface = InventoryInterface(
        "10", "1", "Port 1", "1000base-t", False, mode="access", untagged_vlan_id="5"
    )

    (row,) = plan_for(config(enabled=None, mode="unknown"), interface).rows

    assert row.changes == ()
    assert any("unknown" in note for note in row.notes)


def test_lag_is_noted_but_not_planned():
    (row,) = plan_for(config(mode="tagged-all", native_vid=1, lag_id=1)).rows

    assert any("LAG 1 is shown only" in note for note in row.notes)


def test_blocker_without_port_configuration():
    plan = plan_for(None, error="Port configuration unavailable: denied.")

    assert plan.rows == () and plan.blocker == "Port configuration unavailable: denied."


def test_vlan_fields_follow_the_mode_selection():
    plan = plan_for(config(mode="tagged", native_vid=1, tagged_vids=(20,)))
    key = plan.rows[0].key

    cleared = select_interface(plan, key, MODE, False)
    assert cleared.rows[0].selected_fields == ()
    picked = select_interface(cleared, key, TAGGED_VLANS, True)
    assert picked.rows[0].selected_fields == (MODE, TAGGED_VLANS)
    none = select_interface(picked, key, "all", False)
    assert none.operation_count == 0
