"""Import of chosen device type definitions into NetBox (M12 slice 6)."""

from pathlib import Path

import requests

from unifi2netbox.devicetype_import import (
    BLOCKED,
    CREATE,
    PENDING_ID,
    REUSE,
    build_import_plan,
    execute_import_plan,
    select_import,
)
from unifi2netbox.devicetypes import load_yaml
from unifi2netbox.inventory import InventoryDeviceType, InventoryManufacturer

FIXTURES = Path(__file__).parent / "fixtures" / "devicetype-library" / "device-types"
PRO = load_yaml((FIXTURES / "Ubiquiti" / "USW-Pro-24.yaml").read_text(encoding="utf-8"))
CISCO = load_yaml((FIXTURES / "Cisco" / "C9300-24P.yaml").read_text(encoding="utf-8"))
MAKERS = (InventoryManufacturer("41", "Ubiquiti"),)
CHOICE = "library:Ubiquiti/USW-Pro-24.yaml"


def plan(choices=None, docs=None, types=(), deselected=()):
    return build_import_plan(
        choices or {"create:a": CHOICE, "create:b": CHOICE},
        docs or {CHOICE: PRO},
        {CHOICE: "Ubiquiti USW-Pro-24 (library)"},
        MAKERS,
        types,
        deselected,
    )


def test_plan_rows_create_reuse_and_blocked():
    (row,) = plan().rows
    assert row.action == CREATE and row.selected
    assert row.device_keys == ("create:a", "create:b")
    assert row.manufacturer_id == "41" and row.template_count == 28
    assert plan().device_status(CHOICE) == (
        "ready",
        "The device type is imported into NetBox on apply.",
    )

    (reuse,) = plan(
        types=(InventoryDeviceType("9", "Ubiquiti", "Something", "USW-Pro-24"),)
    ).rows
    assert reuse.action == REUSE and reuse.netbox_id == "9" and not reuse.selectable

    cisco = "local:C:/types/C9300-24P.yaml"
    (blocked,) = plan({"create:c": cisco}, {cisco: CISCO}).rows
    assert blocked.action == BLOCKED
    assert "Manufacturer 'Cisco' is not in NetBox" in blocked.notes[0]

    missing = plan({"create:d": "local:gone.yaml"}, {}).rows[0]
    assert missing.action == BLOCKED and "could not be loaded" in missing.notes[0]

    off = select_import(plan(), CHOICE, False)
    assert off.operation_count == 0
    assert off.device_status(CHOICE)[0] == BLOCKED
    assert plan(deselected={CHOICE}).operation_count == 0


class FakeNetBox:
    def __init__(self):
        self.objects: dict[str, tuple[str, dict]] = {}
        self.created: list[tuple[str, dict]] = []
        self.fail_type = None
        self.fail_names = set()

    def find_ids(self, path, **filters):
        filters.pop("limit", None)
        result = []
        for key, (kind, obj) in self.objects.items():
            if kind != path:
                continue
            if all(
                str(obj.get(f if f != "device_type_id" else "device_type")) == str(v)
                for f, v in filters.items()
            ):
                result.append(key)
        return tuple(result)

    def read_object(self, path):
        key = path.rstrip("/").rsplit("/", 1)[-1]
        entry = self.objects.get(key)
        return entry[1] if entry else None

    def create_object(self, path, payload):
        key = str(100 + len(self.objects))
        if path.endswith("device-types/") and self.fail_type:
            self.objects[key] = (path, dict(payload))
            raise self.fail_type
        if payload.get("name") in self.fail_names:
            raise requests.exceptions.HTTPError("400 Bad Request")
        self.created.append((path, payload))
        self.objects[key] = (path, dict(payload))
        return key


def with_manufacturer():
    backend = FakeNetBox()
    backend.objects["41"] = ("/api/dcim/manufacturers/", {"name": "Ubiquiti"})
    return backend


