import pytest

from unifi2netbox.inventory import InventoryDevice, InventorySnapshot, InventorySource
from unifi2netbox.matching import deduplicate_inventory
from unifi2netbox.preview import build_change_preview, build_difference_preview
from unifi2netbox.write_journal import (
    OperationOutcomeStatus,
    finalize_journal,
    initialize_journal,
    reconcile_ambiguous_creates,
    record_operation_result,
    summarize_journal,
)
from unifi2netbox.write_plan import build_write_plan


def snapshot(
    source: InventorySource, devices: list[InventoryDevice]
) -> InventorySnapshot:
    return InventorySnapshot(
        source=source,
        captured_at="2026-11-01T10:00:00+00:00",
        source_version="x",
        devices=tuple(devices),
    )


def test_initialize_journal_creates_pending_outcomes():
    netbox = snapshot(
        InventorySource.NETBOX,
        [InventoryDevice(source_id="1", name="switch-a", serial="S1", site="HQ")],
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(source_id="a", name="switch-a-new", serial="S1", site="HQ"),
            InventoryDevice(source_id="b", name="switch-b", serial="S2", site="HQ"),
        ],
    )

    dedup = deduplicate_inventory(netbox, unifi)
    preview = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(preview)
    plan = build_write_plan(preview, change)

    journal = initialize_journal(
        write_plan=plan,
        run_id="run-1",
        started_at="2026-11-01T12:00:00+00:00",
    )

    assert len(journal.outcomes) == 2
    assert all(
        item.status == OperationOutcomeStatus.PENDING for item in journal.outcomes
    )
    summary = summarize_journal(journal)
    assert summary.total == 2
    assert summary.pending == 2
    assert summary.finished is False


def test_record_operation_result_updates_one_sequence():
    netbox = snapshot(InventorySource.NETBOX, [])
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [InventoryDevice(source_id="a", name="switch-a", site="HQ")],
    )

    dedup = deduplicate_inventory(netbox, unifi)
    preview = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(preview)
    plan = build_write_plan(preview, change)

    journal = initialize_journal(
        plan, run_id="run-2", started_at="2026-11-01T12:10:00+00:00"
    )
    updated = record_operation_result(
        journal,
        sequence=1,
        status=OperationOutcomeStatus.SUCCESS,
        message="Created in NetBox",
        netbox_object_id="42",
    )

    assert journal is not updated
    assert updated.outcomes[0].status == OperationOutcomeStatus.SUCCESS
    assert updated.outcomes[0].netbox_object_id == "42"
    summary = summarize_journal(updated)
    assert summary.successful == 1
    assert summary.pending == 0


def test_record_operation_result_rejects_unknown_sequence():
    netbox = snapshot(InventorySource.NETBOX, [])
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [InventoryDevice(source_id="a", name="switch-a", site="HQ")],
    )

    dedup = deduplicate_inventory(netbox, unifi)
    preview = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(preview)
    plan = build_write_plan(preview, change)
    journal = initialize_journal(
        plan, run_id="run-3", started_at="2026-11-01T12:20:00+00:00"
    )

    with pytest.raises(ValueError):
        record_operation_result(
            journal,
            sequence=99,
            status=OperationOutcomeStatus.FAILED,
            message="No such operation",
        )


def test_finalize_journal_marks_run_finished():
    netbox = snapshot(InventorySource.NETBOX, [])
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [InventoryDevice(source_id="a", name="switch-a", site="HQ")],
    )

    dedup = deduplicate_inventory(netbox, unifi)
    preview = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(preview)
    plan = build_write_plan(preview, change)
    journal = initialize_journal(
        plan, run_id="run-4", started_at="2026-11-01T12:30:00+00:00"
    )

    finished = finalize_journal(
        journal,
        finished_at="2026-11-01T12:31:00+00:00",
        cancelled=True,
    )

    summary = summarize_journal(finished)
    assert finished.cancelled is True
    assert summary.finished is True


def test_reconcile_ambiguous_creates_flags_missing_object_id():
    netbox = snapshot(InventorySource.NETBOX, [])
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [InventoryDevice(source_id="a", name="switch-a", site="HQ")],
    )

    dedup = deduplicate_inventory(netbox, unifi)
    preview = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(preview)
    plan = build_write_plan(preview, change)

    journal = initialize_journal(
        plan, run_id="run-5", started_at="2026-11-01T12:40:00+00:00"
    )
    journal = record_operation_result(
        journal,
        sequence=1,
        status=OperationOutcomeStatus.SUCCESS,
        message="created",
    )

    ambiguous = reconcile_ambiguous_creates(plan, journal)

    assert len(ambiguous) == 1
    assert ambiguous[0].reason == "missing_object_id"
    assert ambiguous[0].sequence == 1


def test_reconcile_ambiguous_creates_flags_duplicate_object_id():
    netbox = snapshot(InventorySource.NETBOX, [])
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(source_id="a", name="switch-a", site="HQ"),
            InventoryDevice(source_id="b", name="switch-b", site="HQ"),
        ],
    )

    dedup = deduplicate_inventory(netbox, unifi)
    preview = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(preview)
    plan = build_write_plan(preview, change)

    journal = initialize_journal(
        plan, run_id="run-6", started_at="2026-11-01T12:50:00+00:00"
    )
    journal = record_operation_result(
        journal,
        sequence=1,
        status=OperationOutcomeStatus.SUCCESS,
        message="created",
        netbox_object_id="42",
    )
    journal = record_operation_result(
        journal,
        sequence=2,
        status=OperationOutcomeStatus.SUCCESS,
        message="created",
        netbox_object_id="42",
    )

    ambiguous = reconcile_ambiguous_creates(plan, journal)

    assert len(ambiguous) == 2
    assert {item.reason for item in ambiguous} == {"duplicate_object_id"}
    assert all(item.candidate_object_ids == ("42",) for item in ambiguous)
