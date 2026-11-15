"""The firmware Custom Field and firmware device writes (M11 slice 2)."""

import requests

from unifi2netbox.config import BehaviorConfig, NetBoxConfig
from unifi2netbox.custom_fields import (
    CONFLICT,
    CREATE,
    PAYLOAD,
    PRESENT,
    UNAVAILABLE,
    build_custom_field_plan,
    execute_custom_field_plan,
    select_custom_field,
)
from unifi2netbox.inventory import (
    InventoryCustomField,
    InventoryDevice,
    InventorySnapshot,
    InventorySource,
)
from unifi2netbox.matching import deduplicate_inventory
from unifi2netbox.pipeline import InventoryPreviewResult
from unifi2netbox.preview import (
    build_change_preview,
    build_difference_preview,
    select_field,
)
from unifi2netbox.review import ReviewState
from unifi2netbox.write_execute import AmbiguousWriteError, execute_write_plan
from unifi2netbox.write_journal import OperationOutcomeStatus, Verification
from unifi2netbox.write_plan import build_write_plan

FIELD = InventoryCustomField("8", "firmware", "text", ("dcim.device",))


def test_plan_states():
    assert build_custom_field_plan(()).action == CREATE
    assert build_custom_field_plan(()).selected
    assert build_custom_field_plan((FIELD,)).action == PRESENT
    wrong_type = InventoryCustomField("8", "firmware", "integer", ("dcim.device",))
    wrong_object = InventoryCustomField("8", "firmware", "text", ("dcim.site",))
    assert build_custom_field_plan((wrong_type,)).action == CONFLICT
    assert build_custom_field_plan((wrong_object,)).action == CONFLICT
    failed = build_custom_field_plan((), "NetBox custom fields could not be read.")
    assert failed.action == UNAVAILABLE and not failed.firmware_writable


def test_writability_follows_selection():
    plan = build_custom_field_plan(())
    off = select_custom_field(plan, False)

    assert plan.firmware_writable and plan.operation_count == 1
    assert not off.firmware_writable and off.operation_count == 0
    present = build_custom_field_plan((FIELD,))
    assert present.firmware_writable and present.operation_count == 0
    assert select_custom_field(present, False) == present


class FakeFields:
    def __init__(self, fields=None):
        self.fields = dict(fields or {})
        self.created = []
        self.fail = None
        self.apply_anyway = False

    def find_ids(self, path, **filters):
        assert path == "/api/extras/custom-fields/"
        return tuple(k for k, v in self.fields.items() if v["name"] == filters["name"])

    def read_object(self, path):
        return self.fields.get(path.rstrip("/").rsplit("/", 1)[-1])

    def create_object(self, path, payload):
        if self.fail:
            if self.apply_anyway:
                self.fields["66"] = dict(payload)
            raise self.fail
        self.created.append(payload)
        self.fields["60"] = dict(payload) | {"type": {"value": payload["type"]}}
        return "60"

    def update_object(self, path, payload):  # pragma: no cover - never called
        raise AssertionError("Custom Fields are never updated")


def test_create_writes_and_verifies():
    backend = FakeFields()

    outcomes, writable = execute_custom_field_plan(build_custom_field_plan(()), backend)

    (outcome,) = outcomes
    assert writable
    assert (outcome.status, outcome.object_id, outcome.verification) == (
        "success",
        "60",
        "verified",
    )
    assert backend.created == [PAYLOAD]
    assert PAYLOAD["object_types"] == ["dcim.device"] and PAYLOAD["type"] == "text"


def test_dry_run_present_and_deselected():
    backend = FakeFields()
    outcomes, writable = execute_custom_field_plan(
        build_custom_field_plan(()), backend, dry_run=True
    )
    assert writable and outcomes[0].status == "skipped" and not backend.created

    assert execute_custom_field_plan(build_custom_field_plan((FIELD,)), backend) == (
        (),
        True,
    )
    off = select_custom_field(build_custom_field_plan(()), False)
    assert execute_custom_field_plan(off, backend) == ((), False)
    assert execute_custom_field_plan(None, backend) == ((), False)


def test_field_created_since_preview_is_not_duplicated():
    backend = FakeFields({"5": {"name": "firmware"}})

    outcomes, writable = execute_custom_field_plan(build_custom_field_plan(()), backend)

    assert outcomes[0].status == "skipped" and not writable
    assert not backend.created


def test_interrupted_create_is_reconciled_not_retried():
    backend = FakeFields()
    backend.fail = requests.exceptions.Timeout("timed out")
    backend.apply_anyway = True
    backend.fields_after = None

    outcomes, writable = execute_custom_field_plan(build_custom_field_plan(()), backend)

    assert outcomes[0].status == "success" and outcomes[0].object_id == "66"
    assert "interrupted" in outcomes[0].message
    assert writable


