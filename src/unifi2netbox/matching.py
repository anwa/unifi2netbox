from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum

from unifi2netbox.inventory import InventoryDevice, InventorySnapshot, InventorySource


class MatchReason(StrEnum):
    CONFIRMED = "confirmed"
    IDENTITY = "identity"


class ConflictReason(StrEnum):
    AMBIGUOUS_CANDIDATES = "ambiguous_candidates"
    DUPLICATE_CONFIRMED_TARGET = "duplicate_confirmed_target"
    MISSING_CONFIRMED_TARGET = "missing_confirmed_target"


@dataclass(frozen=True)
class DeviceObservation:
    observation_id: str
    source: InventorySource
    source_id: str
    name: str
    serial: str
    mac_address: str


@dataclass(frozen=True)
class MatchPair:
    unifi_observation_id: str
    netbox_observation_id: str
    reason: MatchReason


@dataclass(frozen=True)
class IdentityConflict:
    reason: ConflictReason
    observation_ids: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class DeduplicationResult:
    pairs: tuple[MatchPair, ...]
    conflicts: tuple[IdentityConflict, ...]
    unmatched_unifi: tuple[str, ...]
    unmatched_netbox: tuple[str, ...]


@dataclass(frozen=True)
class DeviceTypeCandidate:
    manufacturer: str
    model: str
    score: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class DeviceTypeSuggestion:
    unifi_observation_id: str
    candidates: tuple[DeviceTypeCandidate, ...]


def deduplicate_inventory(
    netbox_snapshot: InventorySnapshot | None,
    unifi_snapshot: InventorySnapshot | None,
    *,
    confirmed_mappings: dict[str, str] | None = None,
) -> DeduplicationResult:
    confirmed = confirmed_mappings or {}
    netbox = _observations(netbox_snapshot)
    unifi = _observations(unifi_snapshot)

    netbox_by_id = {item.observation_id: item for item in netbox}
    netbox_by_identity = _index_by_identity(netbox)

    pairs: list[MatchPair] = []
    conflicts: list[IdentityConflict] = []
    paired_unifi: set[str] = set()
    paired_netbox: set[str] = set()

    # Pass 1: explicit confirmed mappings.
    for unifi_id, netbox_id in confirmed.items():
        source = next((item for item in unifi if item.observation_id == unifi_id), None)
        target = netbox_by_id.get(netbox_id)
        if source is None or target is None:
            conflicts.append(
                IdentityConflict(
                    reason=ConflictReason.MISSING_CONFIRMED_TARGET,
                    observation_ids=(unifi_id, netbox_id),
                    message="Confirmed mapping points to a missing source or target.",
                )
            )
            continue
        if target.observation_id in paired_netbox:
            conflicts.append(
                IdentityConflict(
                    reason=ConflictReason.DUPLICATE_CONFIRMED_TARGET,
                    observation_ids=(unifi_id, target.observation_id),
                    message=(
                        "Multiple confirmed mappings target the same " "NetBox device."
                    ),
                )
            )
            continue
        pairs.append(
            MatchPair(
                unifi_observation_id=source.observation_id,
                netbox_observation_id=target.observation_id,
                reason=MatchReason.CONFIRMED,
            )
        )
        paired_unifi.add(source.observation_id)
        paired_netbox.add(target.observation_id)

    # Pass 2: identity-based matching for unpaired UniFi observations.
    for source in unifi:
        if source.observation_id in paired_unifi:
            continue
        candidates = _candidates_for(source, netbox_by_identity)
        candidates = [
            item for item in candidates if item.observation_id not in paired_netbox
        ]
        if not candidates:
            continue
        if len(candidates) > 1:
            conflicts.append(
                IdentityConflict(
                    reason=ConflictReason.AMBIGUOUS_CANDIDATES,
                    observation_ids=(
                        source.observation_id,
                        *(item.observation_id for item in candidates),
                    ),
                    message="UniFi observation matches multiple NetBox candidates.",
                )
            )
            continue
        target = candidates[0]
        pairs.append(
            MatchPair(
                unifi_observation_id=source.observation_id,
                netbox_observation_id=target.observation_id,
                reason=MatchReason.IDENTITY,
            )
        )
        paired_unifi.add(source.observation_id)
        paired_netbox.add(target.observation_id)

    unmatched_unifi = tuple(
        item.observation_id for item in unifi if item.observation_id not in paired_unifi
    )
    unmatched_netbox = tuple(
        item.observation_id
        for item in netbox
        if item.observation_id not in paired_netbox
    )

    return DeduplicationResult(
        pairs=tuple(pairs),
        conflicts=tuple(conflicts),
        unmatched_unifi=unmatched_unifi,
        unmatched_netbox=unmatched_netbox,
    )


