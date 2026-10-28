from unifi2netbox.inventory import InventoryDevice, InventorySnapshot, InventorySource
from unifi2netbox.matching import (
    ConflictReason,
    MatchReason,
    deduplicate_inventory,
)


def snapshot(
    source: InventorySource, devices: list[InventoryDevice]
) -> InventorySnapshot:
    return InventorySnapshot(
        source=source,
        captured_at="2026-10-28T15:00:00+00:00",
        source_version="x",
        devices=tuple(devices),
    )


def netbox_device(device_id: str, serial: str = "", mac: str = "") -> InventoryDevice:
    return InventoryDevice(
        source_id=device_id, name=f"nb-{device_id}", serial=serial, mac_address=mac
    )


def unifi_device(device_id: str, serial: str = "", mac: str = "") -> InventoryDevice:
    return InventoryDevice(
        source_id=device_id, name=f"uf-{device_id}", serial=serial, mac_address=mac
    )


def test_identity_match_pairs_unique_candidate():
    netbox = snapshot(
        InventorySource.NETBOX,
        [netbox_device("1", serial="ABC123", mac="00:11:22:33:44:55")],
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [unifi_device("a", serial="abc123")],
    )

    result = deduplicate_inventory(netbox, unifi)

    assert len(result.pairs) == 1
    assert result.pairs[0].reason == MatchReason.IDENTITY
    assert result.conflicts == ()
    assert result.unmatched_unifi == ()
    assert result.unmatched_netbox == ()


def test_ambiguous_identity_creates_conflict():
    netbox = snapshot(
        InventorySource.NETBOX,
        [
            netbox_device("1", serial="ABC123"),
            netbox_device("2", serial="ABC123"),
        ],
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK, [unifi_device("a", serial="ABC123")]
    )

    result = deduplicate_inventory(netbox, unifi)

    assert result.pairs == ()
    assert len(result.conflicts) == 1
    assert result.conflicts[0].reason == ConflictReason.AMBIGUOUS_CANDIDATES


def test_confirmed_mapping_overrides_missing_identity():
    netbox = snapshot(InventorySource.NETBOX, [netbox_device("1")])
    unifi = snapshot(InventorySource.UNIFI_NETWORK, [unifi_device("a")])
    confirmed = {"unifi_network:a": "netbox:1"}

    result = deduplicate_inventory(netbox, unifi, confirmed_mappings=confirmed)

    assert len(result.pairs) == 1
    assert result.pairs[0].reason == MatchReason.CONFIRMED
    assert result.conflicts == ()


def test_duplicate_confirmed_target_reports_conflict():
    netbox = snapshot(InventorySource.NETBOX, [netbox_device("1")])
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [unifi_device("a"), unifi_device("b")],
    )
    confirmed = {
        "unifi_network:a": "netbox:1",
        "unifi_network:b": "netbox:1",
    }

    result = deduplicate_inventory(netbox, unifi, confirmed_mappings=confirmed)

    assert len(result.pairs) == 1
    assert len(result.conflicts) == 1
    assert result.conflicts[0].reason == ConflictReason.DUPLICATE_CONFIRMED_TARGET


def test_missing_confirmed_target_reports_conflict():
    netbox = snapshot(InventorySource.NETBOX, [netbox_device("1")])
    unifi = snapshot(InventorySource.UNIFI_NETWORK, [unifi_device("a")])
    confirmed = {"unifi_network:a": "netbox:999"}

    result = deduplicate_inventory(netbox, unifi, confirmed_mappings=confirmed)

    assert result.pairs == ()
    assert len(result.conflicts) == 1
    assert result.conflicts[0].reason == ConflictReason.MISSING_CONFIRMED_TARGET
