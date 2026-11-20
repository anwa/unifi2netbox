"""Restore a NetBox backup into a target NetBox (M15 slices 2 and 3).

One walker plans and executes: with ``dry_run`` it reads the target, matches
and counts but writes nothing, so the check shows exactly what the run will
do.

Order: endpoints are restored in dependency order over the references in
the backup (tags, custom fields and choice sets first). A reference to an
object that is not restored yet is left out of the create when the field is
optional and patched afterwards (for example a device's primary IP, which
points to an IP address that points to the device's interface); a missing
required reference fails that object, never silently.

Matching: target objects are read per endpoint and found by a natural key
(slug; device name and site; parent and name for components and templates;
address and VRF; the A terminations of a cable; ...). Components NetBox
creates from templates when a device is created are found the same way and
updated instead of created twice. An object without a usable key is created
only when the target endpoint is empty, else reported.

Modes:

- ``create``: create missing objects; existing ones stay as they are.
- ``update``: create missing objects and update differing ones with the
  backup's values (also empty ones: a restore restores).
- ``replace``: empty the selected endpoints of the target first (reverse
  order, bulk DELETE), then restore. Users, tokens and permissions are never
  part of a backup and are never deleted.

Writes use bulk create and bulk update in batches; an interrupted batch is
looked up by natural key, never retried. Images are uploaded afterwards.
"""

from __future__ import annotations

import base64
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from unifi2netbox.netbox_backup import Backup, serialize_row
from unifi2netbox.network_execute import NETWORK_ERRORS
from unifi2netbox.write_execute import AMBIGUOUS_CREATE_ERRORS

CREATE = "create"
UPDATE = "update"
REPLACE = "replace"
MODES = (CREATE, UPDATE, REPLACE)
BATCH = 100
FIRST = ("extras/custom-field-choice-sets", "extras/custom-fields", "extras/tags")
# Endpoints restored with their files (multipart), after all other objects.
FILE_ENDPOINTS = ("extras/image-attachments",)
COMPONENTS = (
    "dcim/console-ports",
    "dcim/console-server-ports",
    "dcim/power-ports",
    "dcim/power-outlets",
    "dcim/interfaces",
    "dcim/front-ports",
    "dcim/rear-ports",
    "dcim/device-bays",
    "dcim/module-bays",
    "dcim/inventory-items",
)
KEYS: dict[str, tuple[str, ...]] = {
    **{name: ("device", "name") for name in COMPONENTS},
    "dcim/devices": ("name", "site", "tenant"),
    "dcim/device-types": ("manufacturer", "slug"),
    "dcim/module-types": ("manufacturer", "model"),
    "dcim/modules": ("device", "module_bay"),
    "dcim/locations": ("site", "slug"),
    "dcim/racks": ("site", "location", "name"),
    "dcim/power-panels": ("site", "name"),
    "dcim/power-feeds": ("power_panel", "name"),
    "dcim/virtual-device-contexts": ("device", "name"),
    "dcim/mac-addresses": ("mac_address", "assigned_object_type", "assigned_object_id"),
    "dcim/cables": ("a_terminations", "b_terminations"),
    "ipam/ip-addresses": ("address", "vrf"),
    "ipam/prefixes": ("prefix", "vrf"),
    "ipam/ip-ranges": ("start_address", "end_address", "vrf"),
    "ipam/aggregates": ("prefix",),
    "ipam/asns": ("asn",),
    "ipam/vlans": ("vid", "group", "site"),
    "ipam/vlan-groups": ("slug", "scope_type", "scope_id"),
    "ipam/vrfs": ("name", "rd"),
    "ipam/services": ("parent_object_type", "parent_object_id", "name"),
    "ipam/fhrp-groups": ("protocol", "group_id"),
    "circuits/circuits": ("cid", "provider"),
    "circuits/circuit-terminations": ("circuit", "term_side"),
    "virtualization/virtual-machines": ("name", "cluster"),
    "virtualization/interfaces": ("virtual_machine", "name"),
    "virtualization/virtual-disks": ("virtual_machine", "name"),
    "tenancy/contact-assignments": ("object_type", "object_id", "contact", "role"),
    "extras/image-attachments": ("object_type", "object_id", "name"),
    "wireless/wireless-lans": ("ssid", "group"),
    "wireless/wireless-links": ("interface_a", "interface_b"),
}
TEMPLATE_KEY = ("device_type", "module_type", "name")
# Fields NetBox fills from the parent type when an object is created; an
# empty value in the backup is set again right after the create.
INHERITED = {"dcim/devices": ("airflow", "cooling_method")}


