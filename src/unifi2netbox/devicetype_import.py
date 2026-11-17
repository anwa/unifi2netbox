"""Import chosen device type definitions into NetBox (M12 slice 6, M13 slice 4).

A create row may use a definition from the local type folder or the
devicetype-library instead of a NetBox device type. Each distinct definition
becomes one selectable plan row:

- ``reuse``: NetBox already has a type with the same manufacturer and model
  or the same part number; its ID is used and nothing is written.
- ``create``: the type, all of its component templates and its local front
  and rear images are created, as a visible write step before device writes
  (after the Custom Field).
- ``blocked``: the manufacturer is missing in NetBox (create it with the
  editor's **New...** first) or the definition is invalid.

Every NetBox device type field is sent; owner, default platform, tags,
inventory item roles and manufacturers are looked up by name (tags by slug)
before anything is written, and a missing one stops that import (dry runs
check them too). Templates are created in dependency order: power ports
before outlets, rear ports before front ports (with the port mappings),
cooling intakes before outflows, inventory items after the components they
refer to and parents before children; interface parents and bridges are set
once all interfaces exist. Images are uploaded after the templates; a failed
upload is reported but does not undo the type.

Execution re-reads NetBox (an existing slug is reused, never duplicated),
looks up interrupted creates by slug or name instead of retrying, reads the
type back and counts its templates. Dry runs perform the checks only.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

from unifi2netbox.devicetypes import (
    COMPONENT_TYPE_SECTIONS,
    SECTION_ENDPOINTS,
    errors,
    netbox_metadata,
    validate,
)
from unifi2netbox.inventory import InventoryDeviceType, InventoryManufacturer
from unifi2netbox.network_execute import NETWORK_ERRORS, IpamBackend, NetworkOutcome
from unifi2netbox.write_execute import AMBIGUOUS_CREATE_ERRORS

CREATE = "create"
REUSE = "reuse"
BLOCKED = "blocked"
OPERATION = "import_device_type"
DEVICE_TYPES = "/api/dcim/device-types/"
MANUFACTURERS = "/api/dcim/manufacturers/"
OWNERS = "/api/users/owners/"
PLATFORMS = "/api/dcim/platforms/"
TAGS = "/api/extras/tags/"
ROLES = "/api/dcim/inventory-item-roles/"
# Creation order: referenced templates first.
ORDER = (
    "console-ports",
    "console-server-ports",
    "power-ports",
    "power-outlets",
    "interfaces",
    "rear-ports",
    "front-ports",
    "module-bays",
    "device-bays",
    "cooling-intakes",
    "cooling-outflows",
    "inventory-items",
)
TEMPLATES = {section: f"/api/{SECTION_ENDPOINTS[section]}/" for section in ORDER}
# Template fields resolved separately (references) or not imported.
_SPECIAL = {
    "device_type",
    "module_type",
    "power_port",
    "parent",
    "bridge",
    "rear_ports",
    "front_ports",
    "cooling_intake",
    "role",
    "manufacturer",
    "component_id",
    "module_bay_types",
}
TYPE_FIELDS = (
    "model",
    "slug",
    "part_number",
    "u_height",
    "exclude_from_utilization",
    "is_full_depth",
    "airflow",
    "cooling_method",
    "weight",
    "weight_unit",
    "subdevice_role",
    "end_of_life",
    "description",
    "comments",
)
IMAGE_FIELDS = ("front_image", "rear_image")
SKIP_PREFIX = "skip:"
PENDING_ID = "pending-import"


def template_fields(section: str) -> tuple[str, ...]:
    """Plain NetBox fields of one template kind (from the bundled metadata)."""
    endpoint = netbox_metadata()["endpoints"].get(SECTION_ENDPOINTS[section], {})
    fields = endpoint.get("fields", endpoint)
    return tuple(name for name in fields if name not in _SPECIAL)


@dataclass(frozen=True)
class TypeImportRow:
    key: str
    choice: str
    label: str
    manufacturer: str
    model: str
    slug: str
    action: str
    device_keys: tuple[str, ...] = ()
    doc: Mapping = field(default_factory=dict, compare=False)
    manufacturer_id: str = ""
    netbox_id: str = ""
    selected: bool = True
    notes: tuple[str, ...] = ()
    images: tuple[tuple[str, str], ...] = ()  # (front_image|rear_image, path)

    @property
    def selectable(self) -> bool:
        return self.action == CREATE

    @property
    def template_count(self) -> int:
        return _count(self.doc)


@dataclass(frozen=True)
class TypeImportPlan:
    rows: tuple[TypeImportRow, ...] = ()

    def selected_rows(self) -> tuple[TypeImportRow, ...]:
        return tuple(row for row in self.rows if row.selected and row.selectable)

    @property
    def operation_count(self) -> int:
        return len(self.selected_rows())

    def row_for_choice(self, choice: str) -> TypeImportRow | None:
        return next((row for row in self.rows if row.choice == choice), None)

    def device_status(self, choice: str) -> tuple[str, str]:
        """(state, message) for a create row using ``choice``.

        States: ``ready`` (imported or reused on apply), ``blocked``.
        """
        row = self.row_for_choice(choice)
        if row is None:
            return BLOCKED, "The chosen device type definition is not loaded."
        if row.action == REUSE:
            return "ready", f"NetBox already has this type (ID {row.netbox_id})."
        if row.action == BLOCKED:
            return BLOCKED, row.notes[0] if row.notes else "Cannot import this type."
        if not row.selected:
            return BLOCKED, "The device type import is not selected."
        return "ready", "The device type is imported into NetBox on apply."


def build_import_plan(
    choices: Mapping[str, str],
    docs: Mapping[str, Mapping],
    labels: Mapping[str, str],
    manufacturers: Iterable[InventoryManufacturer],
    netbox_types: Iterable[InventoryDeviceType],
    deselected: Iterable[str] = (),
    images: Mapping[str, Mapping[str, str]] | None = None,
) -> TypeImportPlan:
    """``choices`` maps device keys to import choices (``local:``/``library:``).

    ``images`` maps a choice to its local image files by side (front, rear).
    """
    by_choice: dict[str, list[str]] = {}
    for device_key, choice in choices.items():
        by_choice.setdefault(choice, []).append(device_key)
    makers = {m.name.strip().lower(): m.source_id for m in manufacturers}
    types = tuple(netbox_types)
    skipped = set(deselected)
    images = images or {}
    rows = []
    for choice, device_keys in sorted(by_choice.items()):
        doc = docs.get(choice)
        label = labels.get(choice, choice.split(":", 1)[-1])
        if doc is None:
            rows.append(
                TypeImportRow(
                    f"devicetype:{choice}",
                    choice,
                    label,
                    "",
                    "",
                    "",
                    BLOCKED,
                    tuple(sorted(device_keys)),
                    notes=("The definition could not be loaded; choose it again.",),
                )
            )
            continue
        rows.append(
            _row(
                choice,
                label,
                doc,
                tuple(sorted(device_keys)),
                makers,
                types,
                skipped,
                images.get(choice, {}),
            )
        )
    return TypeImportPlan(tuple(rows))


def select_import(plan: TypeImportPlan, choice: str, selected: bool) -> TypeImportPlan:
    return replace(
        plan,
        rows=tuple(
            replace(row, selected=selected)
            if row.choice == choice and row.selectable
            else row
            for row in plan.rows
        ),
    )


def _row(
    choice, label, doc, device_keys, makers, types, skipped, images
) -> TypeImportRow:
    manufacturer = str(doc.get("manufacturer") or "").strip()
    model = str(doc.get("model") or "").strip()
    part = str(doc.get("part_number") or "").strip()
    slug = str(doc.get("slug") or "").strip()
    base = dict(
        key=f"devicetype:{choice}",
        choice=choice,
        label=label,
        manufacturer=manufacturer,
        model=model,
        slug=slug,
        device_keys=device_keys,
        doc=doc,
    )
    existing = next(
        (
            t
            for t in types
            if t.manufacturer.strip().lower() == manufacturer.lower()
            and (
                t.model.strip().lower() == model.lower()
                or (part and t.part_number.strip().lower() == part.lower())
            )
        ),
        None,
    )
    if existing is not None:
        return TypeImportRow(
            action=REUSE,
            netbox_id=existing.source_id,
            selected=False,
            notes=(f"NetBox already has {existing.manufacturer} {existing.model}.",),
            **base,
        )
    notes: list[str] = []
    problems = errors(validate(doc))
    if problems:
        notes.append(f"The definition is invalid: {problems[0]}")
    manufacturer_id = makers.get(manufacturer.lower(), "")
    if not manufacturer_id:
        notes.insert(
            0,
            f"Manufacturer '{manufacturer}' is not in NetBox; create it with New... "
            "in the device type editor first.",
        )
    if notes:
        return TypeImportRow(action=BLOCKED, notes=tuple(notes), **base)
    files = tuple(
        (f"{side}_image", str(images[side]))
        for side in ("front", "rear")
        if images.get(side)
    )
    info = [f"Creates the type and {_count(doc)} component templates"]
    if files:
        info.append(f" and uploads {len(files)} image(s)")
    missing = [
        name
        for name in IMAGE_FIELDS
        if doc.get(name) and name not in {key for key, _ in files}
    ]
    extra = []
    if missing:
        extra.append(
            f"No local file for {', '.join(missing)}; upload it in NetBox later."
        )
    if any(item.get("module_bay_types") for item in _items(doc, "module-bays")):
        extra.append("Module bay types are not imported; set them in NetBox.")
    return TypeImportRow(
        action=CREATE,
        manufacturer_id=manufacturer_id,
        selected=choice not in skipped,
        notes=("".join(info) + ".", *extra),
        images=files,
        **base,
    )


def _count(doc: Mapping) -> int:
    return sum(len(doc.get(section) or ()) for section in TEMPLATES)


def _items(doc: Mapping, section: str) -> list[Mapping]:
    return [item for item in doc.get(section) or () if isinstance(item, Mapping)]


def _plain(value):
    """YAML values (ruamel maps, lists, dates) as JSON-ready values."""
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


# -- execution -------------------------------------------------------------------


def execute_import_plan(
    plan: TypeImportPlan | None,
    backend: IpamBackend,
    *,
    dry_run: bool = False,
) -> tuple[tuple[NetworkOutcome, ...], dict[str, str]]:
    """Outcomes and device-type overrides for every device using the plan.

    Overrides map device keys to the NetBox type ID, to ``PENDING_ID`` in a
    dry run, or to ``skip:<reason>`` when the type is not available.
    """
    if plan is None:
        return (), {}
    outcomes: list[NetworkOutcome] = []
    overrides: dict[str, str] = {}
    for row in plan.rows:
        if row.action == REUSE:
            for key in row.device_keys:
                overrides[key] = row.netbox_id
            continue
        if not row.selectable or not row.selected:
            reason = (
                row.notes[0]
                if row.action == BLOCKED and row.notes
                else ("the device type import was not selected")
            )
            for key in row.device_keys:
                overrides[key] = f"{SKIP_PREFIX}Device type {row.label}: {reason}"
            continue
        outcome, type_id = _import(row, backend, dry_run)
        outcomes.append(outcome)
        for key in row.device_keys:
            if type_id:
                overrides[key] = type_id
            elif (
                dry_run and outcome.status == "skipped" and "Dry-run" in outcome.message
            ):
                overrides[key] = PENDING_ID
            else:
                overrides[key] = (
                    f"{SKIP_PREFIX}Device type {row.label} was not imported "
                    f"({outcome.message})"
                )
    return tuple(outcomes), overrides


@dataclass
class _References:
    owner: int | None = None
    platform: int | None = None
    tags: list[int] = field(default_factory=list)
    roles: dict[str, int] = field(default_factory=dict)
    makers: dict[str, int] = field(default_factory=dict)


def _lookup(backend: IpamBackend, path: str, value: str, keys=("name", "slug")):
    for key in keys:
        found = backend.find_ids(path, **{key: value})
        if found:
            return int(found[0])
    return None


def _references(row: TypeImportRow, backend: IpamBackend):
    """Resolve every NetBox object the definition names; (refs, missing)."""
    doc = row.doc
    refs = _References()
    missing: list[str] = []
    if doc.get("owner"):
        refs.owner = _lookup(backend, OWNERS, str(doc["owner"]), ("name",))
        if refs.owner is None:
            missing.append(f"owner '{doc['owner']}'")
    if doc.get("default_platform"):
        refs.platform = _lookup(backend, PLATFORMS, str(doc["default_platform"]))
        if refs.platform is None:
            missing.append(f"platform '{doc['default_platform']}'")
    for tag in doc.get("tags") or ():
        found = _lookup(backend, TAGS, str(tag), ("slug", "name"))
        if found is None:
            missing.append(f"tag '{tag}'")
        else:
            refs.tags.append(found)
    for item in _items(doc, "inventory-items"):
        role = str(item.get("role") or "")
        if role and role not in refs.roles:
            found = _lookup(backend, ROLES, role)
            if found is None:
                missing.append(f"inventory item role '{role}'")
            else:
                refs.roles[role] = found
        maker = str(item.get("manufacturer") or "")
        if maker and maker not in refs.makers:
            found = _lookup(backend, MANUFACTURERS, maker)
            if found is None:
                missing.append(f"manufacturer '{maker}'")
            else:
                refs.makers[maker] = found
    return refs, list(dict.fromkeys(missing))


def _import(row: TypeImportRow, backend: IpamBackend, dry_run: bool):
    try:
        existing = backend.find_ids(DEVICE_TYPES, slug=row.slug)
    except NETWORK_ERRORS as error:
        return _outcome(row, "failed", f"NetBox lookup failed: {error}"), ""
    if existing:
        return (
            _outcome(
                row,
                "success",
                f"NetBox already has the slug {row.slug}; it is used as is.",
                existing[0],
            ),
            existing[0],
        )
    try:
        makers = backend.find_ids(MANUFACTURERS, name=row.manufacturer)
        refs, missing = _references(row, backend)
    except NETWORK_ERRORS as error:
        return _outcome(row, "failed", f"NetBox lookup failed: {error}"), ""
    if not makers:
        return (
            _outcome(row, "skipped", f"Manufacturer {row.manufacturer} is missing."),
            "",
        )
    if missing:
        return (
            _outcome(
                row,
                "skipped",
                f"Not in NetBox: {', '.join(missing)}. Choose or create them in "
                "the device type editor.",
            ),
            "",
        )
    if dry_run:
        return _outcome(row, "skipped", "Dry-run mode: not imported."), ""
    payload = _type_payload(row.doc, int(makers[0]), refs)
    try:
        type_id = backend.create_object(DEVICE_TYPES, payload)
        message = "Created in NetBox"
    except AMBIGUOUS_CREATE_ERRORS as error:
        try:
            found = backend.find_ids(DEVICE_TYPES, slug=row.slug)
        except NETWORK_ERRORS as lookup_error:
            return (
                _outcome(
                    row,
                    "failed",
                    f"Create was interrupted ({error}) and the lookup failed "
                    f"({lookup_error}). Check NetBox before retrying.",
                ),
                "",
            )
        if len(found) != 1:
            return (
                _outcome(
                    row,
                    "failed",
                    f"Create was interrupted ({error}); NetBox shows no single type. "
                    "Refresh and review before retrying.",
                ),
                "",
            )
        type_id, message = (
            found[0],
            f"Create was interrupted ({error}), but NetBox has it",
        )
    except NETWORK_ERRORS as error:
        return _outcome(row, "failed", str(error)), ""
    created, failures = _templates(row, backend, str(type_id), refs)
    failures += _upload_images(row, backend, str(type_id))
    verification, detail = _verify(row, backend, str(type_id))
    if failures:
        return (
            NetworkOutcome(
                row.key,
                OPERATION,
                row.label,
                "failed",
                f"{message}, but {len(failures)} of {created + len(failures)} "
                f"steps failed: {failures[0]} Check the type in NetBox.",
                str(type_id),
                verification,
                detail,
            ),
            str(type_id),
        )
    uploaded = f" and {len(row.images)} image(s)" if row.images else ""
    return (
        NetworkOutcome(
            row.key,
            OPERATION,
            row.label,
            "success",
            f"{message} with {created} component templates{uploaded}.",
            str(type_id),
            verification,
            detail,
        ),
        str(type_id),
    )


def _type_payload(doc: Mapping, manufacturer_id: int, refs: _References) -> dict:
    payload: dict[str, object] = {"manufacturer": manufacturer_id}
    for name in TYPE_FIELDS:
        value = doc.get(name)
        if value not in (None, ""):
            payload[name] = _plain(value)
    if refs.owner is not None:
        payload["owner"] = refs.owner
    if refs.platform is not None:
        payload["default_platform"] = refs.platform
    if refs.tags:
        payload["tags"] = list(refs.tags)
    custom = doc.get("custom_fields")
    if isinstance(custom, Mapping) and custom:
        payload["custom_fields"] = _plain(custom)
    return payload


def _parents_first(items: list[Mapping]) -> list[Mapping]:
    """Inventory items ordered so that every parent precedes its children."""
    names = {str(item.get("name")) for item in items}
    ordered: list[Mapping] = []
    placed: set[str] = set()
    pending = list(items)
    while pending:
        progress = False
        for item in list(pending):
            parent = str(item.get("parent") or "")
            if not parent or parent in placed or parent not in names:
                ordered.append(item)
                placed.add(str(item.get("name")))
                pending.remove(item)
                progress = True
        if not progress:  # a cycle: the remaining parents fail on create
            ordered += pending
            break
    return ordered


def _front_mappings(doc: Mapping, item: Mapping) -> list[dict]:
    """Port mappings of one front port (``port-mappings`` or the older fields)."""
    name = str(item.get("name") or "")
    mappings = [
        {
            "position": int(m.get("front_port_position") or 1),
            "rear_port": str(m.get("rear_port") or ""),
            "rear_port_position": int(m.get("rear_port_position") or 1),
        }
        for m in _items(doc, "port-mappings")
        if str(m.get("front_port") or "") == name
    ]
    if not mappings and item.get("rear_port"):
        mappings.append(
            {
                "position": 1,
                "rear_port": str(item["rear_port"]),
                "rear_port_position": int(item.get("rear_port_position") or 1),
            }
        )
    return mappings


def _templates(
    row: TypeImportRow, backend: IpamBackend, type_id: str, refs: _References
):
    created = 0
    failures: list[str] = []
    ids: dict[str, dict[str, str]] = {section: {} for section in ORDER}
    doc = row.doc
    for section in ORDER:
        endpoint = TEMPLATES[section]
        items = _items(doc, section)
        if section == "inventory-items":
            items = _parents_first(items)
        fields = template_fields(section)
        for item in items:
            name = str(item.get("name") or "")
            payload: dict[str, object] = {"device_type": int(type_id)}
            for column in fields:
                value = item.get(column)
                if value not in (None, ""):
                    payload[column] = _plain(value)
            problem = _template_references(section, item, doc, ids, refs, payload)
            if problem:
                failures.append(f"{name}: {problem}")
                continue
            try:
                template_id = backend.create_object(endpoint, payload)
            except AMBIGUOUS_CREATE_ERRORS:
                try:
                    found = backend.find_ids(
                        endpoint, device_type_id=type_id, name=name
                    )
                except NETWORK_ERRORS as error:
                    failures.append(f"{name}: {error}")
                    continue
                if len(found) != 1:
                    failures.append(f"{name}: interrupted create.")
                    continue
                template_id = found[0]
            except NETWORK_ERRORS as error:
                failures.append(f"{name}: {error}")
                continue
            created += 1
            ids[section][name] = str(template_id)
    failures += _interface_links(doc, backend, ids["interfaces"])
    return created, failures


def _template_references(section, item, doc, ids, refs, payload) -> str:
    """Add reference IDs to ``payload``; a message when one cannot resolve."""

    def resolve(target: str, value) -> int | None:
        found = ids[target].get(str(value))
        return int(found) if found else None

    if section == "power-outlets" and item.get("power_port"):
        found = resolve("power-ports", item["power_port"])
        if found is None:
            return f"unknown power port {item['power_port']}."
        payload["power_port"] = found
    if section == "front-ports":
        mappings = _front_mappings(doc, item)
        for mapping in mappings:
            found = resolve("rear-ports", mapping["rear_port"])
            if found is None:
                return f"unknown rear port {mapping['rear_port']}."
            mapping["rear_port"] = found
        if mappings:
            payload["rear_ports"] = mappings
    if section == "cooling-outflows" and item.get("cooling_intake"):
        found = resolve("cooling-intakes", item["cooling_intake"])
        if found is None:
            return f"unknown cooling intake {item['cooling_intake']}."
        payload["cooling_intake"] = found
    if section == "inventory-items":
        if item.get("parent"):
            found = resolve("inventory-items", item["parent"])
            if found is None:
                return f"unknown parent {item['parent']}."
            payload["parent"] = found
        if item.get("role"):
            payload["role"] = refs.roles[str(item["role"])]
        if item.get("manufacturer"):
            payload["manufacturer"] = refs.makers[str(item["manufacturer"])]
        target = COMPONENT_TYPE_SECTIONS.get(str(item.get("component_type") or ""))
        if target and item.get("component_name"):
            found = resolve(target, item["component_name"])
            if found is None:
                return f"unknown component {item['component_name']}."
            payload["component_id"] = found
    return ""


def _interface_links(doc, backend: IpamBackend, interfaces: dict[str, str]):
    """Set interface parents and bridges once all interfaces exist."""
    failures = []
    for item in _items(doc, "interfaces"):
        name = str(item.get("name") or "")
        if name not in interfaces:
            continue
        patch = {}
        for column in ("parent", "bridge"):
            value = item.get(column)
            if value and str(value) in interfaces:
                patch[column] = int(interfaces[str(value)])
            elif value:
                failures.append(f"{name}: unknown {column} {value}.")
        if not patch:
            continue
        try:
            backend.update_object(
                f"{TEMPLATES['interfaces']}{interfaces[name]}/", patch
            )
        except NETWORK_ERRORS as error:
            failures.append(f"{name}: {error}")
    return failures


def _upload_images(row: TypeImportRow, backend: IpamBackend, type_id: str):
    if not row.images:
        return []
    upload = getattr(backend, "upload_files", None)
    if upload is None:
        return ["images: this backend cannot upload files."]
    files = {name: Path(path) for name, path in row.images}
    try:
        upload(f"{DEVICE_TYPES}{type_id}/", files)
    except (*NETWORK_ERRORS, OSError) as error:
        return [f"images: {error}"]
    return []


def _verify(row: TypeImportRow, backend: IpamBackend, type_id: str) -> tuple[str, str]:
    try:
        current = backend.read_object(f"{DEVICE_TYPES}{type_id}/")
    except NETWORK_ERRORS as error:
        return "unverified", f"Read-back failed: {error}"
    if current is None:
        return "unverified", "The type was not found after the write."
    mismatches = [
        name
        for name in ("model", "slug", "part_number")
        if row.doc.get(name) and str(current.get(name) or "") != str(row.doc.get(name))
    ]
    mismatches += [name for name, _path in row.images if not current.get(name)]
    for section, endpoint in TEMPLATES.items():
        expected = len(row.doc.get(section) or ())
        if not expected:
            continue
        try:
            found = backend.find_ids(endpoint, device_type_id=type_id, limit=1000)
        except NETWORK_ERRORS as error:
            return "unverified", f"Read-back failed: {error}"
        if len(found) != expected:
            mismatches.append(f"{section} ({len(found)} of {expected})")
    if mismatches:
        return "mismatch", f"NetBox differs in {', '.join(mismatches)}."
    return "verified", "NetBox matches the definition."


def _outcome(row: TypeImportRow, status: str, message: str, object_id: str = ""):
    return NetworkOutcome(row.key, OPERATION, row.label, status, message, object_id)
