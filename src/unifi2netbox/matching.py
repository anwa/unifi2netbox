from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum

from unifi2netbox.inventory import InventoryDevice, InventorySnapshot, InventorySource


class MatchReason(StrEnum):
    CONFIRMED = "confirmed"
    SERIAL = "serial"
    MAC = "mac"
    NAME = "name"


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
    source_id: str = ""


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
    netbox_by_name = _index_by_name(netbox)
    netbox_by_serial = _index_by_serial(netbox)
    netbox_by_mac = _index_by_mac(netbox)

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
                        "Multiple confirmed mappings target the same NetBox device."
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

    # Pass 2: ordered matching for unpaired UniFi observations.
    # Priority is name -> serial -> mac. Ambiguity in any pass is treated as conflict.
    for source in unifi:
        if source.observation_id in paired_unifi:
            continue
        matched = _try_ranked_match(
            source,
            paired_netbox,
            netbox_by_name,
            netbox_by_serial,
            netbox_by_mac,
            conflicts,
        )
        if matched is None:
            continue
        target, reason = matched
        pairs.append(
            MatchPair(
                unifi_observation_id=source.observation_id,
                netbox_observation_id=target.observation_id,
                reason=reason,
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


def _index_by_serial(
    observations: list[DeviceObservation],
) -> dict[str, list[DeviceObservation]]:
    index: dict[str, list[DeviceObservation]] = {}
    for item in observations:
        if not item.serial:
            continue
        index.setdefault(item.serial, []).append(item)
    return index


def _index_by_mac(
    observations: list[DeviceObservation],
) -> dict[str, list[DeviceObservation]]:
    index: dict[str, list[DeviceObservation]] = {}
    for item in observations:
        if not item.mac_address:
            continue
        index.setdefault(item.mac_address, []).append(item)
    return index


def _index_by_name(
    observations: list[DeviceObservation],
) -> dict[str, list[DeviceObservation]]:
    index: dict[str, list[DeviceObservation]] = {}
    for item in observations:
        key = _normalize_name(item.name)
        if not key:
            continue
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


def _try_ranked_match(
    source: DeviceObservation,
    paired_netbox: set[str],
    netbox_by_name: dict[str, list[DeviceObservation]],
    netbox_by_serial: dict[str, list[DeviceObservation]],
    netbox_by_mac: dict[str, list[DeviceObservation]],
    conflicts: list[IdentityConflict],
) -> tuple[DeviceObservation, MatchReason] | None:
    ranked_criteria: tuple[
        tuple[str, MatchReason, str, dict[str, list[DeviceObservation]]], ...
    ] = (
        ("name", MatchReason.NAME, _normalize_name(source.name), netbox_by_name),
        ("serial", MatchReason.SERIAL, source.serial, netbox_by_serial),
        ("mac", MatchReason.MAC, source.mac_address, netbox_by_mac),
    )

    for label, reason, key, index in ranked_criteria:
        if not key:
            continue
        candidates = [
            item
            for item in index.get(key, ())
            if item.observation_id not in paired_netbox
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
                    message=(
                        "UniFi observation matches multiple NetBox candidates by "
                        f"{label}."
                    ),
                )
            )
            return None
        return (candidates[0], reason)

    return None


def _identity_keys(observation: DeviceObservation) -> tuple[str, ...]:
    keys = []
    if observation.serial:
        keys.append(f"serial:{observation.serial}")
    if observation.mac_address:
        keys.append(f"mac:{observation.mac_address}")
    return tuple(keys)


def _normalize_name(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


@dataclass(frozen=True)
class _CatalogType:
    source_id: str
    manufacturer: str
    model: str
    part_number: str = ""


# Scores: exact identity evidence ranks far above fuzzy similarity.
EXACT_MODEL_SCORE = 100
PART_NUMBER_SCORE = 95
ALIAS_SCORE = 90
CLOSE_MODEL_SCORE = 40
PARTIAL_MODEL_SCORE = 15
# Suggestions at or above this score are unambiguous enough to preselect.
CONFIDENT_SCORE = ALIAS_SCORE


def _build_type_catalog(
    netbox_snapshot: InventorySnapshot | None,
) -> tuple[_CatalogType, ...]:
    if netbox_snapshot is None:
        return ()

    if netbox_snapshot.device_types:
        return tuple(
            _CatalogType(
                source_id=item.source_id,
                manufacturer=item.manufacturer,
                model=item.model,
                part_number=item.part_number,
            )
            for item in netbox_snapshot.device_types
            if item.manufacturer.strip() and item.model.strip()
        )

    seen: set[tuple[str, str]] = set()
    catalog: list[_CatalogType] = []
    for device in netbox_snapshot.devices:
        manufacturer = device.manufacturer.strip()
        model = device.model.strip()
        if not manufacturer or not model:
            continue
        key = (_norm(manufacturer), _norm(model))
        if key in seen:
            continue
        seen.add(key)
        catalog.append(_CatalogType("", manufacturer, model))
    return tuple(catalog)


def _rank_candidates(
    device: InventoryDevice,
    catalog: tuple[_CatalogType, ...],
) -> list[DeviceTypeCandidate]:
    model = device.model.strip()
    manufacturer = _norm(device.manufacturer)
    if not model:
        return []

    model_key = _norm(model)
    alias_keys = _alias_keys(model) - {model_key}
    source_numbers = _numbers(model)

    ranked: list[DeviceTypeCandidate] = []
    for item in catalog:
        if manufacturer and _norm(item.manufacturer) != manufacturer:
            continue
        target_keys = {_norm(item.model), _norm(item.part_number)} - {""}
        reasons: list[str] = []
        if manufacturer:
            reasons.append("manufacturer exact match")

        if model_key == _norm(item.model):
            score = EXACT_MODEL_SCORE
            reasons.append("model exact match")
        elif item.part_number and model_key == _norm(item.part_number):
            score = PART_NUMBER_SCORE
            reasons.append("part number exact match")
        elif alias_keys & target_keys:
            score = ALIAS_SCORE
            reasons.append("UniFi model alias match")
        else:
            target_numbers = _numbers(item.model) | _numbers(item.part_number)
            if source_numbers and target_numbers and source_numbers != target_numbers:
                continue
            similarity = max(
                _similarity(key, target)
                for key in {model_key} | alias_keys
                for target in target_keys
            )
            if similarity >= 0.85:
                score = CLOSE_MODEL_SCORE
                reasons.append("model close match")
            elif similarity >= 0.7:
                score = PARTIAL_MODEL_SCORE
                reasons.append("model partial similarity")
            else:
                continue

        ranked.append(
            DeviceTypeCandidate(
                manufacturer=item.manufacturer,
                model=item.model,
                score=score,
                reasons=tuple(reasons),
                source_id=item.source_id,
            )
        )

    ranked.sort(
        key=lambda item: (-item.score, _norm(item.manufacturer), _norm(item.model))
    )
    return ranked


def confident_device_type_id(candidates: tuple[DeviceTypeCandidate, ...]) -> str:
    """Return the type ID of a single unambiguous top candidate, else ''."""
    if not candidates or not candidates[0].source_id:
        return ""
    top = candidates[0]
    if top.score < CONFIDENT_SCORE:
        return ""
    if len(candidates) > 1 and candidates[1].score == top.score:
        return ""
    return top.source_id


def _alias_keys(model: str) -> set[str]:
    """Normalized spellings UniFi uses for NetBox part numbers.

    - ``AC Pro`` is part number ``UAP-AC-PRO``.
    - ``US 16 PoE 150W`` is part number ``US-16-150W`` (no ``PoE`` token).
    """
    tokens = _tokens(model)
    keys = {"".join(tokens)}
    without_poe = [token for token in tokens if token != "poe"]
    if len(without_poe) != len(tokens) and any(
        token.endswith("w") and token[:-1].isdigit() for token in tokens
    ):
        keys.add("".join(without_poe))
    for key in list(keys):
        if key.startswith("ac"):
            keys.add("uap" + key)
    return keys - {""}


def _tokens(value: str) -> list[str]:
    tokens: list[str] = []
    current = ""
    for character in value.lower():
        if character.isalnum():
            current += character
        elif current:
            tokens.append(current)
            current = ""
    if current:
        tokens.append(current)
    return tokens


def _numbers(value: str) -> frozenset[str]:
    """Port-count style numbers; wattage tokens such as ``150W`` are ignored."""
    return frozenset(token for token in _tokens(value) if token.isdigit())


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(a=left, b=right).ratio()


def _norm(value: str) -> str:
    return "".join(character.lower() for character in value if character.isalnum())