def test_import_creates_type_and_templates_and_verifies():
    backend = with_manufacturer()

    outcomes, overrides = execute_import_plan(plan(), backend)

    (outcome,) = outcomes
    assert outcome.status == "success" and outcome.verification == "verified"
    assert "with 28 component templates" in outcome.message
    type_path, type_payload = backend.created[0]
    assert type_path == "/api/dcim/device-types/"
    assert type_payload["manufacturer"] == 41 and type_payload["slug"] == (
        "ubiquiti-unifi-switch-24-pro"
    )
    assert "front_image" not in type_payload
    interfaces = [p for path, p in backend.created if "interface-templates" in path]
    assert len(interfaces) == 26 and interfaces[0]["device_type"] == int(
        outcome.object_id
    )
    assert overrides == {"create:a": outcome.object_id, "create:b": outcome.object_id}


def test_existing_slug_is_reused_and_dry_run_writes_nothing():
    backend = with_manufacturer()
    backend.objects["7"] = (
        "/api/dcim/device-types/",
        {"slug": "ubiquiti-unifi-switch-24-pro"},
    )
    (outcome,), overrides = execute_import_plan(plan(), backend)
    assert outcome.object_id == "7" and "used as is" in outcome.message
    assert overrides["create:a"] == "7" and backend.created == []

    dry = with_manufacturer()
    (outcome,), overrides = execute_import_plan(plan(), dry, dry_run=True)
    assert outcome.status == "skipped" and dry.created == []
    assert overrides["create:a"] == PENDING_ID


def test_blocked_deselected_and_failed_imports_skip_their_devices():
    backend = FakeNetBox()  # no manufacturer in NetBox
    (outcome,), overrides = execute_import_plan(plan(), backend)
    assert outcome.status == "skipped"
    assert overrides["create:a"].startswith("skip:Device type")

    outcomes, overrides = execute_import_plan(plan(deselected={CHOICE}), backend)
    assert outcomes == () and "not selected" in overrides["create:b"]

    reuse = plan(types=(InventoryDeviceType("9", "Ubiquiti", "UniFi Switch 24 Pro"),))
    assert execute_import_plan(reuse, backend) == (
        (),
        {"create:a": "9", "create:b": "9"},
    )


def test_interrupted_type_create_is_looked_up_and_template_failures_reported():
    backend = with_manufacturer()
    backend.fail_type = requests.exceptions.Timeout("timed out")
    (outcome,), _ = execute_import_plan(plan(), backend)
    assert outcome.status == "success" and "interrupted" in outcome.message

    broken = with_manufacturer()
    broken.fail_names = {"Port 3"}
    (outcome,), overrides = execute_import_plan(plan(), broken)
    assert outcome.status == "failed" and "1 of 28 templates failed" in outcome.message
    assert outcome.verification == "mismatch" and "interfaces (25 of 26)" in (
        outcome.verification_detail
    )
    assert overrides["create:a"] == outcome.object_id


def test_skip_override_skips_the_device_create():
    from test_gui import preview_result

    from unifi2netbox.config import BehaviorConfig, NetBoxConfig
    from unifi2netbox.review import single_operation_plan
    from unifi2netbox.write_execute import execute_write_plan

    result = preview_result()
    create = next(
        op for op in result.write_plan.operations if op.device_key.startswith("create:")
    )
    # Only the create: nothing else may touch the (absent) backend.
    plan_ = single_operation_plan(result.write_plan, create.device_key)
    report = execute_write_plan(
        plan_,
        result.difference_preview,
        NetBoxConfig(url="https://netbox.example.com", token="t"),
        BehaviorConfig(default_device_role_name="Switch"),
        run_id="r",
        started_at="s",
        finished_at="f",
        dry_run=True,
        device_type_overrides={
            create.device_key: "skip:Device type X was not imported"
        },
        backend=object(),
    )
    outcome = next(
        o for o in report.journal.outcomes if o.device_key == create.device_key
    )
    assert str(outcome.status) == "skipped"
    assert outcome.message == "Device type X was not imported"
