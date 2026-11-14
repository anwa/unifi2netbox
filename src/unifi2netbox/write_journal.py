from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from unifi2netbox.write_plan import OperationType, PreflightIssue, WritePlan


class OperationOutcomeStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class OperationOutcome:
    sequence: int
    device_key: str
    operation_type: OperationType
    status: OperationOutcomeStatus
    message: str = ""
    netbox_object_id: str = ""


@dataclass(frozen=True)
class WriteJournal:
    run_id: str
    started_at: str
    finished_at: str
    cancelled: bool
    blocker_issues: tuple[PreflightIssue, ...]
    outcomes: tuple[OperationOutcome, ...]


@dataclass(frozen=True)
class JournalSummary:
    total: int
    pending: int
    successful: int
    failed: int
    skipped: int
    blockers: int
    finished: bool


@dataclass(frozen=True)
class AmbiguousCreate:
    sequence: int
    device_key: str
    reason: str
    candidate_object_ids: tuple[str, ...] = ()


def initialize_journal(
    write_plan: WritePlan, run_id: str, started_at: str
) -> WriteJournal:
    outcomes = tuple(
        OperationOutcome(
            sequence=operation.sequence,
            device_key=operation.device_key,
            operation_type=operation.operation_type,
            status=OperationOutcomeStatus.PENDING,
        )
        for operation in write_plan.operations
    )
    blocker_issues = tuple(
        issue for issue in write_plan.issues if issue.severity.value == "blocker"
    )
    return WriteJournal(
        run_id=run_id,
        started_at=started_at,
        finished_at="",
        cancelled=False,
        blocker_issues=blocker_issues,
        outcomes=outcomes,
    )


def record_operation_result(
    journal: WriteJournal,
    sequence: int,
    status: OperationOutcomeStatus,
    message: str = "",
    netbox_object_id: str = "",
) -> WriteJournal:
    updated = False
    outcomes: list[OperationOutcome] = []
    for item in journal.outcomes:
        if item.sequence != sequence:
            outcomes.append(item)
            continue
        outcomes.append(
            replace(
                item,
                status=status,
                message=message.strip(),
                netbox_object_id=netbox_object_id.strip(),
            )
        )
        updated = True

    if not updated:
        raise ValueError("Cannot update unknown operation sequence.")

    return replace(journal, outcomes=tuple(outcomes))


def finalize_journal(
    journal: WriteJournal,
    finished_at: str,
    *,
    cancelled: bool = False,
) -> WriteJournal:
    return replace(
        journal,
        finished_at=finished_at.strip(),
        cancelled=cancelled,
    )


def summarize_journal(journal: WriteJournal) -> JournalSummary:
    pending = 0
    successful = 0
    failed = 0
    skipped = 0

    for item in journal.outcomes:
        if item.status == OperationOutcomeStatus.PENDING:
            pending += 1
        elif item.status == OperationOutcomeStatus.SUCCESS:
            successful += 1
        elif item.status == OperationOutcomeStatus.FAILED:
            failed += 1
        elif item.status == OperationOutcomeStatus.SKIPPED:
            skipped += 1

    return JournalSummary(
        total=len(journal.outcomes),
        pending=pending,
        successful=successful,
        failed=failed,
        skipped=skipped,
        blockers=len(journal.blocker_issues),
        finished=bool(journal.finished_at),
    )


def reconcile_ambiguous_creates(
    write_plan: WritePlan,
    journal: WriteJournal,
) -> tuple[AmbiguousCreate, ...]:
    create_sequences = {
        operation.sequence
        for operation in write_plan.operations
        if operation.operation_type == OperationType.CREATE_DEVICE
    }

    successful_creates = [
        item
        for item in journal.outcomes
        if item.sequence in create_sequences
        and item.status == OperationOutcomeStatus.SUCCESS
    ]

    object_id_counts: dict[str, int] = {}
    for item in successful_creates:
        if not item.netbox_object_id:
            continue
        object_id_counts[item.netbox_object_id] = (
            object_id_counts.get(item.netbox_object_id, 0) + 1
        )

    ambiguous: list[AmbiguousCreate] = []
    for item in successful_creates:
        if not item.netbox_object_id:
            ambiguous.append(
                AmbiguousCreate(
                    sequence=item.sequence,
                    device_key=item.device_key,
                    reason="missing_object_id",
                )
            )
            continue
        if object_id_counts[item.netbox_object_id] > 1:
            ambiguous.append(
                AmbiguousCreate(
                    sequence=item.sequence,
                    device_key=item.device_key,
                    reason="duplicate_object_id",
                    candidate_object_ids=(item.netbox_object_id,),
                )
            )

    return tuple(sorted(ambiguous, key=lambda item: item.sequence))
