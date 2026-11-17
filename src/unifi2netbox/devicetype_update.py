"""Sync a local device type definition with its NetBox type (M14 slice 5).

``sync_items`` lists every difference of a ``TypeComparison``: device type
fields and template rows (by name; port mappings by front port and
position). Each item is decided:

- ``local``: NetBox gets the local value (a field is patched, a template
  row created or patched, a front port's mappings replaced).
- ``netbox``: the local file gets the NetBox value (a NetBox-only row is
  added to it, a local-only row is removed from it).
- ``skip``: nothing changes.

A value missing in the file is never written as "clear" to NetBox, and a
template that exists only in NetBox is never deleted. **Overwrite NetBox**
decides ``local`` wherever that is possible.

``execute_sync`` re-reads the type and its templates first and stops when
NetBox changed since the comparison (drift), runs the preflight blockers,
resolves references by name (stopping when one is missing), then writes:
type fields, new templates in dependency order, changed templates, port
mappings, interface parents and bridges, images. Interrupted creates are
looked up by name, never retried. NetBox is read back and every item
decided ``local`` must be gone from the new comparison (*verified*), else
*mismatch*. Dry runs do all reads and checks and write nothing.
"""

from __future__ import annotations

import copy
import sqlite3
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ruamel.yaml.comments import CommentedMap

from unifi2netbox.devicetype_import import (
    DEVICE_TYPES,
    IMAGE_FIELDS,
    MANUFACTURERS,
    ORDER,
    TEMPLATES,
    _front_mappings,
    _lookup,
    _parents_first,
    _plain,
    _template_references,
    _type_payload,
    resolve_references,
    template_fields,
)
from unifi2netbox.journal_store import (
    JournalStore,
    JournalStoreError,
    StoredOutcome,
    StoredRun,
)
from unifi2netbox.netbox_types import (
    COMPONENT_ORDER,
    LOCAL_ONLY,
    NETBOX_ONLY,
    NetBoxType,
    NetBoxTypes,
    TypeComparison,
    compare,
    netbox_definition,
    row_key,
)
from unifi2netbox.network_execute import NETWORK_ERRORS, NetworkOutcome
from unifi2netbox.write_execute import AMBIGUOUS_CREATE_ERRORS

LOCAL = "local"
NETBOX = "netbox"
SKIP = "skip"
FIELD = "field"
OPERATION = "sync_device_type"
CHOICE_LABELS = {
    LOCAL: "Local",
    NETBOX: "NetBox",
    SKIP: "Skip",
}


@dataclass(frozen=True)
class SyncItem:
    key: str
    section: str | None  # None for device type fields
    name: str  # field name or template row key
    kind: str  # field, differs, local-only, netbox-only
    local: object = None
    netbox: object = None
    columns: tuple[str, ...] = ()

    @property
    def choices(self) -> tuple[str, ...]:
        if self.kind == NETBOX_ONLY:
            return (NETBOX, SKIP)  # never deleted in NetBox
        if self.kind == FIELD and self.local in (None, "", [], {}):
            return (NETBOX, SKIP)  # never "clear" in NetBox
        return (LOCAL, NETBOX, SKIP)

    @property
    def title(self) -> str:
        if self.section is None:
            return self.name
        return f"{self.section}: {self.name}"

    @property
    def detail(self) -> str:
        if self.kind == LOCAL_ONLY:
            return (
                "Only in the file. Local: create it in NetBox. "
                "NetBox: remove it from the file."
            )
        if self.kind == NETBOX_ONLY:
            return "Only in NetBox (never deleted). NetBox: add it to the file."
        if self.columns:
            return f"Differs in {', '.join(self.columns)}."
        return ""


def sync_items(comparison: TypeComparison) -> list[SyncItem]:
    items = [
        SyncItem(f"field:{d.name}", None, d.name, FIELD, d.local, d.netbox)
        for d in comparison.fields
    ]
    for section in COMPONENT_ORDER:
        for row in comparison.rows(section):
            items.append(
                SyncItem(
                    f"{section}:{row.key}",
                    section,
                    row.key,
                    row.kind,
                    None,
                    row.netbox_row,
                    tuple(f.name for f in row.fields),
                )
            )
    return items


