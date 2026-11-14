from unifi2netbox.config import BehaviorConfig, NetBoxConfig
from unifi2netbox.inventory import InventoryDevice, InventorySnapshot, InventorySource
from unifi2netbox.matching import deduplicate_inventory
from unifi2netbox.preview import build_change_preview, build_difference_preview
from unifi2netbox.write_execute import WriteExecutionError, execute_write_plan
from unifi2netbox.write_journal import OperationOutcomeStatus
from unifi2netbox.write_plan import build_write_plan


def netbox_row(device: InventoryDevice) -> dict[str, object]:
    return {
        "id": device.source_id,
        "name": device.name,
        "serial": device.serial,
        "site": {"name": device.site} if device.site else None,
        "device_type": {
            "model": device.model,
            "manufacturer": {"name": device.manufacturer},
        },
        "primary_mac_address": device.mac_address or None,
    }


class FakeBackend:
    def __init__(self, netbox: InventorySnapshot | None = None):
        self.created_payloads = []
        self.updated_payloads = []
        self.rows = {
            device.source_id: netbox_row(device)
            for device in (netbox.devices if netbox else ())
        }

    def read_device(self, device_id: str) -> dict[str, object] | None:
        return self.rows.get(device_id)

    def find_device_ids(self, **filters: str) -> tuple[str, ...]:
        return tuple(
            row_id
            for row_id, row in self.rows.items()
            if all(str(row.get(key, "")) == value for key, value in filters.items())
        )

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

    backend = FakeBackend(netbox)
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

    backend = FakeBackend(netbox)
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

    backend = FakeBackend(netbox)
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
            "role": "21",
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

    backend = FakeBackend(netbox)
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
    backend = FakeBackend(netbox)
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

    backend = FakeBackend(netbox)
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
    assert backend.created_payloads[0]["role"] == "21"


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

    backend = FakeBackend(netbox)
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

    backend = FakeBackend(netbox)
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

    backend = FakeBackend(netbox)
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


def _update_plan_fixture():
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
    plan = build_write_plan(diff, build_change_preview(diff))
    return netbox, diff, plan


def _run(plan, diff, backend, *, dry_run=False, behavior=None):
    return execute_write_plan(
        plan,
        diff,
        NetBoxConfig("https://netbox.invalid", "token"),
        behavior or BehaviorConfig(),
        run_id="run-stale",
        started_at="2026-11-01T16:00:00+00:00",
        finished_at="2026-11-01T16:01:00+00:00",
        dry_run=dry_run,
        backend=backend,
    )


def test_update_skipped_when_netbox_value_changed_since_preview():
    netbox, diff, plan = _update_plan_fixture()
    backend = FakeBackend(netbox)
    backend.rows["1"]["serial"] = "EDITED-BY-SOMEONE"

    result = _run(plan, diff, backend)

    outcome = result.journal.outcomes[0]
    assert outcome.status == OperationOutcomeStatus.SKIPPED
    assert "changed since the preview (serial)" in outcome.message
    assert backend.updated_payloads == []


def test_update_skipped_when_netbox_device_was_deleted():
    netbox, diff, plan = _update_plan_fixture()
    backend = FakeBackend(netbox)
    del backend.rows["1"]

    result = _run(plan, diff, backend)

    outcome = result.journal.outcomes[0]
    assert outcome.status == OperationOutcomeStatus.SKIPPED
    assert "no longer exists" in outcome.message
    assert backend.updated_payloads == []


def test_update_ignores_changes_to_unselected_fields():
    netbox, diff, plan = _update_plan_fixture()
    backend = FakeBackend(netbox)
    backend.rows["1"]["primary_mac_address"] = "AA:BB:CC:DD:EE:FF"

    result = _run(plan, diff, backend)

    assert result.journal.outcomes[0].status == OperationOutcomeStatus.SUCCESS
    assert backend.updated_payloads == [("1", {"serial": "NEW"})]


def test_dry_run_reports_stale_preview():
    netbox, diff, plan = _update_plan_fixture()
    backend = FakeBackend(netbox)
    backend.rows["1"]["serial"] = "EDITED-BY-SOMEONE"

    result = _run(plan, diff, backend, dry_run=True)

    outcome = result.journal.outcomes[0]
    assert outcome.status == OperationOutcomeStatus.SKIPPED
    assert "changed since the preview" in outcome.message


def _create_plan_fixture():
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
    plan = build_write_plan(diff, build_change_preview(diff))
    return netbox, diff, plan


ROLE = BehaviorConfig(default_device_role_name="Network Device")


def test_create_skipped_when_device_with_same_name_appeared():
    netbox, diff, plan = _create_plan_fixture()
    backend = FakeBackend(netbox)
    backend.rows["77"] = netbox_row(
        InventoryDevice(source_id="77", name="switch-a", site="HQ")
    )

    result = _run(plan, diff, backend, behavior=ROLE)

    outcome = result.journal.outcomes[0]
    assert outcome.status == OperationOutcomeStatus.SKIPPED
    assert "name 'switch-a' now exists (ID 77)" in outcome.message
    assert backend.created_payloads == []


def test_create_skipped_when_device_with_same_serial_appeared():
    netbox, diff, plan = _create_plan_fixture()
    backend = FakeBackend(netbox)
    backend.rows["78"] = netbox_row(
        InventoryDevice(source_id="78", name="other", serial="SER-1", site="HQ")
    )

    result = _run(plan, diff, backend, behavior=ROLE)

    outcome = result.journal.outcomes[0]
    assert outcome.status == OperationOutcomeStatus.SKIPPED
    assert "serial 'SER-1'" in outcome.message
    assert backend.created_payloads == []


class FailingReadBackend(FakeBackend):
    def read_device(self, device_id: str) -> dict[str, object] | None:
        raise WriteExecutionError("NetBox device read failed with HTTP 500.")


def test_update_fails_when_pre_write_read_fails():
    netbox, diff, plan = _update_plan_fixture()
    backend = FailingReadBackend(netbox)

    result = _run(plan, diff, backend)

    outcome = result.journal.outcomes[0]
    assert outcome.status == OperationOutcomeStatus.FAILED
    assert outcome.message.startswith("Pre-write NetBox re-read failed")
    assert backend.updated_payloads == []
