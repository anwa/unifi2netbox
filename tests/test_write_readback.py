from dataclasses import replace

from unifi2netbox.inventory import InventoryDevice, InventorySnapshot, InventorySource
from unifi2netbox.matching import deduplicate_inventory
from unifi2netbox.preview import build_change_preview, build_difference_preview
from unifi2netbox.write_journal import (
    OperationOutcomeStatus,
    finalize_journal,
    initialize_journal,
    record_operation_result,
)
from unifi2netbox.write_plan import OperationType, build_write_plan
from unifi2netbox.write_readback import build_readback_plan


def snapshot(
    source: InventorySource, devices: list[InventoryDevice]
) -> InventorySnapshot:
    return InventorySnapshot(
        source=source,
        captured_at="2026-11-01T10:00:00+00:00",
        source_version="x",
        devices=tuple(devices),
    )


def test_readback_plan_includes_successful_create_with_object_id():
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
        plan, run_id="run-rb-1", started_at="2026-11-01T13:00:00+00:00"
    )
    journal = record_operation_result(
        journal,
        sequence=1,
        status=OperationOutcomeStatus.SUCCESS,
        netbox_object_id="501",
    )

    readback = build_readback_plan(plan, journal)

    assert len(readback.requests) == 1
    assert readback.requests[0].operation_type == OperationType.CREATE_DEVICE
    assert readback.requests[0].netbox_object_id == "501"
    assert readback.skipped_sequences == ()


def test_readback_plan_includes_successful_update_from_device_key():
    netbox = snapshot(
        InventorySource.NETBOX,
        [InventoryDevice(source_id="1", name="switch-a", serial="S1", site="HQ")],
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(
                source_id="a", name="switch-a-renamed", serial="S1", site="HQ"
            )
        ],
    )

    dedup = deduplicate_inventory(netbox, unifi)
    preview = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(preview)
    plan = build_write_plan(preview, change)

    journal = initialize_journal(
        plan, run_id="run-rb-2", started_at="2026-11-01T13:10:00+00:00"
    )
    journal = record_operation_result(
        journal,
        sequence=1,
        status=OperationOutcomeStatus.SUCCESS,
        message="updated",
    )

    readback = build_readback_plan(plan, journal)

    assert len(readback.requests) == 1
    assert readback.requests[0].operation_type == OperationType.UPDATE_DEVICE
    assert readback.requests[0].netbox_object_id == "1"
    assert readback.skipped_sequences == ()


def test_readback_plan_skips_successful_create_without_object_id():
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
        plan, run_id="run-rb-3", started_at="2026-11-01T13:20:00+00:00"
    )
    journal = record_operation_result(
        journal,
        sequence=1,
        status=OperationOutcomeStatus.SUCCESS,
    )

    readback = build_readback_plan(plan, journal)

    assert readback.requests == ()
    assert readback.skipped_sequences == (1,)


def test_readback_plan_includes_only_successes_on_partial_failure():
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
        plan, run_id="run-rb-4", started_at="2026-11-01T13:30:00+00:00"
    )
    journal = record_operation_result(
        journal,
        sequence=1,
        status=OperationOutcomeStatus.SUCCESS,
        netbox_object_id="601",
    )
    journal = record_operation_result(
        journal,
        sequence=2,
        status=OperationOutcomeStatus.FAILED,
        message="simulated write failure",
    )

    readback = build_readback_plan(plan, journal)

    assert len(readback.requests) == 1
    assert readback.requests[0].sequence == 1
    assert readback.requests[0].netbox_object_id == "601"
    assert readback.skipped_sequences == ()


def test_readback_plan_stays_empty_on_cancel_without_successes():
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
        plan, run_id="run-rb-5", started_at="2026-11-01T13:40:00+00:00"
    )
    cancelled = finalize_journal(
        journal,
        finished_at="2026-11-01T13:41:00+00:00",
        cancelled=True,
    )

    readback = build_readback_plan(plan, cancelled)

    assert readback.requests == ()
    assert readback.skipped_sequences == ()


def test_readback_plan_skips_success_with_missing_plan_operation_sequence():
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
        plan, run_id="run-rb-6", started_at="2026-11-01T13:50:00+00:00"
    )
    journal = record_operation_result(
        journal,
        sequence=1,
        status=OperationOutcomeStatus.SUCCESS,
        netbox_object_id="701",
    )

    trimmed_plan = replace(plan, operations=())

    readback = build_readback_plan(trimmed_plan, journal)

    assert readback.requests == ()
    assert readback.skipped_sequences == (1,)
