"""Device type sync with NetBox and its preflight (M14 slice 5)."""

import copy

import requests
from test_devicetype_import import FULL, FULL_CHOICE, MAKERS

from unifi2netbox.devicetype_import import build_import_plan, execute_import_plan
from unifi2netbox.devicetype_update import (
    LOCAL,
    NETBOX,
    SKIP,
    build_sync_plan,
    execute_sync,
    overwrite_decisions,
    read_type,
    sync_items,
)
from unifi2netbox.netbox_types import NetBoxType, NetBoxTypes, compare
from unifi2netbox.type_preflight import BLOCKER, WARNING, preflight

# FULL without the front image flag (imported without an image file).
BASE = copy.deepcopy(FULL)
BASE.pop("front_image")

REFERENCES = (
    "manufacturer",
    "owner",
    "default_platform",
    "power_port",
    "bridge",
    "cooling_intake",
    "role",
    "rack",
    "device_type",
)


class ApiNetBox:
    """Stores objects like the NetBox API returns them (nested references)."""

    def __init__(self):
        self.rows: dict[str, tuple[str, dict]] = {}
        self.writes = []
        self.fail_create = None
        self.seed("/api/dcim/manufacturers/", 41, name="Ubiquiti", slug="ubiquiti")
        self.seed("/api/users/owners/", 51, name="Network team")
        self.seed("/api/dcim/platforms/", 52, name="UniFi OS", slug="unifi-os")
        self.seed("/api/extras/tags/", 53, name="Core", slug="core")
        self.seed("/api/dcim/inventory-item-roles/", 54, name="Fan tray", slug="fan")

    def seed(self, path, object_id, **row):
        self.rows[str(object_id)] = (path, {"id": object_id, **row})

    def _ref(self, value):
        if isinstance(value, int) and str(value) in self.rows:
            row = self.rows[str(value)][1]
            return {"id": value, "name": row.get("name"), "slug": row.get("slug")}
        return value

    def _convert(self, payload):
        row = {}
        for key, value in payload.items():
            if key in REFERENCES or (key == "parent" and isinstance(value, int)):
                value = self._ref(value) if key != "parent" else value
            if key == "tags":
                value = [self._ref(v) for v in value]
            row[key] = value
        return row

    def _parent_refs(self, path, row):
        # Interface parents are nested objects in the API, inventory ones IDs.
        if "interface-templates" in path and isinstance(row.get("parent"), int):
            row["parent"] = self._ref(row["parent"])
        return row

    def find_ids(self, path, **filters):
        return tuple(str(r["id"]) for r in self.list_objects(path, **filters))

    def list_objects(self, path, **filters):
        filters.pop("limit", None)
        result = []
        for kind, row in self.rows.values():
            if kind != path:
                continue
            ok = True
            for key, value in filters.items():
                field = key[:-3] if key.endswith("_id") else key
                current = row.get(field)
                if isinstance(current, dict):
                    current = current.get("id")
                if str(current) != str(value):
                    ok = False
            if ok:
                result.append(copy.deepcopy(row))
        return result

    def read_object(self, path):
        key = path.rstrip("/").rsplit("/", 1)[-1]
        entry = self.rows.get(key)
        return copy.deepcopy(entry[1]) if entry else None

    def create_object(self, path, payload):
        object_id = 100 + len(self.rows)
        if self.fail_create and payload.get("name") == self.fail_create:
            self.rows[str(object_id)] = (path, {"id": object_id, **payload})
            raise requests.exceptions.Timeout("timed out")
        row = self._parent_refs(path, {"id": object_id, **self._convert(payload)})
        self.rows[str(object_id)] = (path, row)
        self.writes.append(("create", path, payload))
        return str(object_id)

    def update_object(self, path, payload):
        key = path.rstrip("/").rsplit("/", 1)[-1]
        kind, row = self.rows[key]
        row.update(self._parent_refs(kind, self._convert(payload)))
        self.writes.append(("update", path, payload))

    def upload_files(self, path, files):
        key = path.rstrip("/").rsplit("/", 1)[-1]
        for name in files:
            self.rows[key][1][name] = "/media/x.png"
        self.writes.append(("upload", path, sorted(files)))


def imported():
    """An API fake holding FULL, imported by the real import executor."""
    backend = ApiNetBox()
    plan = build_import_plan(
        {"create:x": FULL_CHOICE}, {FULL_CHOICE: FULL}, {}, MAKERS, ()
    )
    (outcome,), _ = execute_import_plan(plan, backend)
    assert outcome.status == "success", outcome.message
    return backend, outcome.object_id


