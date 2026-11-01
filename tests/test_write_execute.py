from unifi2netbox.config import BehaviorConfig, NetBoxConfig
from unifi2netbox.inventory import InventoryDevice, InventorySnapshot, InventorySource
from unifi2netbox.matching import deduplicate_inventory
from unifi2netbox.preview import build_change_preview, build_difference_preview
from unifi2netbox.write_execute import WriteExecutionError, execute_write_plan
from unifi2netbox.write_journal import OperationOutcomeStatus
from unifi2netbox.write_plan import build_write_plan


class FakeBackend:
    def __init__(self):
        self.created_payloads = []
        self.updated_payloads = []

    def resolve_site_id(self, name: str) -> str:
        values = {"HQ": "11", "Branch": "12"}
        if name not in values:
            raise WriteExecutionError(f"Unknown site '{name}'.")
        return values[name]

    def resolve_role_id(self, name: str) -> str:
        values = {"Network Device": "21"}
        if name not in values:
            raise WriteExecutionError(f"Unknown role '{name}'.")
        return values[name]

    def resolve_device_type_id(self, manufacturer: str, model: str) -> str:
        key = (manufacturer, model)
        values = {("Ubiquiti", "USW-24"): "31"}
        if key not in values:
            raise WriteExecutionError("Unknown device type.")
        return values[key]

    def create_device(self, payload: dict[str, object]) -> str:
        self.created_payloads.append(payload)
        return "9001"

    def update_device(self, device_id: str, payload: dict[str, object]) -> None:
        self.updated_payloads.append((device_id, payload))


def snapshot(
    source: InventorySource, devices: list[InventoryDevice]
) -> InventorySnapshot:
    return InventorySnapshot(
        source=source,
        captured_at="2026-11-01T10:00:00+00:00",
        source_version="x",
        devices=tuple(devices),
    )


def test_execute_write_plan_updates_existing_device():
    netbox = snapshot(
        InventorySource.NETBOX,
        [InventoryDevice(source_id="1", name="switch-a", serial="OLD", site="HQ")],
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [InventoryDevice(source_id="a", name="switch-a", serial="NEW", site="HQ")],
    )

    dedup = deduplicate_inventory(netbox, unifi)
    diff = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change)

    backend = FakeBackend()
    result = execute_write_plan(
        plan,
        diff,
        NetBoxConfig("https://netbox.invalid", "token"),
        BehaviorConfig(),
        run_id="run-1",
        started_at="2026-11-01T15:00:00+00:00",
        finished_at="2026-11-01T15:01:00+00:00",
        backend=backend,
    )

    assert len(result.journal.outcomes) == 1
    outcome = result.journal.outcomes[0]
    assert outcome.status == OperationOutcomeStatus.SUCCESS
    assert outcome.netbox_object_id == "1"
    assert backend.updated_payloads == [("1", {"serial": "NEW"})]


def test_execute_write_plan_create_requires_role_setting():
    netbox = snapshot(InventorySource.NETBOX, [])
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(
                source_id="a",
                name="switch-a",
                serial="SER-1",
                site="HQ",
                manufacturer="Ubiquiti",
                model="USW-24",
            )
        ],
    )

    dedup = deduplicate_inventory(netbox, unifi)
    diff = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change)

    backend = FakeBackend()
    result = execute_write_plan(
        plan,
        diff,
        NetBoxConfig("https://netbox.invalid", "token"),
        BehaviorConfig(),
        run_id="run-2",
        started_at="2026-11-01T15:10:00+00:00",
        finished_at="2026-11-01T15:11:00+00:00",
        backend=backend,
    )

    assert len(result.journal.outcomes) == 1
    outcome = result.journal.outcomes[0]
    assert outcome.status == OperationOutcomeStatus.FAILED
    assert "default NetBox device role" in outcome.message
    assert backend.created_payloads == []


def test_execute_write_plan_create_success_with_role_setting():
    netbox = snapshot(InventorySource.NETBOX, [])
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(
                source_id="a",
                name="switch-a",
                serial="SER-1",
                site="HQ",
                manufacturer="Ubiquiti",
                model="USW-24",
            )
        ],
    )

    dedup = deduplicate_inventory(netbox, unifi)
    diff = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change)

    backend = FakeBackend()
    result = execute_write_plan(
        plan,
        diff,
        NetBoxConfig("https://netbox.invalid", "token"),
        BehaviorConfig(default_device_role_name="Network Device"),
        run_id="run-3",
        started_at="2026-11-01T15:20:00+00:00",
        finished_at="2026-11-01T15:21:00+00:00",
        backend=backend,
    )

    assert len(result.journal.outcomes) == 1
    outcome = result.journal.outcomes[0]
    assert outcome.status == OperationOutcomeStatus.SUCCESS
    assert outcome.netbox_object_id == "9001"
    assert backend.created_payloads == [
        {
            "name": "switch-a",
            "site": "11",
            "device_role": "21",
            "device_type": "31",
            "serial": "SER-1",
        }
    ]


def test_execute_write_plan_dry_run_skips_without_backend_writes():
    netbox = snapshot(
        InventorySource.NETBOX,
        [InventoryDevice(source_id="1", name="switch-a", serial="OLD", site="HQ")],
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [InventoryDevice(source_id="a", name="switch-a", serial="NEW", site="HQ")],
    )

    dedup = deduplicate_inventory(netbox, unifi)
    diff = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change)

    backend = FakeBackend()
    result = execute_write_plan(
        plan,
        diff,
        NetBoxConfig("https://netbox.invalid", "token"),
        BehaviorConfig(),
        run_id="run-4",
        started_at="2026-11-01T15:30:00+00:00",
        finished_at="2026-11-01T15:31:00+00:00",
        dry_run=True,
        backend=backend,
    )

    assert len(result.journal.outcomes) == 1
    assert result.journal.outcomes[0].status == OperationOutcomeStatus.SKIPPED
    assert backend.created_payloads == []
    assert backend.updated_payloads == []


