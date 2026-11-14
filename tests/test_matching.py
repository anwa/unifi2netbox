import pytest

from unifi2netbox.inventory import (
    InventoryDevice,
    InventoryDeviceType,
    InventorySnapshot,
    InventorySource,
)
from unifi2netbox.matching import (
    ConflictReason,
    DeviceTypeCandidate,
    MatchReason,
    confident_device_type_id,
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


def test_serial_match_pairs_unique_candidate():
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
    assert result.pairs[0].reason == MatchReason.SERIAL
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


def test_name_fallback_matches_unique_name_when_identity_missing():
    netbox = snapshot(
        InventorySource.NETBOX,
        [InventoryDevice(source_id="1", name="HG-DG-R1-UDM")],
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [InventoryDevice(source_id="a", name="HG-DG-R1-UDM")],
    )

    result = deduplicate_inventory(netbox, unifi)

    assert len(result.pairs) == 1
    assert result.pairs[0].reason == MatchReason.NAME
    assert result.conflicts == ()
    assert result.unmatched_unifi == ()
    assert result.unmatched_netbox == ()


def test_name_match_precedes_serial_and_mac_matches():
    netbox = snapshot(
        InventorySource.NETBOX,
        [
            InventoryDevice(
                source_id="1",
                name="HG-DG-R1-UDM",
                serial="WRONG",
                mac_address="AA:AA:AA:AA:AA:AA",
            ),
            InventoryDevice(
                source_id="2",
                name="other",
                serial="SERIAL-1",
                mac_address="11:22:33:44:55:66",
            ),
        ],
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(
                source_id="a",
                name="HG-DG-R1-UDM",
                serial="SERIAL-1",
                mac_address="11:22:33:44:55:66",
            )
        ],
    )

    result = deduplicate_inventory(netbox, unifi)

    assert len(result.pairs) == 1
    assert result.pairs[0].netbox_observation_id == "netbox:1"
    assert result.pairs[0].reason == MatchReason.NAME


def test_ambiguous_name_blocks_serial_and_mac_fallback():
    netbox = snapshot(
        InventorySource.NETBOX,
        [
            InventoryDevice(source_id="1", name="dup-name", serial="SERIAL-1"),
            InventoryDevice(source_id="2", name="dup-name", serial="OTHER"),
        ],
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [InventoryDevice(source_id="a", name="dup-name", serial="SERIAL-1")],
    )

    result = deduplicate_inventory(netbox, unifi)

    assert result.pairs == ()
    assert len(result.conflicts) == 1
    assert result.conflicts[0].reason == ConflictReason.AMBIGUOUS_CANDIDATES


def test_serial_match_precedes_mac_match():
    netbox = snapshot(
        InventorySource.NETBOX,
        [
            InventoryDevice(
                source_id="1",
                name="nb-1",
                serial="SERIAL-1",
                mac_address="AA:BB:CC:DD:EE:FF",
            ),
            InventoryDevice(
                source_id="2",
                name="nb-2",
                serial="OTHER",
                mac_address="11:22:33:44:55:66",
            ),
        ],
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(
                source_id="a",
                name="uf-a",
                serial="SERIAL-1",
                mac_address="11:22:33:44:55:66",
            )
        ],
    )

    result = deduplicate_inventory(netbox, unifi)

    assert len(result.pairs) == 1
    assert result.pairs[0].netbox_observation_id == "netbox:1"
    assert result.pairs[0].reason == MatchReason.SERIAL


def test_mac_match_is_used_when_name_and_serial_do_not_match():
    netbox = snapshot(
        InventorySource.NETBOX,
        [InventoryDevice(source_id="1", name="nb-1", mac_address="11:22:33:44:55:66")],
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(
                source_id="a",
                name="uf-a",
                serial="SERIAL-1",
                mac_address="11:22:33:44:55:66",
            )
        ],
    )

    result = deduplicate_inventory(netbox, unifi)

    assert len(result.pairs) == 1
    assert result.pairs[0].reason == MatchReason.MAC


def test_name_fallback_reports_ambiguous_candidates():
    netbox = snapshot(
        InventorySource.NETBOX,
        [
            InventoryDevice(source_id="1", name="HG-DG-R1-UDM"),
            InventoryDevice(source_id="2", name="HG-DG-R1-UDM"),
        ],
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [InventoryDevice(source_id="a", name="HG-DG-R1-UDM")],
    )

    result = deduplicate_inventory(netbox, unifi)

    assert result.pairs == ()
    assert len(result.conflicts) == 1
    assert result.conflicts[0].reason == ConflictReason.AMBIGUOUS_CANDIDATES


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