def netbox_view(backend, type_id, devices=0):
    doc, _ids = read_type(backend, type_id)
    return NetBoxTypes((NetBoxType(type_id, doc, devices),), loaded=True)


def test_imported_type_reads_back_equal_to_its_definition():
    backend, type_id = imported()
    assert compare(BASE, netbox_view(backend, type_id)).status == "same"


def changed_local():
    local = copy.deepcopy(BASE)
    local["weight"] = 1.5
    local["weight_unit"] = "kg"
    local.pop("owner")  # missing locally: never cleared in NetBox
    local["interfaces"][3]["mgmt_only"] = True  # eth1
    local["interfaces"].append({"name": "eth2", "type": "1000base-t", "parent": "eth0"})
    local["port-mappings"][0]["rear_port_position"] = 1
    local["rear-ports"][0]["positions"] = 2
    return local


def test_overwrite_netbox_writes_local_values_and_keeps_netbox_only_rows():
    backend, type_id = imported()
    backend.seed(
        "/api/dcim/rear-port-templates/",
        900,
        name="R9",
        type="8p8c",
        positions=1,
        device_type={"id": int(type_id)},
    )
    local = changed_local()
    comparison = compare(local, netbox_view(backend, type_id))
    items = {i.key: i for i in sync_items(comparison)}
    assert items["field:owner"].choices == (NETBOX, SKIP)
    assert items["rear-ports:R9"].choices == (NETBOX, SKIP)
    assert items["interfaces:eth2"].kind == "local-only"
    decisions = overwrite_decisions(items.values())
    assert decisions["field:owner"] == SKIP and decisions["rear-ports:R9"] == SKIP

    plan = build_sync_plan(local, comparison, decisions)
    assert set(plan.fields) == {"weight", "weight_unit"}
    assert plan.creates == (("interfaces", "eth2"),)
    assert plan.updates == (("interfaces", "eth1", ("mgmt_only",)),)
    assert plan.mapping_fronts == ("F1",)
    report = execute_sync(plan, backend, types=netbox_view(backend, type_id))

    assert report.outcome.status == "success", report.outcome.message
    assert report.outcome.verification == "verified", report.outcome.verification_detail
    assert report.local_doc is None  # the file does not change
    after = compare(local, netbox_view(backend, type_id))
    assert {i.key for i in sync_items(after)} == {"field:owner", "rear-ports:R9"}
    eth2 = next(r for _k, (p, r) in backend.rows.items() if r.get("name") == "eth2")
    assert eth2["parent"]["name"] == "eth0"
    assert "R9" in [r.get("name") for _p, r in backend.rows.values()]


def test_per_value_choices_update_the_file_and_netbox():
    backend, type_id = imported()
    backend.seed(
        "/api/dcim/rear-port-templates/",
        900,
        name="R9",
        type="8p8c",
        positions=1,
        device_type={"id": int(type_id)},
    )
    local = changed_local()
    comparison = compare(local, netbox_view(backend, type_id))
    decisions = {i.key: SKIP for i in sync_items(comparison)}
    decisions["field:weight"] = NETBOX  # NetBox has no weight: drop it locally
    decisions["field:owner"] = NETBOX
    decisions["rear-ports:R9"] = NETBOX
    decisions["interfaces:eth1"] = LOCAL
    plan = build_sync_plan(local, comparison, decisions)
    assert plan.local_changed and plan.netbox_steps == 1
    assert "weight" not in plan.local_doc
    assert plan.local_doc["owner"] == "Network team"
    assert plan.local_doc["rear-ports"][-1]["name"] == "R9"

    report = execute_sync(plan, backend)
    assert report.outcome.verification == "verified"
    assert report.local_doc is plan.local_doc


def test_drift_dry_run_and_missing_references_stop_before_writing():
    backend, type_id = imported()
    local = changed_local()
    comparison = compare(local, netbox_view(backend, type_id))
    plan = build_sync_plan(
        local, comparison, overwrite_decisions(sync_items(comparison))
    )
    writes = len(backend.writes)

    dry = execute_sync(plan, backend, dry_run=True)
    assert dry.outcome.status == "skipped" and "Dry-run" in dry.outcome.message
    assert len(backend.writes) == writes

    tagged = copy.deepcopy(local)
    tagged["tags"] = ["nope"]
    comparison2 = compare(tagged, netbox_view(backend, type_id))
    plan2 = build_sync_plan(
        tagged, comparison2, overwrite_decisions(sync_items(comparison2))
    )
    report = execute_sync(plan2, backend)
    assert report.outcome.status == "skipped" and "tag 'nope'" in report.outcome.message

    backend.update_object(f"/api/dcim/device-types/{type_id}/", {"description": "x"})
    drift = execute_sync(plan, backend)
    assert (
        drift.outcome.status == "skipped" and "changed since" in drift.outcome.message
    )
    assert len(backend.writes) == writes + 1  # only the drift change above


