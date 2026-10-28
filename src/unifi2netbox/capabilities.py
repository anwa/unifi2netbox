from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class CapabilityState(StrEnum):
    VERIFIED = "Verified"
    PARTIAL = "Partial"
    UNVERIFIED = "Unverified"
    MISSING = "Missing"


@dataclass(frozen=True)
class FieldCapability:
    field: str
    state: CapabilityState
    unifi_evidence: str
    netbox_target: str
    note: str


@dataclass(frozen=True)
class CapabilityMatrix:
    unifi_version: str
    netbox_version: str
    generated_at: str
    capabilities: tuple[FieldCapability, ...]


def build_installed_capability_matrix(
    *,
    unifi_version: str,
    netbox_version: str,
    sample_device: dict[str, object] | None = None,
    generated_at: datetime | None = None,
) -> CapabilityMatrix:
    snapshot_time = generated_at or datetime.now(UTC)
    evidence = sample_device if isinstance(sample_device, dict) else {}

    entries = (
        _entry(
            field="Ports",
            state=_has_any(evidence, "ports", "interfaces", "ethernetPorts"),
            unifi_evidence="ports/interfaces list",
            netbox_target="dcim.Interface",
            note="Required for interface inventory and later M6 write mapping.",
        ),
        _entry(
            field="Profiles",
            state=_has_any(evidence, "portProfile", "portProfileId", "profile"),
            unifi_evidence="port profile identifiers",
            netbox_target="stored as provenance/diagnostic before write mapping",
            note="Needed to resolve effective profile inheritance.",
        ),
        _entry(
            field="Overrides",
            state=_has_any(evidence, "overrides", "portOverrides", "configOverrides"),
            unifi_evidence="per-port override markers",
            netbox_target="stored as provenance/diagnostic before write mapping",
            note="Needed to distinguish inherited from explicit overrides.",
        ),
        _entry(
            field="VLAN",
            state=_has_any(evidence, "nativeVlan", "taggedVlans", "vlan"),
            unifi_evidence="native/tagged VLAN fields",
            netbox_target="ipam.VLAN and interface VLAN mode/tag mappings",
            note="Coverage includes native/tagged semantics, not only IDs.",
        ),
        _entry(
            field="PoE",
            state=_has_any(evidence, "poeMode", "poeEnabled", "poeState"),
            unifi_evidence="PoE mode/state markers",
            netbox_target="interface power attributes when schema-compatible",
            note="Exact write path remains gated by NetBox field support.",
        ),
        _entry(
            field="Speed/Duplex",
            state=_has_any(evidence, "speedMbps", "duplex", "linkSpeed"),
            unifi_evidence="link speed and duplex indicators",
            netbox_target="interface speed/duplex compatible fields",
            note="State may remain diagnostic where no standard target field exists.",
        ),
        _entry(
            field="LAG",
            state=_has_any(evidence, "lag", "lacp", "aggregate", "parentLag"),
            unifi_evidence="LAG/LACP membership markers",
            netbox_target="dcim.Interface LAG relationships",
            note="Requires unambiguous parent/member evidence before apply.",
        ),
        _entry(
            field="LLDP",
            state=_has_any(evidence, "lldp", "lldpNeighbors", "neighbors"),
            unifi_evidence="LLDP neighbor payload",
            netbox_target="cable suggestions and adjacency diagnostics",
            note="LLDP is advisory and never auto-applied.",
        ),
    )

    return CapabilityMatrix(
        unifi_version=unifi_version,
        netbox_version=netbox_version,
        generated_at=snapshot_time.astimezone(UTC).isoformat(timespec="seconds"),
        capabilities=entries,
    )


def _entry(
    *,
    field: str,
    state: CapabilityState,
    unifi_evidence: str,
    netbox_target: str,
    note: str,
) -> FieldCapability:
    return FieldCapability(
        field=field,
        state=state,
        unifi_evidence=unifi_evidence,
        netbox_target=netbox_target,
        note=note,
    )


def _has_any(payload: dict[str, object], *keys: str) -> CapabilityState:
    if not payload:
        return CapabilityState.UNVERIFIED
    if any(_present(payload.get(key)) for key in keys):
        return CapabilityState.VERIFIED
    return CapabilityState.MISSING


def _present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float, str)):
        return bool(str(value).strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def matrix_to_markdown(matrix: CapabilityMatrix) -> str:
    lines = [
        f"Installed UniFi version: {matrix.unifi_version or 'unknown'}",
        f"Installed NetBox version: {matrix.netbox_version or 'unknown'}",
        f"Generated at: {matrix.generated_at}",
        "",
        "| Field | State | UniFi evidence | NetBox target | Note |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in matrix.capabilities:
        lines.append(
            f"| {entry.field} | {entry.state} | {entry.unifi_evidence} | "
            f"{entry.netbox_target} | {entry.note} |"
        )
    return "\n".join(lines)