def overwrite_decisions(items: Iterable[SyncItem]) -> dict[str, str]:
    """Overwrite NetBox: local wherever possible, NetBox-only rows stay."""
    return {i.key: LOCAL if LOCAL in i.choices else SKIP for i in items}


@dataclass(frozen=True)
class SyncPlan:
    type_id: str
    label: str
    netbox_doc: Mapping  # what the comparison saw (drift check)
    local_doc: CommentedMap  # the file after the NetBox decisions
    fields: tuple[str, ...] = ()
    creates: tuple[tuple[str, str], ...] = ()  # (section, row key)
    updates: tuple[tuple[str, str, tuple[str, ...]], ...] = ()
    mapping_fronts: tuple[str, ...] = ()
    images: tuple[tuple[str, str], ...] = ()  # (front_image, path)
    local_keys: tuple[str, ...] = ()  # items decided local (read-back)
    local_changed: bool = False
    device_count: int = 0

    @property
    def netbox_steps(self) -> int:
        return (
            (1 if self.fields else 0)
            + len(self.creates)
            + len(self.updates)
            + len(self.mapping_fronts)
            + len(self.images)
        )

    def describe(self) -> list[str]:
        lines = []
        if self.fields:
            lines.append(f"Update the type: {', '.join(self.fields)}")
        for section, key in self.creates:
            lines.append(f"Create {section}: {key}")
        for section, key, columns in self.updates:
            lines.append(f"Update {section}: {key} ({', '.join(columns)})")
        for front in self.mapping_fronts:
            lines.append(f"Update the port mappings of front port {front}")
        for name, _path in self.images:
            lines.append(f"Upload the {name.replace('_', ' ')}")
        if self.local_changed:
            lines.append("Update the local file with the NetBox values")
        return lines


def build_sync_plan(
    local: Mapping,
    comparison: TypeComparison,
    decisions: Mapping[str, str],
    images: Mapping[str, str] | None = None,
) -> SyncPlan:
    """Turn decisions into NetBox steps and the new local document."""
    if comparison.netbox is None:
        raise ValueError("The definition is not in NetBox; import it instead.")
    images = images or {}
    doc = copy.deepcopy(local)
    fields, creates, updates, fronts, uploads, local_keys = [], [], [], [], [], []
    local_changed = False
    for item in sync_items(comparison):
        choice = decisions.get(item.key, SKIP)
        if choice not in item.choices or choice == SKIP:
            continue
        if choice == NETBOX:
            local_changed = True
            _take_netbox(doc, item)
            continue
        local_keys.append(item.key)
        if item.section is None:
            if item.name in IMAGE_FIELDS:
                side = item.name.split("_")[0]
                if images.get(side):
                    uploads.append((item.name, str(images[side])))
            else:
                fields.append(item.name)
        elif item.section == "port-mappings":
            front = item.name.rsplit("/", 1)[0]
            if front not in fronts:
                fronts.append(front)
        elif item.kind == LOCAL_ONLY:
            creates.append((item.section, item.name))
        else:
            updates.append((item.section, item.name, item.columns))
    # Mappings of front ports created in this run are sent with the create.
    created_fronts = {key for section, key in creates if section == "front-ports"}
    fronts = [f for f in fronts if f not in created_fronts]
    return SyncPlan(
        comparison.netbox.id,
        f"{local.get('manufacturer') or ''} {local.get('model') or ''}".strip(),
        comparison.netbox.doc,
        doc,
        tuple(fields),
        tuple(creates),
        tuple(updates),
        tuple(fronts),
        tuple(uploads),
        tuple(local_keys),
        local_changed,
        comparison.netbox.device_count,
    )


