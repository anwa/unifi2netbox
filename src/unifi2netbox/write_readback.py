from __future__ import annotations

from dataclasses import dataclass

from unifi2netbox.write_journal import OperationOutcomeStatus, WriteJournal
from unifi2netbox.write_plan import OperationType, WritePlan


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