def test_interrupted_template_create_is_looked_up():
    backend, type_id = imported()
    local = changed_local()
    comparison = compare(local, netbox_view(backend, type_id))
    plan = build_sync_plan(
        local, comparison, overwrite_decisions(sync_items(comparison))
    )
    backend.fail_create = "eth2"
    report = execute_sync(plan, backend)
    assert report.outcome.status == "success", report.outcome.message


# -- preflight -------------------------------------------------------------------


def racked(backend, type_id, positions, other_at):
    backend.seed("/api/dcim/racks/", 700, name="R1", u_height=4, starting_unit=1)
    for index, position in enumerate(positions):
        backend.seed(
            "/api/dcim/devices/",
            710 + index,
            name=f"box{index}",
            device_type={"id": int(type_id)},
            rack={"id": 700},
            position=position,
            face={"value": "front"},
        )
    backend.seed(
        "/api/dcim/devices/",
        720,
        name="switch",
        device_type={"id": 999},
        rack={"id": 700},
        position=other_at,
        face={"value": "rear"},
    )


def plan_for(backend, type_id, change, devices=1, others=()):
    local = copy.deepcopy(BASE)
    local.update(change)
    types = netbox_view(backend, type_id, devices)
    types = NetBoxTypes(types.types + tuple(others), loaded=True)
    comparison = compare(local, types)
    return build_sync_plan(
        local, comparison, overwrite_decisions(sync_items(comparison))
    ), types


def test_preflight_blocks_rack_overlaps_and_impossible_heights():
    backend, type_id = imported()
    racked(backend, type_id, [1], other_at=2)
    other = NetBoxType(
        "999",
        {"manufacturer": "X", "model": "Switch", "u_height": 1, "is_full_depth": True},
    )
    plan, types = plan_for(backend, type_id, {"u_height": 2}, others=[other])
    findings = preflight(plan, types, backend)
    assert [f.level for f in findings][0] == BLOCKER
    assert "box0 would overlap switch" in findings[0].message
    report = execute_sync(plan, backend, types=types)
    assert report.outcome.status == "skipped" and "Blocked" in report.outcome.message

    plan, types = plan_for(backend, type_id, {"u_height": 0}, others=[other])
    assert "0 U is not possible" in preflight(plan, types, backend)[0].message

    backend2, type2 = imported()
    racked(backend2, type2, [4], other_at=1)
    plan, types = plan_for(backend2, type2, {"u_height": 2})
    assert any(
        "would leave rack" in f.message for f in preflight(plan, types, backend2)
    )


def test_preflight_subdevice_role_conflicts_and_warnings():
    backend, type_id = imported()
    racked(backend, type_id, [1], other_at=3)
    plan, types = plan_for(backend, type_id, {"subdevice_role": "child"})
    assert any(
        "Child devices cannot be mounted" in f.message
        for f in preflight(plan, types, backend)
    )

    twin = NetBoxType(
        "998", {"manufacturer": "Ubiquiti", "model": "Twin", "slug": "ubiquiti-twin"}
    )
    # Same slug as another type: the comparison already matches that type.
    plan, types = plan_for(backend, type_id, {"model": "Twin"}, others=[twin])
    assert any(
        "Another NetBox type is Ubiquiti Twin" in f.message
        for f in preflight(plan, types, backend)
    )

    plan, types = plan_for(
        backend,
        type_id,
        {
            "airflow": "front-to-rear",
            "interfaces": FULL["interfaces"] + [{"name": "eth7", "type": "virtual"}],
        },
        devices=3,
    )
    levels = {f.level: f.message for f in preflight(plan, types, backend)}
    assert set(levels) == {WARNING}
    messages = [f.message for f in preflight(plan, types, backend)]
    assert any("airflow change(s) at once on the 3 device(s)" in m for m in messages)
    assert any("only to devices created later" in m for m in messages)