def _take_netbox(doc: CommentedMap, item: SyncItem) -> None:
    if item.section is None:
        if item.netbox in (None, "", [], {}):
            doc.pop(item.name, None)
        else:
            doc[item.name] = copy.deepcopy(item.netbox)
        return
    rows = list(doc.get(item.section) or ())
    index = next(
        (
            i
            for i, row in enumerate(rows)
            if isinstance(row, Mapping) and row_key(item.section, row) == item.name
        ),
        None,
    )
    if item.kind == LOCAL_ONLY:
        if index is not None:
            del rows[index]
    elif item.kind == NETBOX_ONLY:
        rows.append(CommentedMap(item.netbox or {}))
    elif index is not None:
        rows[index] = CommentedMap(item.netbox or {})
    if rows:
        doc[item.section] = rows
    else:
        doc.pop(item.section, None)


# -- execution -------------------------------------------------------------------


@dataclass(frozen=True)
class SyncReport:
    outcome: NetworkOutcome
    local_doc: CommentedMap | None = None  # to save when NetBox choices exist
    findings: tuple = ()


def read_type(backend, type_id: str):
    """The type as a definition plus template IDs by section and name."""
    row = backend.read_object(f"{DEVICE_TYPES}{type_id}/")
    if row is None:
        return None, {}
    templates = {
        section: backend.list_objects(endpoint, device_type_id=type_id)
        for section, endpoint in TEMPLATES.items()
    }
    ids = {
        section: {str(r.get("name") or ""): str(r.get("id")) for r in rows}
        for section, rows in templates.items()
    }
    return netbox_definition(row, templates), ids


def execute_sync(
    plan: SyncPlan,
    backend,
    *,
    dry_run: bool = False,
    types: NetBoxTypes | None = None,
) -> SyncReport:
    from unifi2netbox.type_preflight import BLOCKER, preflight

    def outcome(status, message, verification="", detail=""):
        return NetworkOutcome(
            f"devicetype-sync:{plan.type_id}",
            OPERATION,
            plan.label,
            status,
            message,
            plan.type_id,
            verification,
            detail,
        )

    try:
        current, ids = read_type(backend, plan.type_id)
    except NETWORK_ERRORS as error:
        return SyncReport(outcome("failed", f"NetBox read failed: {error}"))
    if current is None:
        return SyncReport(outcome("skipped", "The type is no longer in NetBox."))
    before = compare(plan.netbox_doc, _single(plan.type_id, current))
    if before.status != "same":
        return SyncReport(
            outcome(
                "skipped",
                "NetBox changed since the comparison; reload from NetBox and "
                "review again.",
            )
        )
    try:
        findings = preflight(plan, types or NetBoxTypes(), backend)
    except NETWORK_ERRORS as error:
        return SyncReport(outcome("failed", f"NetBox check failed: {error}"))
    blockers = [f for f in findings if f.level == BLOCKER]
    if blockers:
        return SyncReport(
            outcome("skipped", f"Blocked: {blockers[0].message}"), findings=findings
        )
    needed = _needed(plan)
    try:
        refs, missing = resolve_references(needed, backend)
        manufacturer = (
            _lookup(backend, MANUFACTURERS, str(needed.get("manufacturer") or ""))
            if "manufacturer" in plan.fields
            else None
        )
    except NETWORK_ERRORS as error:
        return SyncReport(outcome("failed", f"NetBox lookup failed: {error}"))
    if "manufacturer" in plan.fields and manufacturer is None:
        missing.insert(0, f"manufacturer '{needed.get('manufacturer')}'")
    if missing:
        return SyncReport(
            outcome(
                "skipped",
                f"Not in NetBox: {', '.join(missing)}. Choose or create them first.",
            ),
            findings=findings,
        )
    local_doc = plan.local_doc if plan.local_changed else None
    if dry_run:
        return SyncReport(
            outcome(
                "skipped",
                f"Dry-run mode: {plan.netbox_steps} NetBox step(s) checked, "
                "nothing written.",
            ),
            None,
            findings,
        )
    if not plan.netbox_steps:
        return SyncReport(
            outcome("success", "Only the local file changes.", "verified"),
            local_doc,
            findings,
        )
    failures = _write(plan, backend, ids, refs, manufacturer)
    try:
        after, _ids = read_type(backend, plan.type_id)
    except NETWORK_ERRORS as error:
        after = None
        detail = f"Read-back failed: {error}"
    verification, detail = "unverified", "The type was not found after the write."
    if after is not None:
        remaining = {
            item.key
            for item in sync_items(
                compare(plan.local_doc, _single(plan.type_id, after))
            )
        } & set(plan.local_keys)
        if remaining:
            verification = "mismatch"
            detail = f"NetBox still differs in {', '.join(sorted(remaining))}."
        else:
            verification, detail = "verified", "NetBox matches the chosen values."
    steps = plan.netbox_steps
    if failures:
        return SyncReport(
            outcome(
                "failed",
                f"{len(failures)} of {steps} step(s) failed: {failures[0]}",
                verification,
                detail,
            ),
            local_doc,
            findings,
        )
    return SyncReport(
        outcome("success", f"Synced {steps} step(s) to NetBox.", verification, detail),
        local_doc,
        findings,
    )


