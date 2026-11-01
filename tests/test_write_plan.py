from unifi2netbox.inventory import InventoryDevice, InventorySnapshot, InventorySource
from unifi2netbox.matching import deduplicate_inventory
from unifi2netbox.preview import (
    build_change_preview,
    build_difference_preview,
    select_field,
)
from unifi2netbox.write_plan import (
    IssueSeverity,
    OperationType,
    build_write_plan,
)


def snapshot(
    source: InventorySource, devices: list[InventoryDevice]
) -> InventorySnapshot:
    return InventorySnapshot(
        source=source,
        captured_at="2026-11-01T10:00:00+00:00",
        source_version="x",
        devices=tuple(devices),
    )


def test_write_plan_orders_create_before_update():
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
    diff = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change)

    assert plan.executable is True
    assert [item.operation_type for item in plan.operations] == [
        OperationType.CREATE_DEVICE,
        OperationType.UPDATE_DEVICE,
    ]
    assert [item.sequence for item in plan.operations] == [1, 2]
    assert plan.summary.total_operations == 2
    assert plan.summary.create_operations == 1
    assert plan.summary.update_operations == 1
    assert plan.summary.blocker_issues == 0
    assert plan.summary.requires_confirmation is True
    assert "Confirm execution of 2 operations" in plan.summary.confirmation_message


def test_write_plan_blocks_on_dependency_failure():
    netbox = snapshot(
        InventorySource.NETBOX,
        [
            InventoryDevice(
                source_id="1",
                name="switch-a",
                manufacturer="Ubiquiti",
                model="USW-24",
                serial="S1",
            )
        ],
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(
                source_id="a",
                name="switch-a",
                manufacturer="Ubiquity",
                model="USW-48",
                serial="S1",
            )
        ],
    )

    dedup = deduplicate_inventory(netbox, unifi)
    diff = build_difference_preview(netbox, unifi, dedup)
    update = next(item for item in diff.devices if item.action.value == "update")
    diff = select_field(diff, update.device_key, "manufacturer", False)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change)

    assert plan.executable is False
    assert any(issue.code == "dependency_blocked" for issue in plan.issues)
    assert plan.summary.blocker_issues >= 1
    assert plan.summary.requires_confirmation is False
    assert update.device_key in plan.summary.blocked_device_keys
    assert "No eligible operations selected" in plan.summary.confirmation_message


def test_write_plan_blocks_duplicate_creates():
    netbox = snapshot(InventorySource.NETBOX, [])
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(source_id="a", name="dup", site="HQ"),
            InventoryDevice(source_id="b", name="dup", site="HQ"),
        ],
    )

    dedup = deduplicate_inventory(netbox, unifi)
    diff = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change)

    assert plan.executable is False
    duplicate_issues = [
        issue for issue in plan.issues if issue.code == "duplicate_create_name"
    ]
    assert len(duplicate_issues) == 2
    assert all(issue.severity == IssueSeverity.BLOCKER for issue in duplicate_issues)


def test_write_plan_ignores_target_only_rows():
    netbox = snapshot(
        InventorySource.NETBOX, [InventoryDevice(source_id="1", name="only-netbox")]
    )
    unifi = snapshot(InventorySource.UNIFI_NETWORK, [])

    dedup = deduplicate_inventory(netbox, unifi)
    diff = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change)

    assert plan.operations == ()
    assert plan.executable is False
    assert plan.summary.total_operations == 0
    assert plan.summary.requires_confirmation is False
    assert "No eligible operations selected" in plan.summary.confirmation_message
