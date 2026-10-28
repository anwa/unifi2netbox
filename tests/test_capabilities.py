from datetime import UTC, datetime

from unifi2netbox.capabilities import (
    CapabilityState,
    build_installed_capability_matrix,
    matrix_to_markdown,
)


def test_matrix_marks_unverified_without_sample_device():
    matrix = build_installed_capability_matrix(
        unifi_version="10.6.100",
        netbox_version="4.7.3",
        sample_device=None,
        generated_at=datetime(2026, 10, 28, 14, 0, 0, tzinfo=UTC),
    )

    assert matrix.unifi_version == "10.6.100"
    assert matrix.netbox_version == "4.7.3"
    assert matrix.generated_at == "2026-10-28T14:00:00+00:00"
    assert len(matrix.capabilities) == 8
    assert all(
        entry.state == CapabilityState.UNVERIFIED for entry in matrix.capabilities
    )


def test_matrix_marks_verified_fields_when_evidence_exists():
    sample = {
        "ports": [{"id": 1}],
        "portProfile": "switch-profile",
        "portOverrides": {"1": {}},
        "nativeVlan": 10,
        "poeMode": "auto",
        "speedMbps": 1000,
        "lag": {"parent": "lag0"},
        "lldp": {"neighbors": [{"chassis": "abc"}]},
    }

    matrix = build_installed_capability_matrix(
        unifi_version="10.6.100",
        netbox_version="4.7.3",
        sample_device=sample,
    )

    by_name = {entry.field: entry for entry in matrix.capabilities}
    assert by_name["Ports"].state == CapabilityState.VERIFIED
    assert by_name["Profiles"].state == CapabilityState.VERIFIED
    assert by_name["Overrides"].state == CapabilityState.VERIFIED
    assert by_name["VLAN"].state == CapabilityState.VERIFIED
    assert by_name["PoE"].state == CapabilityState.VERIFIED
    assert by_name["Speed/Duplex"].state == CapabilityState.VERIFIED
    assert by_name["LAG"].state == CapabilityState.VERIFIED
    assert by_name["LLDP"].state == CapabilityState.VERIFIED


def test_markdown_contains_required_fields():
    matrix = build_installed_capability_matrix(
        unifi_version="10.6.100",
        netbox_version="4.7.3",
        sample_device={},
        generated_at=datetime(2026, 10, 28, 14, 0, 0, tzinfo=UTC),
    )

    text = matrix_to_markdown(matrix)
    assert "| Ports |" in text
    assert "| Profiles |" in text
    assert "| Overrides |" in text
    assert "| VLAN |" in text
    assert "| PoE |" in text
    assert "| Speed/Duplex |" in text
    assert "| LAG |" in text
    assert "| LLDP |" in text