def _single(type_id: str, doc) -> NetBoxTypes:
    return NetBoxTypes((NetBoxType(type_id, doc),), loaded=True)


def _needed(plan: SyncPlan) -> CommentedMap:
    """The parts of the document that NetBox steps use (for references)."""
    doc = plan.local_doc
    needed = CommentedMap()
    for name in plan.fields:
        if name in doc:
            needed[name] = doc[name]
    if "manufacturer" in doc:
        needed.setdefault("manufacturer", doc["manufacturer"])
    rows = {key for section, key in plan.creates if section == "inventory-items"}
    rows |= {key for section, key, _c in plan.updates if section == "inventory-items"}
    items = [
        r
        for r in doc.get("inventory-items") or ()
        if isinstance(r, Mapping) and str(r.get("name")) in rows
    ]
    if items:
        needed["inventory-items"] = items
    return needed


def _write(plan, backend, ids, refs, manufacturer) -> list[str]:
    failures: list[str] = []
    doc = plan.local_doc
    type_id = plan.type_id
    if plan.fields:
        payload = _type_payload(doc, manufacturer or 0, refs)
        wanted = set(plan.fields)
        payload = {k: v for k, v in payload.items() if k in wanted}
        for name in plan.fields:  # fields the payload builder leaves out
            if name not in payload and name in doc and name not in IMAGE_FIELDS:
                payload[name] = _plain(doc[name])
        try:
            backend.update_object(f"{DEVICE_TYPES}{type_id}/", payload)
        except NETWORK_ERRORS as error:
            failures.append(f"type fields: {error}")
    rows = {
        (section, row_key(section, r)): r
        for section in ORDER
        for r in doc.get(section) or ()
        if isinstance(r, Mapping)
    }
    created_interfaces = []
    for section in ORDER:
        items = [rows[(s, k)] for s, k in plan.creates if s == section]
        if section == "inventory-items":
            items = _parents_first(items)
        for item in items:
            name = str(item.get("name") or "")
            payload = _payload(section, item, doc, ids, refs, type_id)
            if isinstance(payload, str):
                failures.append(f"{name}: {payload}")
                continue
            created = _create(backend, section, payload, type_id, name)
            if isinstance(created, str) and created.startswith("!"):
                failures.append(f"{name}: {created[1:]}")
                continue
            ids.setdefault(section, {})[name] = created
            if section == "interfaces":
                created_interfaces.append(item)
    for section, key, columns in plan.updates:
        item = rows.get((section, key))
        object_id = ids.get(section, {}).get(key)
        if item is None or object_id is None:
            failures.append(f"{key}: not found in NetBox.")
            continue
        payload = _payload(section, item, doc, ids, refs, type_id)
        if isinstance(payload, str):
            failures.append(f"{key}: {payload}")
            continue
        patch = {}
        for column in columns:
            if column == "component_name":
                for name in ("component_type", "component_id"):
                    if name in payload:
                        patch[name] = payload[name]
            elif section == "interfaces" and column in ("parent", "bridge"):
                value = item.get(column)
                patch[column] = (
                    int(ids["interfaces"][str(value)])
                    if value and str(value) in ids.get("interfaces", {})
                    else None
                )
            elif column in payload:
                patch[column] = payload[column]
        if not patch:
            continue
        try:
            backend.update_object(f"{TEMPLATES[section]}{object_id}/", patch)
        except NETWORK_ERRORS as error:
            failures.append(f"{key}: {error}")
    for front in plan.mapping_fronts:
        item = rows.get(("front-ports", front))
        object_id = ids.get("front-ports", {}).get(front)
        if item is None or object_id is None:
            failures.append(f"{front}: front port not found.")
            continue
        mappings = _front_mappings(doc, item)
        for mapping in mappings:
            rear = ids.get("rear-ports", {}).get(mapping["rear_port"])
            if rear is None:
                failures.append(f"{front}: unknown rear port {mapping['rear_port']}.")
                break
            mapping["rear_port"] = int(rear)
        else:
            try:
                backend.update_object(
                    f"{TEMPLATES['front-ports']}{object_id}/", {"rear_ports": mappings}
                )
            except NETWORK_ERRORS as error:
                failures.append(f"{front}: {error}")
    for item in created_interfaces:
        patch = {}
        for column in ("parent", "bridge"):
            value = item.get(column)
            if value and str(value) in ids.get("interfaces", {}):
                patch[column] = int(ids["interfaces"][str(value)])
        if patch:
            name = str(item.get("name"))
            try:
                backend.update_object(
                    f"{TEMPLATES['interfaces']}{ids['interfaces'][name]}/", patch
                )
            except NETWORK_ERRORS as error:
                failures.append(f"{name}: {error}")
    if plan.images:
        upload = getattr(backend, "upload_files", None)
        files = {name: Path(path) for name, path in plan.images}
        try:
            if upload is None:
                raise OSError("this backend cannot upload files")
            upload(f"{DEVICE_TYPES}{type_id}/", files)
        except (*NETWORK_ERRORS, OSError) as error:
            failures.append(f"images: {error}")
    return failures