class RestoreCancelled(RuntimeError):
    pass


@dataclass
class EndpointResult:
    endpoint: str
    create: int = 0
    update: int = 0
    equal: int = 0
    unmatched: int = 0
    failed: int = 0
    deleted: int = 0
    removed: int = 0  # made by NetBox from templates during this restore
    changes: list = field(default_factory=list)  # (old id, label, fields)

    @property
    def writes(self) -> int:
        return self.create + self.update + self.deleted + self.removed


@dataclass
class RestoreReport:
    mode: str
    dry_run: bool
    endpoints: dict[str, EndpointResult] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    deferred: int = 0
    files: int = 0
    counts_before: dict[str, int] = field(default_factory=dict)
    verification: str = ""
    verification_detail: str = ""

    def result(self, endpoint: str) -> EndpointResult:
        return self.endpoints.setdefault(endpoint, EndpointResult(endpoint))

    def total(self, name: str) -> int:
        return sum(getattr(r, name) for r in self.endpoints.values())

    def summary(self) -> str:
        parts = [
            f"{self.total('create')} to create"
            if self.dry_run
            else f"{self.total('create')} created",
            f"{self.total('update')} to update"
            if self.dry_run
            else f"{self.total('update')} updated",
            f"{self.total('equal')} equal",
        ]
        if self.total("deleted"):
            parts.insert(0, f"{self.total('deleted')} deleted")
        if self.total("removed"):
            parts.append(
                f"{self.total('removed')} components NetBox made from templates "
                "but the backup does not have removed"
            )
        if self.total("unmatched"):
            parts.append(f"{self.total('unmatched')} not matchable")
        if self.total("failed"):
            parts.append(f"{self.total('failed')} failed")
        return ", ".join(parts) + "."


# -- order -------------------------------------------------------------------------


def references(value) -> Iterable[tuple[str, int]]:
    if isinstance(value, dict):
        if set(value) == {"$ref"}:
            yield value["$ref"][0], int(value["$ref"][1])
            return
        for item in value.values():
            yield from references(item)
    elif isinstance(value, list):
        for item in value:
            yield from references(item)


def restore_order(backup: Backup, selection: Iterable[str] | None = None) -> list[str]:
    """Endpoints in dependency order (required references first)."""
    objects = backup.endpoints
    wanted = [e for e in objects if selection is None or e in set(selection)]
    fields = backup.data.get("fields", {})
    required: dict[str, set[str]] = {e: set() for e in wanted}
    optional: dict[str, set[str]] = {e: set() for e in wanted}
    for endpoint in wanted:
        meta = fields.get(endpoint, {})
        for row in objects[endpoint]:
            for name, value in row.items():
                for target, _id in references(value):
                    if target == endpoint or target not in required:
                        continue
                    if meta.get(name, {}).get("required"):
                        required[endpoint].add(target)
                    else:
                        optional[endpoint].add(target)
        for first in FIRST:
            if first in required and endpoint not in FIRST:
                optional[endpoint].add(first)
    order: list[str] = []
    remaining = list(wanted)
    while remaining:
        placed = set(order)
        ready = [
            e for e in remaining if required[e] <= placed and optional[e] <= placed
        ]
        if ready:
            ready.sort(key=lambda e: (e not in FIRST, wanted.index(e)))
        else:
            # A cycle over optional references (device -> primary IP -> its
            # interface -> device): take the endpoint that waits for the
            # fewest optional references and that others need most; its
            # missing references are patched after the restore.
            ready = [e for e in remaining if required[e] <= placed] or remaining[:1]
            needed_by = {
                e: sum(1 for other in remaining if e in required[other]) for e in ready
            }
            ready.sort(
                key=lambda e: (
                    len(optional[e] - placed),
                    -needed_by[e],
                    wanted.index(e),
                )
            )
        order.append(ready[0])
        remaining.remove(ready[0])
    return order


