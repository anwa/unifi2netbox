from unifi2netbox.inventory import (
    InventoryNetwork,
    InventoryPrefix,
    InventorySite,
    InventoryVlan,
    InventoryVlanGroup,
)
from unifi2netbox.networks import (
    CONFLICT,
    CREATE,
    IN_SYNC,
    NONE,
    UPDATE,
    build_network_plan,
    group_name_for,
    select_network,
    slugify,
)

SITES = (InventorySite("7", "Home"),)
GROUP = InventoryVlanGroup("3", "UniFi Home", "unifi-home", "dcim.site", "7")


def network(source_id, name, vid, subnet="", enabled=True):
    return InventoryNetwork(source_id, name, vid, enabled, subnet)


def plan(networks, groups=(), vlans=(), prefixes=(), site="Home", ipam_error=""):
    return build_network_plan(
        tuple(networks),
        SITES,
        tuple(groups),
        tuple(vlans),
        tuple(prefixes),
        site_name=site,
        ipam_error=ipam_error,
    )


def row(result, name):
    return next(item for item in result.rows if item.name == name)


def test_empty_netbox_plans_group_vlans_and_prefixes():
    result = plan([network("n1", "IoT", 20, "10.0.20.0/24"), network("n2", "Lab", 30)])

    assert result.group.action == CREATE
    assert (result.group.name, result.group.slug) == ("UniFi Home", "unifi-home")
    iot = row(result, "IoT")
    assert (iot.vlan_action, iot.prefix_action) == (CREATE, CREATE)
    assert iot.vlan_selected and iot.prefix_selected
    lab = row(result, "Lab")
    assert (lab.vlan_action, lab.prefix_action) == (CREATE, NONE)
    assert result.operation_count == 4


def test_existing_objects_are_in_sync_or_completed():
    vlans = (
        InventoryVlan("9", 20, "Old name", "3"),
        InventoryVlan("10", 30, "Lab", "3"),
    )
    prefixes = (
        InventoryPrefix("5", "10.0.20.0/24", ""),
        InventoryPrefix("6", "10.0.30.0/24", "10"),
    )
    result = plan(
        [
            network("n1", "IoT", 20, "10.0.20.0/24"),
            network("n2", "Lab", 30, "10.0.30.0/24"),
        ],
        [GROUP],
        vlans,
        prefixes,
    )

    assert result.group.action == IN_SYNC
    iot = row(result, "IoT")
    assert (iot.vlan_action, iot.prefix_action) == (UPDATE, UPDATE)
    assert "NetBox VLAN is named 'Old name'." in iot.notes
    lab = row(result, "Lab")
    assert lab.category == IN_SYNC and not lab.selected
    assert result.operation_count == 2


def test_conflicts_are_never_selected():
    vlans = (InventoryVlan("9", 20, "IoT", "3"), InventoryVlan("99", 99, "Other", "3"))
    prefixes = (
        InventoryPrefix("5", "10.0.20.0/24", "99"),
        InventoryPrefix("6", "10.0.40.0/24"),
        InventoryPrefix("7", "10.0.40.0/24"),
    )
    result = plan(
        [
            network("n1", "IoT", 20, "10.0.20.0/24"),
            network("n2", "Cams", 40, "10.0.40.0/24"),
            network("n3", "A", 50),
            network("n4", "B", 50),
        ],
        [GROUP],
        vlans,
        prefixes,
    )

    iot = row(result, "IoT")
    assert iot.prefix_action == CONFLICT
    assert "NetBox prefix already points to VLAN 99." in iot.notes
    assert row(result, "Cams").prefix_action == CONFLICT
    assert row(result, "A").vlan_action == CONFLICT and not row(result, "A").selected
    assert all(
        item.category == CONFLICT
        for item in result.rows
        if not item.selected and item.name in ("A", "B")
    )


def test_disabled_networks_are_reference_only():
    result = plan([network("n1", "Guest", 60, "10.0.60.0/24", enabled=False)])

    guest = row(result, "Guest")
    assert guest.vlan_action == CREATE and not guest.selected
    assert "Disabled in UniFi; shown for reference only." in guest.notes
    assert select_network(result, guest.key, "all", True).rows[0].selected is False


def test_missing_site_or_ipam_blocks_planning():
    assert "NetBox site" in plan([network("n1", "IoT", 20)], site="Nowhere").blocker
    assert (
        plan([network("n1", "IoT", 20)], ipam_error="no rights").blocker == "no rights"
    )
    assert plan([]).rows == ()


def test_selection_by_part():
    result = plan([network("n1", "IoT", 20, "10.0.20.0/24")])
    key = result.rows[0].key

    only_vlan = select_network(result, key, "prefix", False)
    assert only_vlan.rows[0].vlan_selected and not only_vlan.rows[0].prefix_selected
    nothing = select_network(only_vlan, key, "all", False)
    assert nothing.operation_count == 0


def test_names_and_slugs():
    assert group_name_for("Wiesenthau") == "UniFi Wiesenthau"
    assert slugify("UniFi Wiesenthau 2") == "unifi-wiesenthau-2"
    assert slugify("!!!") == "unifi"