def _payload(section, item, doc, ids, refs, type_id):
    payload: dict[str, object] = {"device_type": int(type_id)}
    for column in template_fields(section):
        value = item.get(column)
        if value not in (None, ""):
            payload[column] = _plain(value)
    problem = _template_references(section, item, doc, ids, refs, payload)
    return problem or payload


def _create(backend, section, payload, type_id, name) -> str:
    endpoint = TEMPLATES[section]
    try:
        return str(backend.create_object(endpoint, payload))
    except AMBIGUOUS_CREATE_ERRORS:
        try:
            found = backend.find_ids(endpoint, device_type_id=type_id, name=name)
        except NETWORK_ERRORS as error:
            return f"!{error}"
        if len(found) != 1:
            return "!interrupted create."
        return str(found[0])
    except NETWORK_ERRORS as error:
        return f"!{error}"


def journal_sync(path: Path, outcomes: Iterable[NetworkOutcome], dry_run: bool):
    """Save a sync run to the write history (best effort)."""
    started = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        JournalStore(path).save(
            StoredRun(
                run_id=str(uuid.uuid4()),
                started_at=started,
                finished_at=datetime.now(UTC).isoformat(timespec="seconds"),
                dry_run=dry_run,
                outcomes=tuple(
                    StoredOutcome(
                        device_key=o.key,
                        label=o.label,
                        operation_type=o.operation,
                        status=o.status,
                        message=o.message,
                        netbox_object_id=o.object_id,
                        verification=o.verification,
                    )
                    for o in outcomes
                ),
            )
        )
    except JournalStoreError, sqlite3.Error, OSError:
        pass


__all__ = [
    "LOCAL",
    "NETBOX",
    "SKIP",
    "SyncItem",
    "SyncPlan",
    "SyncReport",
    "build_sync_plan",
    "execute_sync",
    "journal_sync",
    "overwrite_decisions",
    "sync_items",
]