def test_permission_error_explains_the_token():
    from unifi2netbox.write_execute import WriteExecutionError

    backend = FakeFields()
    backend.fail = WriteExecutionError("NetBox write permission denied.")

    outcomes, writable = execute_custom_field_plan(build_custom_field_plan(()), backend)

    assert outcomes[0].status == "failed" and not writable
    assert "permission to add Custom Fields" in outcomes[0].message


def test_ambiguous_create_without_result_fails():
    backend = FakeFields()
    backend.fail = AmbiguousWriteError("HTTP 502")

    outcomes, writable = execute_custom_field_plan(build_custom_field_plan(()), backend)

    assert outcomes[0].status == "failed" and not writable


# -- firmware as a device field ------------------------------------------------


def snap(source, devices):
    return InventorySnapshot(source=source, captured_at="x", devices=tuple(devices))


NETBOX = snap(
    InventorySource.NETBOX,
    [InventoryDevice("1", "sw", site="HQ", firmware="7.1.0")],
)
UNIFI = snap(
    InventorySource.UNIFI_NETWORK,
    [InventoryDevice("a", "sw", site="HQ", firmware="7.2.3")],
)


def preview(writable):
    return build_difference_preview(
        NETBOX, UNIFI, deduplicate_inventory(NETBOX, UNIFI), firmware_writable=writable
    )


def firmware(diff):
    return next(f for f in diff.devices[0].fields if f.name == "firmware")


def test_firmware_is_selectable_only_with_the_field():
    assert firmware(preview(True)).selected
    blocked = firmware(preview(False))
    assert blocked.changed and not blocked.selectable
    assert "Custom Field 'firmware'" in blocked.provenance


def test_create_selects_firmware_only_with_the_field():
    empty = snap(InventorySource.NETBOX, [])
    for writable in (True, False):
        diff = build_difference_preview(
            empty,
            UNIFI,
            deduplicate_inventory(empty, UNIFI),
            firmware_writable=writable,
        )
        assert firmware(diff).selected is writable


class FirmwareBackend:
    def __init__(self, firmware="7.1.0"):
        self.row = {
            "id": "1",
            "name": "sw",
            "site": {"name": "HQ"},
            "custom_fields": {"firmware": firmware, "other": "kept"},
        }
        self.updates = []

    def read_device(self, device_id):
        return self.row

    def find_device_ids(self, **filters):
        return ()

    def resolve_site_id(self, name):
        return "11"

    def update_device(self, device_id, payload):
        self.updates.append(payload)
        self.row = self.row | {
            "custom_fields": self.row["custom_fields"] | payload["custom_fields"]
        }


def run(diff, backend, writable):
    plan = build_write_plan(diff, build_change_preview(diff))
    return execute_write_plan(
        plan,
        diff,
        NetBoxConfig("https://netbox.invalid", "token"),
        BehaviorConfig(),
        run_id="r",
        started_at="s",
        finished_at="f",
        backend=backend,
        firmware_writable=writable,
    ).journal.outcomes


def test_firmware_update_patches_only_the_custom_field_and_verifies():
    backend = FirmwareBackend()

    (outcome,) = run(preview(True), backend, True)

    assert backend.updates == [{"custom_fields": {"firmware": "7.2.3"}}]
    assert outcome.status == OperationOutcomeStatus.SUCCESS
    assert outcome.verification == Verification.VERIFIED


def test_firmware_without_field_fails_visibly():
    backend = FirmwareBackend()

    (outcome,) = run(preview(True), backend, False)

    assert outcome.status == OperationOutcomeStatus.FAILED
    assert "Custom Field 'firmware'" in outcome.message
    assert backend.updates == []


def test_firmware_drift_in_netbox_skips_the_update():
    backend = FirmwareBackend(firmware="7.1.9")

    (outcome,) = run(preview(True), backend, True)

    assert outcome.status == OperationOutcomeStatus.SKIPPED
    assert "firmware" in outcome.message and backend.updates == []


def test_review_couples_firmware_and_custom_field():
    diff = preview(True)
    result = InventoryPreviewResult(
        status="Ready",
        details="",
        difference_preview=diff,
        custom_field_plan=build_custom_field_plan(()),
    )
    state = ReviewState(result)
    key = diff.devices[0].device_key

    state.set_custom_field_selected(False)
    assert state.custom_field_operation_count() == 0
    assert state.firmware_selected_count() == 0

    state.set_field_selected(key, "firmware", True)
    assert state.custom_field_operation_count() == 1
    assert state.firmware_selected_count() == 1

    # Unselecting firmware keeps the explicit create choice.
    state.diff = select_field(state.diff, key, "firmware", False)
    state._recompute()
    assert state.custom_field_operation_count() == 1
