from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from unifi2netbox.write_journal import (
    OperationOutcomeStatus,
    Verification,
    WriteJournal,
    record_verification,
)
from unifi2netbox.write_plan import OperationType, WritePlan

type DeviceReader = Callable[[str], Mapping[str, object] | None]


@dataclass(frozen=True)
class ReadbackRequest:
    sequence: int
    device_key: str
    operation_type: OperationType
    netbox_object_id: str


@dataclass(frozen=True)
class ReadbackPlan:
    requests: tuple[ReadbackRequest, ...]
    skipped_sequences: tuple[int, ...]


def build_readback_plan(write_plan: WritePlan, journal: WriteJournal) -> ReadbackPlan:
    operations_by_sequence = {
        operation.sequence: operation for operation in write_plan.operations
    }

    requests: list[ReadbackRequest] = []
    skipped: list[int] = []

    for outcome in journal.outcomes:
        if outcome.status != OperationOutcomeStatus.SUCCESS:
            continue

        operation = operations_by_sequence.get(outcome.sequence)
        if operation is None:
            skipped.append(outcome.sequence)
            continue

        if operation.operation_type == OperationType.CREATE_DEVICE:
            object_id = outcome.netbox_object_id.strip()
            if not object_id:
                skipped.append(outcome.sequence)
                continue
            requests.append(
                ReadbackRequest(
                    sequence=outcome.sequence,
                    device_key=outcome.device_key,
                    operation_type=operation.operation_type,
                    netbox_object_id=object_id,
                )
            )
            continue

        if operation.operation_type == OperationType.UPDATE_DEVICE:
            object_id = _extract_update_object_id(operation.device_key)
            if not object_id:
                skipped.append(outcome.sequence)
                continue
            requests.append(
                ReadbackRequest(
                    sequence=outcome.sequence,
                    device_key=outcome.device_key,
                    operation_type=operation.operation_type,
                    netbox_object_id=object_id,
                )
            )

    requests = sorted(requests, key=lambda item: item.sequence)
    skipped = sorted(set(skipped))
    return ReadbackPlan(requests=tuple(requests), skipped_sequences=tuple(skipped))


def _extract_update_object_id(device_key: str) -> str:
    marker = "->netbox:"
    if marker not in device_key:
        return ""
    object_id = device_key.split(marker, maxsplit=1)[1].strip()
    return object_id


def verify_readback(
    write_plan: WritePlan,
    journal: WriteJournal,
    expected_by_sequence: Mapping[int, Mapping[str, object]],
    read_device: DeviceReader,
) -> WriteJournal:
    """Re-read successful writes and record whether NetBox holds the payload.

    Each written payload key is compared with the device NetBox returns: plain
    values (name, serial) directly, related objects (site, role, device type)
    by ID and status by its value. Read errors leave the write successful but
    mark it unverified; they never trigger another write.
    """
    plan = build_readback_plan(write_plan, journal)
    for request in plan.requests:
        expected = expected_by_sequence.get(request.sequence)
        if not expected:
            continue
        try:
            row = read_device(request.netbox_object_id)
        except Exception as error:  # noqa: BLE001 - reported, never retried
            journal = record_verification(
                journal,
                request.sequence,
                Verification.UNVERIFIED,
                f"Read-back failed: {error}",
            )
            continue
        if row is None:
            journal = record_verification(
                journal,
                request.sequence,
                Verification.UNVERIFIED,
                f"NetBox device {request.netbox_object_id} was not found after "
                "the write.",
            )
            continue
        mismatches = [
            f"{key}: expected {value!s}, NetBox has {actual or '-'}"
            for key, value in _flatten(expected).items()
            if (actual := _row_value(row, key)) != str(value).strip()
        ]
        journal = record_verification(
            journal,
            request.sequence,
            Verification.MISMATCH if mismatches else Verification.VERIFIED,
            "; ".join(mismatches) or "NetBox matches the written values.",
        )
    return journal


def _flatten(expected: Mapping[str, object]) -> dict[str, object]:
    """Custom Field values become ``custom_fields.<name>`` keys."""
    flat: dict[str, object] = {}
    for key, value in expected.items():
        if key == "custom_fields" and isinstance(value, Mapping):
            flat.update({f"custom_fields.{name}": item for name, item in value.items()})
        else:
            flat[key] = value
    return flat


def _row_value(row: Mapping[str, object], key: str) -> str:
    if key.startswith("custom_fields."):
        fields = row.get("custom_fields")
        value = (
            fields.get(key.split(".", 1)[1]) if isinstance(fields, Mapping) else None
        )
        return "" if value is None else str(value).strip()
    value = row.get(key)
    if isinstance(value, Mapping):
        nested = value.get("value") if key == "status" else value.get("id")
        return "" if nested is None else str(nested).strip()
    return "" if value is None else str(value).strip()