def suggest_device_types_for_unmatched(
    result: DeduplicationResult,
    netbox_snapshot: InventorySnapshot | None,
    unifi_snapshot: InventorySnapshot | None,
    *,
    limit: int = 3,
) -> tuple[DeviceTypeSuggestion, ...]:
    if limit < 1:
        raise ValueError("limit must be positive.")
    if unifi_snapshot is None:
        return ()

    catalog = _build_type_catalog(netbox_snapshot)
    if not catalog:
        return ()

    unifi_by_id = {
        _observation_id(InventorySource.UNIFI_NETWORK, device): device
        for device in unifi_snapshot.devices
    }
    suggestions: list[DeviceTypeSuggestion] = []
    for observation_id in result.unmatched_unifi:
        device = unifi_by_id.get(observation_id)
        if device is None:
            continue
        candidates = _rank_candidates(device, catalog)[:limit]
        if not candidates:
            continue
        suggestions.append(
            DeviceTypeSuggestion(
                unifi_observation_id=observation_id,
                candidates=tuple(candidates),
            )
        )
    return tuple(suggestions)


def _observations(snapshot: InventorySnapshot | None) -> list[DeviceObservation]:
    if snapshot is None:
        return []
    observations: list[DeviceObservation] = []
    for device in snapshot.devices:
        observation_id = _observation_id(snapshot.source, device)
        observations.append(
            DeviceObservation(
                observation_id=observation_id,
                source=snapshot.source,
                source_id=device.source_id,
                name=device.name,
                serial=_normalize_serial(device.serial),
                mac_address=_normalize_mac(device.mac_address),
            )
        )
    return observations


def _observation_id(source: InventorySource, device: InventoryDevice) -> str:
    key = device.source_id.strip() or device.name.strip() or "unnamed"
    return f"{source}:{key}"


def _normalize_serial(value: str) -> str:
    return "".join(character for character in value.upper() if character.isalnum())


def _normalize_mac(value: str) -> str:
    compact = "".join(character for character in value.upper() if character.isalnum())
    if len(compact) != 12:
        return ""
    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))


def _index_by_identity(
    observations: list[DeviceObservation],
) -> dict[str, list[DeviceObservation]]:
    index: dict[str, list[DeviceObservation]] = {}
    for item in observations:
        for key in _identity_keys(item):
            index.setdefault(key, []).append(item)
    return index


def _candidates_for(
    source: DeviceObservation,
    netbox_by_identity: dict[str, list[DeviceObservation]],
) -> list[DeviceObservation]:
    candidates: dict[str, DeviceObservation] = {}
    for key in _identity_keys(source):
        for item in netbox_by_identity.get(key, ()):
            candidates[item.observation_id] = item
    return list(candidates.values())


def _identity_keys(observation: DeviceObservation) -> tuple[str, ...]:
    keys = []
    if observation.serial:
        keys.append(f"serial:{observation.serial}")
    if observation.mac_address:
        keys.append(f"mac:{observation.mac_address}")
    return tuple(keys)


def _build_type_catalog(
    netbox_snapshot: InventorySnapshot | None,
) -> tuple[tuple[str, str], ...]:
    if netbox_snapshot is None:
        return ()
    seen: set[tuple[str, str]] = set()
    catalog: list[tuple[str, str]] = []
    for device in netbox_snapshot.devices:
        manufacturer = device.manufacturer.strip()
        model = device.model.strip()
        if not manufacturer or not model:
            continue
        key = (_norm(manufacturer), _norm(model))
        if key in seen:
            continue
        seen.add(key)
        catalog.append((manufacturer, model))
    return tuple(catalog)


def _rank_candidates(
    device: InventoryDevice,
    catalog: tuple[tuple[str, str], ...],
) -> list[DeviceTypeCandidate]:
    model = device.model.strip()
    manufacturer = device.manufacturer.strip()
    if not model and not manufacturer:
        return []

    ranked: list[DeviceTypeCandidate] = []
    for target_manufacturer, target_model in catalog:
        score = 0
        reasons: list[str] = []
        if manufacturer and _norm(manufacturer) == _norm(target_manufacturer):
            score += 20
            reasons.append("manufacturer exact match")
        model_similarity = _model_similarity(model, target_model)
        if model and model_similarity >= 0.999:
            score += 70
            reasons.append("model exact match")
        elif model and model_similarity >= 0.85:
            score += 35
            reasons.append("model close match")
        elif model and model_similarity >= 0.7:
            score += 15
            reasons.append("model partial similarity")

        if score <= 0:
            continue
        ranked.append(
            DeviceTypeCandidate(
                manufacturer=target_manufacturer,
                model=target_model,
                score=score,
                reasons=tuple(reasons),
            )
        )

    ranked.sort(
        key=lambda item: (-item.score, _norm(item.manufacturer), _norm(item.model))
    )
    return ranked


def _model_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(a=_norm(left), b=_norm(right)).ratio()


def _norm(value: str) -> str:
    return "".join(character.lower() for character in value if character.isalnum())
