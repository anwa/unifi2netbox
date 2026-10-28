from unifi2netbox.inventory import InventoryDevice, InventorySnapshot, InventorySource
from unifi2netbox.matching import (
    ConflictReason,
    MatchReason,
    deduplicate_inventory,
    suggest_device_types_for_unmatched,
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


def test_type_suggestions_only_for_unmatched_devices():
    netbox = snapshot(
        InventorySource.NETBOX,
        [
            InventoryDevice(
                source_id="1",
                name="nb-1",
                serial="N1",
                manufacturer="Ubiquiti",
                model="USW-24",
            ),
            InventoryDevice(
                source_id="2",
                name="nb-2",
                serial="N2",
                manufacturer="Ubiquiti",
                model="U7-Pro",
            ),
        ],
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(
                source_id="a",
                name="uf-a",
                serial="N1",
                manufacturer="Ubiquiti",
                model="USW24",
            ),
            InventoryDevice(
                source_id="b",
                name="uf-b",
                serial="X9",
                manufacturer="Ubiquiti",
                model="U7 Pro",
            ),
        ],
    )

    result = deduplicate_inventory(netbox, unifi)
    suggestions = suggest_device_types_for_unmatched(result, netbox, unifi)

    assert len(result.pairs) == 1
    assert result.pairs[0].unifi_observation_id == "unifi_network:a"
    assert len(suggestions) == 1
    assert suggestions[0].unifi_observation_id == "unifi_network:b"
    assert suggestions[0].candidates[0].manufacturer == "Ubiquiti"
    assert suggestions[0].candidates[0].model == "U7-Pro"


def test_type_suggestions_are_explainable_and_ranked():
    netbox = snapshot(
        InventorySource.NETBOX,
        [
            InventoryDevice(
                source_id="1",
                name="nb-1",
                manufacturer="Ubiquiti",
                model="USW-24",
            ),
            InventoryDevice(
                source_id="2",
                name="nb-2",
                manufacturer="Other",
                model="Switch-24",
            ),
        ],
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(
                source_id="b",
                name="uf-b",
                manufacturer="Ubiquiti",
                model="USW 24",
            )
        ],
    )

    result = deduplicate_inventory(netbox, unifi)
    suggestions = suggest_device_types_for_unmatched(result, netbox, unifi)

    assert len(suggestions) == 1
    top = suggestions[0].candidates[0]
    assert top.manufacturer == "Ubiquiti"
    assert top.model == "USW-24"
    assert top.score > 0
    assert "manufacturer exact match" in top.reasons


def test_type_suggestions_require_catalog_and_positive_limit():
    result = deduplicate_inventory(None, None)
    assert suggest_device_types_for_unmatched(result, None, None) == ()