def _rows_parents_first(rows: list[dict]) -> list[dict]:
    """Rows of one endpoint with self-referenced parents before children."""
    ids = {row.get("id") for row in rows}
    placed: set = set()
    result: list[dict] = []
    pending = list(rows)
    while pending:
        progress = False
        for row in list(pending):
            parents = {
                i
                for name, value in row.items()
                if name != "id"
                for _t, i in references(value)
                if i in ids and i != row.get("id")
            }
            if parents <= placed:
                result.append(row)
                placed.add(row.get("id"))
                pending.remove(row)
                progress = True
        if not progress:
            result += pending
            break
    return result


# -- keys and values ---------------------------------------------------------------


def natural_key(endpoint: str, values: Mapping, fields: Mapping) -> tuple | None:
    names = KEYS.get(endpoint)
    if names is None and endpoint.endswith("-templates"):
        names = TEMPLATE_KEY
    if names is None:
        if "slug" in fields:
            names = ("slug",)
        elif "name" in fields:
            names = ("name",)
        else:
            return None
    key = tuple(_frozen(values.get(name)) for name in names)
    if all(part in (None, "", ()) for part in key):
        return None
    if names[0] in ("name", "slug") and key[0] in (None, ""):
        return None  # unnamed objects (for example a device without a name)
    return key


def _frozen(value):
    if isinstance(value, list):
        return tuple(sorted((_frozen(v) for v in value), key=repr))
    if isinstance(value, dict):
        return tuple(sorted((k, _frozen(v)) for k, v in value.items()))
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _resolve(value, ids: Mapping[tuple[str, int], int]):
    """Replace refs by target IDs; (value, unresolved refs)."""
    missing: list[tuple[str, int]] = []

    def walk(item):
        if isinstance(item, dict):
            if set(item) == {"$ref"}:
                target = (item["$ref"][0], int(item["$ref"][1]))
                if target in ids:
                    return ids[target]
                missing.append(target)
                return None
            return {k: walk(v) for k, v in item.items()}
        if isinstance(item, list):
            return [walk(v) for v in item]
        return item

    return walk(value), missing


def _target_values(row: Mapping) -> dict:
    """A target row (already serialized) with refs replaced by plain IDs."""
    return {k: _plain_ids(v) for k, v in row.items()}


