import pytest
import requests

from unifi2netbox.config import BehaviorConfig, NetBoxConfig
from unifi2netbox.inventory import InventoryDevice, InventorySnapshot, InventorySource
from unifi2netbox.matching import deduplicate_inventory
from unifi2netbox.preview import build_change_preview, build_difference_preview
from unifi2netbox.write_execute import (
    AmbiguousWriteError,
    RequestsNetBoxWriteBackend,
    WriteExecutionError,
    execute_write_plan,
)
from unifi2netbox.write_journal import OperationOutcomeStatus, Verification
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

    SITE_NAMES = {"11": "HQ", "12": "Branch"}

    def create_device(self, payload: dict[str, object]) -> str:
        self.created_payloads.append(payload)
        device_id = str(9001 + len(self.created_payloads) - 1)
        self.rows[device_id] = {
            "id": device_id,
            "name": payload.get("name", ""),
            "serial": payload.get("serial", ""),
            "site": self._site(payload.get("site")),
            "role": {"id": payload.get("role")},
            "device_type": {"id": payload.get("device_type")},
            "status": {"value": payload.get("status", "active")},
        }
        return device_id

    def update_device(self, device_id: str, payload: dict[str, object]) -> None:
        self.updated_payloads.append((device_id, payload))
        row = self.rows.setdefault(device_id, {"id": device_id})
        for key, value in payload.items():
            row[key] = self._site(value) if key == "site" else value

    def _site(self, site_id: object) -> dict[str, object] | None:
        if site_id is None:
            return None
        return {"id": site_id, "name": self.SITE_NAMES.get(str(site_id), "")}


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


class NormalizingBackend(FakeBackend):
    """NetBox stores something other than what was sent."""

    def update_device(self, device_id: str, payload: dict[str, object]) -> None:
        super().update_device(device_id, payload)
        self.rows[device_id]["serial"] = "SOMETHING-ELSE"


class UnreadableAfterWriteBackend(FakeBackend):
    def __init__(self, netbox=None):
        super().__init__(netbox)
        self.wrote = False

    def update_device(self, device_id: str, payload: dict[str, object]) -> None:
        super().update_device(device_id, payload)
        self.wrote = True

    def read_device(self, device_id: str) -> dict[str, object] | None:
        if self.wrote:
            raise WriteExecutionError("NetBox device read failed with HTTP 500.")
        return super().read_device(device_id)


def test_successful_update_is_verified_by_read_back():
    netbox, diff, plan = _update_plan_fixture()
    backend = FakeBackend(netbox)

    outcome = _run(plan, diff, backend).journal.outcomes[0]

    assert outcome.status == OperationOutcomeStatus.SUCCESS
    assert outcome.verification == Verification.VERIFIED
    assert "matches" in outcome.verification_detail


def test_successful_create_is_verified_by_read_back():
    netbox, diff, plan = _create_plan_fixture()
    backend = FakeBackend(netbox)

    outcome = _run(plan, diff, backend, behavior=ROLE).journal.outcomes[0]

    assert outcome.status == OperationOutcomeStatus.SUCCESS
    assert outcome.netbox_object_id == "9001"
    assert outcome.verification == Verification.VERIFIED


def test_read_back_reports_mismatch_without_rewriting():
    netbox, diff, plan = _update_plan_fixture()
    backend = NormalizingBackend(netbox)

    outcome = _run(plan, diff, backend).journal.outcomes[0]

    assert outcome.status == OperationOutcomeStatus.SUCCESS
    assert outcome.verification == Verification.MISMATCH
    assert "serial: expected NEW, NetBox has SOMETHING-ELSE" in (
        outcome.verification_detail
    )
    assert len(backend.updated_payloads) == 1


def test_read_back_failure_leaves_write_successful_but_unverified():
    netbox, diff, plan = _update_plan_fixture()
    backend = UnreadableAfterWriteBackend(netbox)

    outcome = _run(plan, diff, backend).journal.outcomes[0]

    assert outcome.status == OperationOutcomeStatus.SUCCESS
    assert outcome.verification == Verification.UNVERIFIED
    assert outcome.verification_detail.startswith("Read-back failed")