def test_type_suggestions_prefer_netbox_device_type_templates():
    netbox = InventorySnapshot(
        source=InventorySource.NETBOX,
        captured_at="2026-10-28T15:00:00+00:00",
        source_version="x",
        devices=(),
        device_types=(
            InventoryDeviceType(
                source_id="101", manufacturer="Ubiquiti", model="USW-24"
            ),
            InventoryDeviceType(
                source_id="102", manufacturer="Ubiquiti", model="U7-Pro"
            ),
        ),
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(
                source_id="u1",
                name="switch-1",
                manufacturer="Ubiquiti",
                model="U7 Pro",
            )
        ],
    )

    result = deduplicate_inventory(netbox, unifi)
    suggestions = suggest_device_types_for_unmatched(result, netbox, unifi)

    assert len(suggestions) == 1
    assert suggestions[0].candidates[0].manufacturer == "Ubiquiti"
    assert suggestions[0].candidates[0].model == "U7-Pro"


# Model/part-number pairs as published in the NetBox device-type library.
LIBRARY_TYPES = (
    ("1", "AC Professional", "UAP-AC-PRO"),
    ("2", "AC Mesh Professional", "UAP-AC-M-PRO"),
    ("3", "U6 Lite", "U6-Lite"),
    ("4", "US-8-150W", ""),
    ("5", "UniFi Switch 8 PoE 60W Gen1", "US-8-60W"),
    ("6", "UniFi Switch 16 PoE 150W Gen1", "US-16-150W"),
    ("7", "UniFi Switch 24 Pro", "USW-Pro-24"),
    ("8", "UniFi Switch 24 Pro PoE Gen2", "USW-Pro-24-POE"),
    ("9", "USW-Pro-8-PoE", ""),
    ("10", "UniFi Switch Aggregation", "USW-Aggregation"),
    ("11", "UniFi Switch Pro Aggregation", "USW-Pro-Aggregation"),
    ("12", "UniFi Switch Flex Mini", "USW-Flex-Mini"),
    ("13", "10G PoE++ Adapter (60W)", "U-POE-AT-60W"),
    ("14", "EdgeSwitch 8 150W", "ES-8-150W"),
    ("20", "Switch 24", "SW-24"),
)


def library_snapshot() -> InventorySnapshot:
    manufacturer = {"20": "Other"}
    return InventorySnapshot(
        source=InventorySource.NETBOX,
        captured_at="2026-11-14T10:00:00+00:00",
        device_types=tuple(
            InventoryDeviceType(
                source_id=type_id,
                manufacturer=manufacturer.get(type_id, "Ubiquiti"),
                model=model,
                part_number=part,
            )
            for type_id, model, part in LIBRARY_TYPES
        ),
    )


def suggestions_for(model: str, manufacturer: str = "Ubiquiti"):
    netbox = library_snapshot()
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(
                source_id="u", name="dev", manufacturer=manufacturer, model=model
            )
        ],
    )
    result = deduplicate_inventory(netbox, unifi)
    found = suggest_device_types_for_unmatched(result, netbox, unifi, limit=10)
    return found[0].candidates if found else ()


@pytest.mark.parametrize(
    ("unifi_model", "expected_id", "reason"),
    [
        ("U6 Lite", "3", "model exact match"),
        ("USW Pro 24", "7", "part number exact match"),
        ("USW Pro 24 PoE", "8", "part number exact match"),
        ("UAP-AC-M-Pro", "2", "part number exact match"),
        ("US 8 60W", "5", "part number exact match"),
        ("USW Aggregation", "10", "part number exact match"),
        ("USW Pro Aggregation", "11", "part number exact match"),
        ("USW Flex Mini", "12", "part number exact match"),
        ("AC Pro", "1", "UniFi model alias match"),
        ("US 16 PoE 150W", "6", "UniFi model alias match"),
        ("US 8 PoE 150W", "4", "UniFi model alias match"),
    ],
)
def test_unifi_model_names_resolve_to_library_types(unifi_model, expected_id, reason):
    candidates = suggestions_for(unifi_model)

    assert candidates[0].source_id == expected_id
    assert reason in candidates[0].reasons
    assert confident_device_type_id(candidates) == expected_id


def test_port_count_mismatch_is_never_suggested():
    candidates = suggestions_for("USW Pro 24 PoE")

    assert "9" not in {candidate.source_id for candidate in candidates}


def test_manufacturer_only_candidates_are_not_suggested():
    candidates = suggestions_for("Totally Unknown Device")

    assert candidates == ()


def test_other_manufacturers_are_not_suggested():
    candidates = suggestions_for("USW 24")

    assert all(candidate.manufacturer == "Ubiquiti" for candidate in candidates)


def test_fuzzy_or_tied_candidates_are_not_preselected():
    fuzzy = (DeviceTypeCandidate("Ubiquiti", "A", 40, (), "1"),)
    tied = (
        DeviceTypeCandidate("Ubiquiti", "A", 95, (), "1"),
        DeviceTypeCandidate("Ubiquiti", "B", 95, (), "2"),
    )
    without_id = (DeviceTypeCandidate("Ubiquiti", "A", 100, (), ""),)

    assert confident_device_type_id(fuzzy) == ""
    assert confident_device_type_id(tied) == ""
    assert confident_device_type_id(without_id) == ""
    assert confident_device_type_id(()) == ""