def _plain_ids(value):
    if isinstance(value, dict):
        if set(value) == {"$ref"}:
            return int(value["$ref"][1])
        return {k: _plain_ids(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain_ids(v) for v in value]
    return value


def _same(a, b) -> bool:
    return _frozen(_normal(a)) == _frozen(_normal(b))


def _normal(value):
    if value in (None, "", [], {}):
        return None
    if isinstance(value, list):
        return [_normal(v) for v in value]
    if isinstance(value, dict):
        return {k: _normal(v) for k, v in value.items() if _normal(v) is not None}
    if isinstance(value, str):
        return value.strip()
    return value


# -- the walker --------------------------------------------------------------------


@dataclass
class _Target:
    rows: list[dict]
    by_key: dict
    by_id: dict
    files: set = field(default_factory=set)  # (id, file field) present


def restore(
    backup: Backup,
    backend,
    *,
    mode: str = CREATE,
    selection: Iterable[str] | None = None,
    skip: Iterable[tuple[str, int]] = (),
    dry_run: bool = True,
    progress: Callable[[str, int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    expected_counts: Mapping[str, int] | None = None,
) -> RestoreReport:
    """Plan (dry run) or run a restore of ``backup`` into ``backend``."""
    if mode not in MODES:
        raise ValueError(f"Unknown restore mode {mode}.")
    report = RestoreReport(mode, dry_run)
    order = restore_order(backup, selection)
    skipped = set(skip)
    fields = backup.data.get("fields", {})
    ids: dict[tuple[str, int], int] = {}
    placeholder = [0]
    created: dict[str, set[int]] = {}  # target IDs created by this restore
    has_file: set[tuple[str, int, str]] = set()  # target files already there
    deferred: list[tuple[str, int, str, object]] = []

    def check_cancel():
        if cancelled is not None and cancelled():
            raise RestoreCancelled("The restore was cancelled.")

    try:
        report.counts_before = {e: backend.count(f"/api/{e}/") for e in order}
    except NETWORK_ERRORS as error:
        report.errors.append(f"Cannot read the target: {error}")
        return report
    if expected_counts is not None and not dry_run:
        changed = [
            e for e in order if expected_counts.get(e) != report.counts_before[e]
        ]
        if changed:
            report.errors.append(
                "The target changed since the check ("
                + ", ".join(changed[:5])
                + "); check again."
            )
            return report
    if mode == REPLACE:
        for endpoint in reversed(order):
            check_cancel()
            _empty(endpoint, backend, report, dry_run)
    for index, endpoint in enumerate(order):
        check_cancel()
        if progress is not None:
            progress(endpoint, index, len(order))
        meta = fields.get(endpoint, {})
        result = report.result(endpoint)
        try:
            target = _read_target(endpoint, backend, meta, report, mode, dry_run)
        except NETWORK_ERRORS as error:
            report.errors.append(f"{endpoint}: cannot read the target ({error})")
            result.failed += len(backup.endpoints[endpoint])
            continue
        has_file |= {(endpoint, i, f) for i, f in target.files}
        matched: set[int] = set()
        creates: list[tuple[dict, dict]] = []
        for row in _rows_parents_first(backup.endpoints[endpoint]):
            old = (endpoint, int(row["id"]))
            if old in skipped:
                continue
            values = {k: v for k, v in row.items() if k != "id"}
            payload, missing = _resolve(values, ids)
            unresolved = False
            later: list[tuple[str, object]] = []
            for name, value in values.items():
                refs = list(references(value))
                if not refs or not any(r in missing for r in refs):
                    continue
                if meta.get(name, {}).get("required"):
                    unresolved = True
                else:
                    payload.pop(name, None)
                    later.append((name, value))
            if unresolved:
                result.failed += 1
                report.errors.append(
                    f"{endpoint} {row['id']}: a required reference is not restored."
                )
                continue
            key = natural_key(endpoint, payload, meta)
            match = target.by_key.get(key) if key is not None else None
            if match is None or mode != CREATE:
                # patched after the restore; for an existing object only when
                # its value differs (checked then)
                existing = match["values"] if match else None
                deferred += [
                    (endpoint, int(row["id"]), n, v, existing) for n, v in later
                ]
            if match is None and key is None and target.rows and mode != REPLACE:
                result.unmatched += 1
                continue
            if match is None:
                creates.append((row, payload))
                if dry_run:  # children in the same run can refer to it
                    placeholder[0] -= 1
                    ids[old] = placeholder[0]
                continue
            ids[old] = match["id"]
            matched.add(match["id"])
            # A component NetBox made from a template for a device this
            # restore created carries template values: it gets the backup's.
            fresh = endpoint in COMPONENTS and match["values"].get("device") in (
                created.get("dcim/devices", set())
            )
            if mode == CREATE and not fresh:
                result.equal += 1
                continue
            changed = [
                name
                for name, value in payload.items()
                if not _same(value, match["values"].get(name))
            ]
            if not changed:
                result.equal += 1
                continue
            result.update += 1
            result.changes.append((row["id"], _label(row), changed))
            if not dry_run:
                try:
                    backend.bulk_update(
                        f"/api/{endpoint}/",
                        [{"id": match["id"], **{n: payload[n] for n in changed}}],
                    )
                except NETWORK_ERRORS as error:
                    result.update -= 1
                    result.failed += 1
                    report.errors.append(f"{endpoint} {row['id']}: {error}")
        if endpoint in FILE_ENDPOINTS:
            _create_files(endpoint, creates, backup, backend, ids, report, dry_run)
            continue
        _create(
            endpoint, creates, backend, ids, report, dry_run, placeholder, meta, created
        )
        if endpoint in COMPONENTS and not dry_run:
            _remove_template_extras(endpoint, target, matched, created, backend, report)
    if not dry_run:
        _patch_deferred(deferred, backend, ids, report)
        _upload_files(backup, backend, ids, report, created, has_file)
        _verify(order, backup, backend, report)
    else:
        report.deferred = sum(
            1
            for _e, _o, name, value, existing in deferred
            if existing is None
            or not _same(_resolve(value, ids)[0], existing.get(name))
        )
    return report


def _label(row: Mapping) -> str:
    for name in ("name", "slug", "address", "prefix", "cid", "model", "ssid"):
        if row.get(name):
            return str(row[name])
    return f"#{row.get('id')}"


def _read_target(endpoint, backend, meta, report, mode, dry_run) -> _Target:
    if mode == REPLACE and dry_run:
        rows = []  # emptied before the restore
    else:
        rows = backend.list_objects(f"/api/{endpoint}/")
    by_key, by_id, files = {}, {}, set()
    for row in rows:
        item, _secrets, wanted = serialize_row(endpoint, row, meta)
        files |= {(int(row["id"]), name) for name, _url in wanted}
        values = _target_values({k: v for k, v in item.items() if k != "id"})
        entry = {"id": int(row["id"]), "values": values}
        by_id[int(row["id"])] = entry
        key = natural_key(endpoint, values, meta)
        if key is not None:
            by_key.setdefault(key, entry)
    return _Target(rows, by_key, by_id, files)


def _create_payload(payload: Mapping) -> dict:
    """Empty values are left out of a create, so NetBox sets its defaults
    (some fields reject an empty string or null)."""
    return {k: v for k, v in payload.items() if v not in (None, "")}


def _create(
    endpoint, creates, backend, ids, report, dry_run, placeholder, meta, created
):
    result = report.result(endpoint)
    for start in range(0, len(creates), BATCH):
        batch = creates[start : start + BATCH]
        if dry_run:
            result.create += len(batch)
            continue
        try:
            new_ids = backend.bulk_create(
                f"/api/{endpoint}/", [_create_payload(p) for _r, p in batch]
            )
        except AMBIGUOUS_CREATE_ERRORS as error:
            new_ids = _look_up(endpoint, batch, backend, meta, report, error)
        except NETWORK_ERRORS as error:
            result.failed += len(batch)
            report.errors.append(
                f"{endpoint}: {len(batch)} objects not created: {error}"
            )
            continue
        clear = []
        for (row, payload), new_id in zip(batch, new_ids, strict=False):
            if new_id is None:
                result.failed += 1
                continue
            ids[(endpoint, int(row["id"]))] = int(new_id)
            created.setdefault(endpoint, set()).add(int(new_id))
            result.create += 1
            empty = {
                name: None
                for name in INHERITED.get(endpoint, ())
                if name in payload and payload[name] in (None, "")
            }
            if empty:
                clear.append({"id": int(new_id), **empty})
        if clear:
            try:
                backend.bulk_update(f"/api/{endpoint}/", clear)
            except NETWORK_ERRORS as error:
                report.errors.append(
                    f"{endpoint}: inherited values not cleared: {error}"
                )


def _remove_template_extras(endpoint, target, matched, created, backend, report):
    """Delete components NetBox made from templates for devices created by
    this restore that the backup does not have (they were removed in the
    source). Components of other devices are never touched."""
    new_devices = created.get("dcim/devices", set())
    if not new_devices:
        return
    extras = []
    for row in target.rows:
        device = row.get("device")
        device_id = device.get("id") if isinstance(device, Mapping) else device
        if int(row["id"]) not in matched and device_id in new_devices:
            extras.append(int(row["id"]))
    if not extras:
        return
    result = report.result(endpoint)
    for start in range(0, len(extras), BATCH):
        batch = extras[start : start + BATCH]
        try:
            backend.bulk_delete(f"/api/{endpoint}/", batch)
            result.removed += len(batch)
        except NETWORK_ERRORS as error:
            report.errors.append(f"{endpoint}: {len(batch)} not removed: {error}")


def _look_up(endpoint, batch, backend, meta, report, error):
    """After an interrupted batch: find what NetBox created, never retry."""
    report.errors.append(f"{endpoint}: a create was interrupted ({error}); looked up.")
    try:
        target = _read_target(endpoint, backend, meta, report, CREATE, False)
    except NETWORK_ERRORS:
        return [None] * len(batch)
    found = []
    for _row, payload in batch:
        key = natural_key(endpoint, payload, meta)
        match = target.by_key.get(key) if key is not None else None
        found.append(match["id"] if match else None)
    return found


def _empty(endpoint, backend, report, dry_run):
    result = report.result(endpoint)
    try:
        rows = backend.list_objects(f"/api/{endpoint}/")
    except NETWORK_ERRORS as error:
        report.errors.append(f"{endpoint}: cannot read for deletion ({error})")
        return
    ids = [int(r["id"]) for r in rows]
    if dry_run:
        result.deleted += len(ids)
        return
    for start in range(0, len(ids), BATCH):
        batch = ids[start : start + BATCH]
        try:
            backend.bulk_delete(f"/api/{endpoint}/", batch)
            result.deleted += len(batch)
        except NETWORK_ERRORS as error:
            report.errors.append(f"{endpoint}: {len(batch)} not deleted: {error}")


def _patch_deferred(deferred, backend, ids, report):
    by_endpoint: dict[str, list[dict]] = {}
    for endpoint, old_id, name, value, existing in deferred:
        new_id = ids.get((endpoint, old_id))
        payload, missing = _resolve(value, ids)
        if new_id is None or missing:
            report.errors.append(f"{endpoint} {old_id}: {name} could not be set.")
            continue
        if existing is not None and _same(payload, existing.get(name)):
            continue  # already set in the target
        by_endpoint.setdefault(endpoint, []).append({"id": new_id, name: payload})
    for endpoint, updates in by_endpoint.items():
        for start in range(0, len(updates), BATCH):
            try:
                backend.bulk_update(f"/api/{endpoint}/", updates[start : start + BATCH])
                report.deferred += len(updates[start : start + BATCH])
            except NETWORK_ERRORS as error:
                report.errors.append(f"{endpoint}: references not set: {error}")


def _decode(entry: Mapping) -> Path:
    folder = Path(tempfile.mkdtemp(prefix="u2n-restore-"))
    path = folder / (str(entry.get("name") or "file") or "file")
    path.write_bytes(base64.b64decode(entry["data"]))
    return path


def _upload_files(backup, backend, ids, report, created, has_file):
    """Images for created objects and for existing ones that lack them."""
    for entry in backup.data.get("files", ()):
        endpoint = entry.get("endpoint")
        if endpoint in FILE_ENDPOINTS:
            continue
        new_id = ids.get((endpoint, int(entry.get("id"))))
        if new_id is None:
            continue
        exists = (endpoint, new_id, entry["field"]) in has_file
        if exists and new_id not in created.get(endpoint, set()):
            continue
        try:
            backend.upload_files(
                f"/api/{endpoint}/{new_id}/", {entry["field"]: _decode(entry)}
            )
            report.files += 1
        except (*NETWORK_ERRORS, OSError) as error:
            report.errors.append(
                f"{endpoint} {entry.get('id')}: file not uploaded: {error}"
            )


def _create_files(endpoint, creates, backup, backend, ids, report, dry_run):
    """Image attachments are created together with their image (multipart)."""
    result = report.result(endpoint)
    files = {
        int(e["id"]): e
        for e in backup.data.get("files", ())
        if e.get("endpoint") == endpoint
    }
    for row, payload in creates:
        entry = files.get(int(row["id"]))
        if entry is None:
            result.failed += 1
            report.errors.append(
                f"{endpoint} {row['id']}: the image is not in the backup."
            )
            continue
        if dry_run:
            result.create += 1
            continue
        try:
            new_id = backend.create_with_files(
                f"/api/{endpoint}/", payload, {"image": _decode(entry)}
            )
        except (*NETWORK_ERRORS, OSError) as error:
            result.failed += 1
            report.errors.append(f"{endpoint} {row['id']}: {error}")
            continue
        ids[(endpoint, int(row["id"]))] = int(new_id)
        result.create += 1
        report.files += 1


def _verify(order, backup, backend, report):
    short = []
    try:
        for endpoint in order:
            count = backend.count(f"/api/{endpoint}/")
            expected = len(backup.endpoints[endpoint])
            if count < expected:
                short.append(f"{endpoint} ({count} of {expected})")
    except NETWORK_ERRORS as error:
        report.verification = "unverified"
        report.verification_detail = f"Read-back failed: {error}"
        return
    if short:
        report.verification = "mismatch"
        report.verification_detail = "Fewer objects than in the backup: " + ", ".join(
            short[:10]
        )
    else:
        report.verification = "verified"
        report.verification_detail = (
            "Every restored endpoint has at least the backup's objects."
        )