def test_dry_run_and_skipped_operations_are_not_verified():
    netbox, diff, plan = _update_plan_fixture()

    dry = _run(plan, diff, FakeBackend(netbox), dry_run=True).journal.outcomes[0]

    assert dry.status == OperationOutcomeStatus.SKIPPED
    assert dry.verification == ""


class InterruptedCreateBackend(FakeBackend):
    """create_device fails ambiguously; ``copies`` devices exist afterwards."""

    def __init__(self, netbox=None, *, copies=1, error=None, lookup_fails=False):
        super().__init__(netbox)
        self.copies = copies
        self.error = error or requests.exceptions.ReadTimeout("read timed out")
        self.lookup_fails = lookup_fails
        self.create_calls = 0
        self.raising = False

    def create_device(self, payload):
        self.create_calls += 1
        for _ in range(self.copies):
            super().create_device(payload)
        self.raising = True
        raise self.error

    def find_device_ids(self, **filters):
        if self.lookup_fails and self.raising:
            raise WriteExecutionError("NetBox device lookup failed with HTTP 500.")
        return super().find_device_ids(**filters)


def test_interrupted_create_found_in_netbox_counts_as_created():
    netbox, diff, plan = _create_plan_fixture()
    backend = InterruptedCreateBackend(netbox)

    outcome = _run(plan, diff, backend, behavior=ROLE).journal.outcomes[0]

    assert backend.create_calls == 1
    assert outcome.status == OperationOutcomeStatus.SUCCESS
    assert outcome.netbox_object_id == "9001"
    assert "interrupted" in outcome.message
    assert "(ID 9001)" in outcome.message
    assert outcome.verification == Verification.VERIFIED


def test_interrupted_create_missing_in_netbox_fails_without_retry():
    netbox, diff, plan = _create_plan_fixture()
    backend = InterruptedCreateBackend(
        netbox, copies=0, error=requests.exceptions.ConnectionError("reset")
    )

    outcome = _run(plan, diff, backend, behavior=ROLE).journal.outcomes[0]

    assert backend.create_calls == 1
    assert outcome.status == OperationOutcomeStatus.FAILED
    assert "has no device 'switch-a'. Refresh, then retry." in outcome.message


def test_interrupted_create_with_several_matches_needs_review():
    netbox, diff, plan = _create_plan_fixture()
    backend = InterruptedCreateBackend(
        netbox, copies=2, error=AmbiguousWriteError("HTTP 504")
    )

    outcome = _run(plan, diff, backend, behavior=ROLE).journal.outcomes[0]

    assert outcome.status == OperationOutcomeStatus.FAILED
    assert "several devices named 'switch-a' (IDs 9001, 9002)" in outcome.message


def test_interrupted_create_with_failed_lookup_asks_for_manual_check():
    netbox, diff, plan = _create_plan_fixture()
    backend = InterruptedCreateBackend(netbox, lookup_fails=True)

    outcome = _run(plan, diff, backend, behavior=ROLE).journal.outcomes[0]

    assert backend.create_calls == 1
    assert outcome.status == OperationOutcomeStatus.FAILED
    assert "Check NetBox for 'switch-a' before retrying." in outcome.message


class _Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


@pytest.mark.parametrize(
    ("response", "ambiguous"),
    [
        (_Response(504), True),
        (_Response(502), True),
        (_Response(201, {"name": "x"}), True),
        (_Response(201, None), True),
        (_Response(400, {"name": ["required"]}), False),
    ],
)
def test_requests_backend_flags_ambiguous_create_answers(response, ambiguous):
    backend = RequestsNetBoxWriteBackend(NetBoxConfig("https://netbox.invalid", "t"))
    backend._request = lambda *args, **kwargs: response

    with pytest.raises(WriteExecutionError) as caught:
        backend.create_device({"name": "x"})

    assert isinstance(caught.value, AmbiguousWriteError) is ambiguous