def test_execute_write_plan_continues_after_operation_failure():
    netbox = snapshot(
        InventorySource.NETBOX,
        [InventoryDevice(source_id="1", name="switch-a", serial="OLD", site="HQ")],
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(source_id="a", name="switch-a", serial="NEW", site="HQ"),
            InventoryDevice(
                source_id="b",
                name="switch-b",
                serial="SER-2",
                site="Branch",
                manufacturer="Ubiquiti",
                model="USW-24",
            ),
        ],
    )

    dedup = deduplicate_inventory(netbox, unifi)
    diff = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change)

    # Force create to fail by dropping role setting while update can still succeed.
    backend = FakeBackend()
    result = execute_write_plan(
        plan,
        diff,
        NetBoxConfig("https://netbox.invalid", "token"),
        BehaviorConfig(),
        run_id="run-5",
        started_at="2026-11-01T15:40:00+00:00",
        finished_at="2026-11-01T15:41:00+00:00",
        backend=backend,
    )

    statuses = [item.status for item in result.journal.outcomes]
    assert OperationOutcomeStatus.SUCCESS in statuses
    assert OperationOutcomeStatus.FAILED in statuses


def test_execute_write_plan_create_uses_role_override():
    netbox = snapshot(InventorySource.NETBOX, [])
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(
                source_id="a",
                name="switch-a",
                serial="SER-1",
                site="HQ",
                manufacturer="Ubiquiti",
                model="USW-24",
            )
        ],
    )

    dedup = deduplicate_inventory(netbox, unifi)
    diff = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change)

    backend = FakeBackend()
    result = execute_write_plan(
        plan,
        diff,
        NetBoxConfig("https://netbox.invalid", "token"),
        BehaviorConfig(),
        run_id="run-6",
        started_at="2026-11-01T15:50:00+00:00",
        finished_at="2026-11-01T15:51:00+00:00",
        role_overrides={"create:unifi_network:a": "Network Device"},
        backend=backend,
    )

    assert len(result.journal.outcomes) == 1
    assert result.journal.outcomes[0].status == OperationOutcomeStatus.SUCCESS
    assert backend.created_payloads[0]["device_role"] == "21"


def test_execute_write_plan_create_uses_site_override():
    netbox = snapshot(InventorySource.NETBOX, [])
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(
                source_id="a",
                name="switch-a",
                serial="SER-1",
                site="Branch",
                manufacturer="Ubiquiti",
                model="USW-24",
            )
        ],
    )

    dedup = deduplicate_inventory(netbox, unifi)
    diff = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change)

    backend = FakeBackend()
    result = execute_write_plan(
        plan,
        diff,
        NetBoxConfig("https://netbox.invalid", "token"),
        BehaviorConfig(default_device_role_name="Network Device"),
        run_id="run-7",
        started_at="2026-11-01T15:55:00+00:00",
        finished_at="2026-11-01T15:56:00+00:00",
        site_overrides={"create:unifi_network:a": "HQ"},
        backend=backend,
    )

    assert len(result.journal.outcomes) == 1
    assert result.journal.outcomes[0].status == OperationOutcomeStatus.SUCCESS
    assert backend.created_payloads[0]["site"] == "11"


def test_execute_write_plan_create_uses_status_override():
    netbox = snapshot(InventorySource.NETBOX, [])
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(
                source_id="a",
                name="switch-a",
                serial="SER-1",
                site="HQ",
                manufacturer="Ubiquiti",
                model="USW-24",
            )
        ],
    )

    dedup = deduplicate_inventory(netbox, unifi)
    diff = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change)

    backend = FakeBackend()
    result = execute_write_plan(
        plan,
        diff,
        NetBoxConfig("https://netbox.invalid", "token"),
        BehaviorConfig(default_device_role_name="Network Device"),
        run_id="run-8",
        started_at="2026-11-01T15:57:00+00:00",
        finished_at="2026-11-01T15:58:00+00:00",
        status_overrides={"create:unifi_network:a": "active"},
        backend=backend,
    )

    assert len(result.journal.outcomes) == 1
    assert result.journal.outcomes[0].status == OperationOutcomeStatus.SUCCESS
    assert backend.created_payloads[0]["status"] == "active"


def test_execute_write_plan_create_uses_device_type_override_id():
    netbox = snapshot(InventorySource.NETBOX, [])
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(
                source_id="a",
                name="switch-a",
                serial="SER-1",
                site="HQ",
                manufacturer="Ubiquiti",
                model="USW-Aggregation",
            )
        ],
    )

    dedup = deduplicate_inventory(netbox, unifi)
    diff = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change)

    backend = FakeBackend()
    result = execute_write_plan(
        plan,
        diff,
        NetBoxConfig("https://netbox.invalid", "token"),
        BehaviorConfig(default_device_role_name="Network Device"),
        run_id="run-9",
        started_at="2026-11-01T15:59:00+00:00",
        finished_at="2026-11-01T16:00:00+00:00",
        device_type_overrides={"create:unifi_network:a": "999"},
        backend=backend,
    )

    assert len(result.journal.outcomes) == 1
    assert result.journal.outcomes[0].status == OperationOutcomeStatus.SUCCESS
    assert backend.created_payloads[0]["device_type"] == "999"
