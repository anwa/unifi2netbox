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
    assert outcome.status == "failed" and "1 of 28 steps failed" in outcome.message
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


# -- M13 slice 4: all fields, references, templates and images ----------------

FULL = load_yaml(
    "---\n"
    "manufacturer: Ubiquiti\n"
    "model: Lab Box\n"
    "slug: ubiquiti-lab-box\n"
    "u_height: 1\n"
    "is_full_depth: false\n"
    "cooling_method: air\n"
    "end_of_life: 2031-12-31\n"
    "exclude_from_utilization: true\n"
    "owner: Network team\n"
    "default_platform: UniFi OS\n"
    "tags: [core]\n"
    "front_image: true\n"
    "custom_fields:\n  support: gold\n"
    "power-ports:\n  - name: PSU 1\n    type: iec-60320-c14\n"
    "power-outlets:\n  - name: Out 1\n    type: iec-60320-c13\n"
    "    power_port: PSU 1\n"
    "interfaces:\n"
    "  - name: eth0\n    type: 1000base-t\n"
    "  - name: eth0.10\n    type: virtual\n    parent: eth0\n"
    "  - name: br0\n    type: bridge\n"
    "  - name: eth1\n    type: 1000base-t\n    bridge: br0\n"
    "front-ports:\n  - name: F1\n    type: 8p8c\n    positions: 1\n"
    "rear-ports:\n  - name: R1\n    type: 8p8c\n    positions: 2\n"
    "port-mappings:\n"
    "  - front_port: F1\n    front_port_position: 1\n"
    "    rear_port: R1\n    rear_port_position: 2\n"
    "cooling-intakes:\n  - name: In 1\n    type: uqd\n"
    "cooling-outflows:\n  - name: Out A\n    type: uqd\n    cooling_intake: In 1\n"
    "inventory-items:\n"
    "  - name: Fan 1\n    parent: Tray\n"
    "  - name: Tray\n    role: Fan tray\n    manufacturer: Ubiquiti\n"
    "    component_type: dcim.powerporttemplate\n    component_name: PSU 1\n"
)
FULL_CHOICE = "local:C:/types/Ubiquiti/Lab Box.yaml"


class FullNetBox(FakeNetBox):
    def __init__(self):
        super().__init__()
        self.objects.update(
            {
                "41": ("/api/dcim/manufacturers/", {"name": "Ubiquiti"}),
                "51": ("/api/users/owners/", {"name": "Network team"}),
                "52": ("/api/dcim/platforms/", {"name": "x", "slug": "UniFi OS"}),
                "53": ("/api/extras/tags/", {"name": "Core", "slug": "core"}),
                "54": ("/api/dcim/inventory-item-roles/", {"name": "Fan tray"}),
            }
        )
        self.updates = []
        self.uploads = []

    def update_object(self, path, payload):
        self.updates.append((path, payload))

    def upload_files(self, path, files):
        self.uploads.append((path, sorted(files)))
        key = path.rstrip("/").rsplit("/", 1)[-1]
        for name in files:
            self.objects[key][1][name] = "/media/x.png"

    def payload(self, endpoint, name):
        return next(
            p
            for path, p in self.created
            if endpoint in path and (p.get("name") == name)
        )


def full_plan(images=None):
    return build_import_plan(
        {"create:x": FULL_CHOICE},
        {FULL_CHOICE: FULL},
        {},
        MAKERS,
        (),
        images={FULL_CHOICE: images} if images else None,
    )


def test_full_definition_is_imported_with_references_mappings_and_images(tmp_path):
    image = tmp_path / "ubiquiti-lab-box.front.png"
    image.write_bytes(b"png")
    (row,) = full_plan({"front": str(image)}).rows
    assert row.action == CREATE and row.images == (("front_image", str(image)),)
    assert "uploads 1 image(s)" in row.notes[0]
    backend = FullNetBox()

    (outcome,), overrides = execute_import_plan(
        full_plan({"front": str(image)}), backend
    )

    assert outcome.status == "success", outcome.message
    assert outcome.verification == "verified", outcome.verification_detail
    _, device_type = backend.created[0]
    assert device_type["owner"] == 51 and device_type["default_platform"] == 52
    assert device_type["tags"] == [53]
    assert device_type["custom_fields"] == {"support": "gold"}
    assert device_type["end_of_life"] == "2031-12-31"
    assert device_type["cooling_method"] == "air"
    assert device_type["exclude_from_utilization"] is True
    assert "front_image" not in device_type
    ids = {p.get("name"): key for key, (path, p) in backend.objects.items()}
    outlet = backend.payload("power-outlet", "Out 1")
    assert outlet["power_port"] == int(ids["PSU 1"])
    front = backend.payload("front-port", "F1")
    assert front["rear_ports"] == [
        {"position": 1, "rear_port": int(ids["R1"]), "rear_port_position": 2}
    ]
    assert backend.payload("cooling-outflow", "Out A")["cooling_intake"] == int(
        ids["In 1"]
    )
    tray = backend.payload("inventory-item", "Tray")
    fan = backend.payload("inventory-item", "Fan 1")
    assert tray["role"] == 54 and tray["manufacturer"] == 41
    assert tray["component_type"] == "dcim.powerporttemplate"
    assert tray["component_id"] == int(ids["PSU 1"])
    assert fan["parent"] == int(ids["Tray"])
    order = [p.get("name") for _path, p in backend.created]
    assert order.index("R1") < order.index("F1")
    assert order.index("Tray") < order.index("Fan 1")
    assert sorted(backend.updates) == [
        (
            f"/api/dcim/interface-templates/{ids['eth0.10']}/",
            {"parent": int(ids["eth0"])},
        ),
        (f"/api/dcim/interface-templates/{ids['eth1']}/", {"bridge": int(ids["br0"])}),
    ]
    assert backend.uploads == [
        (f"/api/dcim/device-types/{outcome.object_id}/", ["front_image"])
    ]
    assert "and 1 image(s)" in outcome.message
    assert overrides == {"create:x": outcome.object_id}


def test_missing_references_stop_the_import_before_any_write():
    backend = FullNetBox()
    del backend.objects["53"]  # the tag
    del backend.objects["51"]  # the owner
    for dry_run in (True, False):
        (outcome,), overrides = execute_import_plan(
            full_plan(), backend, dry_run=dry_run
        )
        assert outcome.status == "skipped"
        assert "owner 'Network team'" in outcome.message
        assert "tag 'core'" in outcome.message
        assert overrides["create:x"].startswith("skip:")
    assert backend.created == []


def test_plan_notes_images_without_files():
    (row,) = full_plan().rows
    assert row.images == ()
    assert any("No local file for front_image" in note for note in row.notes)


def test_backend_uploads_images_as_multipart(tmp_path):
    from unifi2netbox.config import NetBoxConfig
    from unifi2netbox.write_execute import RequestsNetBoxWriteBackend

    image = tmp_path / "x.front.png"
    image.write_bytes(b"\x89PNG")
    backend = RequestsNetBoxWriteBackend(
        NetBoxConfig(url="https://netbox.example.com", token="t")
    )
    sent = []

    def send(request, **kwargs):
        sent.append(request)
        response = requests.Response()
        response.status_code = 200
        return response

    backend.session.send = send
    backend.upload_files("/api/dcim/device-types/5/", {"front_image": image})

    (request,) = sent
    assert request.method == "PATCH"
    assert request.url == "https://netbox.example.com/api/dcim/device-types/5/"
    assert request.headers["Content-Type"].startswith("multipart/form-data")
    assert b'name="front_image"; filename="x.front.png"' in request.body
    assert request.headers["Authorization"] == "Token t"
