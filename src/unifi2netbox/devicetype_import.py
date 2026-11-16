"""Import chosen device type definitions into NetBox (M12 slice 6).

A create row may use a definition from the local type folder or the
devicetype-library instead of a NetBox device type. Each distinct definition
becomes one selectable plan row:

- ``reuse``: NetBox already has a type with the same manufacturer and model
  or the same part number; its ID is used and nothing is written.
- ``create``: the type and its component templates are created, as a visible
  write step before device writes (after the Custom Field).
- ``blocked``: the manufacturer is missing in NetBox (it is never created),
  the definition is invalid, or it uses components the import does not
  support (front/rear ports and port mappings: import those in NetBox).

Execution re-reads NetBox (an existing slug is reused, never duplicated),
looks up interrupted creates by slug or name instead of retrying, reads the
type back and counts its templates. Dry runs perform the checks only.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace

from unifi2netbox.devicetypes import errors, validate
from unifi2netbox.inventory import InventoryDeviceType, InventoryManufacturer
from unifi2netbox.network_execute import NETWORK_ERRORS, IpamBackend, NetworkOutcome
from unifi2netbox.write_execute import AMBIGUOUS_CREATE_ERRORS

CREATE = "create"
REUSE = "reuse"
BLOCKED = "blocked"
OPERATION = "import_device_type"
DEVICE_TYPES = "/api/dcim/device-types/"
MANUFACTURERS = "/api/dcim/manufacturers/"
# Section -> (template endpoint, allowed fields). Order matters: power ports
# before outlets (outlets refer to them by name).
TEMPLATES = {
    "console-ports": (
        "/api/dcim/console-port-templates/",
        ("name", "label", "type", "description"),
    ),
    "console-server-ports": (
        "/api/dcim/console-server-port-templates/",
        ("name", "label", "type", "description"),
    ),
    "power-ports": (
        "/api/dcim/power-port-templates/",
        ("name", "label", "type", "maximum_draw", "allocated_draw", "description"),
    ),
    "power-outlets": (
        "/api/dcim/power-outlet-templates/",
        ("name", "label", "type", "power_port", "feed_leg", "description"),
    ),
    "interfaces": (
        "/api/dcim/interface-templates/",
        (
            "name",
            "label",
            "type",
            "enabled",
            "mgmt_only",
            "description",
            "poe_mode",
            "poe_type",
            "rf_role",
        ),
    ),
    "module-bays": (
        "/api/dcim/module-bay-templates/",
        ("name", "label", "position", "description"),
    ),
    "device-bays": (
        "/api/dcim/device-bay-templates/",
        ("name", "label", "description"),
    ),
    "inventory-items": (
        "/api/dcim/inventory-item-templates/",
        ("name", "label", "part_id", "description"),
    ),
}
UNSUPPORTED = ("front-ports", "rear-ports", "port-mappings")
TYPE_FIELDS = (
    "model",
    "slug",
    "part_number",
    "u_height",
    "is_full_depth",
    "airflow",
    "weight",
    "weight_unit",
    "subdevice_role",
    "description",
    "comments",
)
SKIP_PREFIX = "skip:"
PENDING_ID = "pending-import"


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

    @property
    def selectable(self) -> bool:
        return self.action == CREATE

    @property
    def template_count(self) -> int:
        return sum(len(self.doc.get(section) or ()) for section in TEMPLATES)


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
) -> TypeImportPlan:
    """``choices`` maps device keys to import choices (``local:``/``library:``)."""
    by_choice: dict[str, list[str]] = {}
    for device_key, choice in choices.items():
        by_choice.setdefault(choice, []).append(device_key)
    makers = {m.name.strip().lower(): m.source_id for m in manufacturers}
    types = tuple(netbox_types)
    skipped = set(deselected)
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
            _row(choice, label, doc, tuple(sorted(device_keys)), makers, types, skipped)
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


def _row(choice, label, doc, device_keys, makers, types, skipped) -> TypeImportRow:
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
    unsupported = [s for s in UNSUPPORTED if doc.get(s)]
    if unsupported:
        notes.append(
            f"{', '.join(unsupported)} cannot be imported by the app; import this "
            "type in NetBox (Device Types > Import)."
        )
    manufacturer_id = makers.get(manufacturer.lower(), "")
    if not manufacturer_id:
        notes.insert(
            0,
            f"Manufacturer '{manufacturer}' is not in NetBox; create it there first "
            "(the app never creates manufacturers).",
        )
    if notes:
        return TypeImportRow(action=BLOCKED, notes=tuple(notes), **base)
    return TypeImportRow(
        action=CREATE,
        manufacturer_id=manufacturer_id,
        selected=choice not in skipped,
        notes=(f"Creates the type and {_count(doc)} component templates.",),
        **base,
    )


def _count(doc: Mapping) -> int:
    return sum(len(doc.get(section) or ()) for section in TEMPLATES)


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
    except NETWORK_ERRORS as error:
        return _outcome(row, "failed", f"NetBox lookup failed: {error}"), ""
    if not makers:
        return (
            _outcome(row, "skipped", f"Manufacturer {row.manufacturer} is missing."),
            "",
        )
    if dry_run:
        return _outcome(row, "skipped", "Dry-run mode: not imported."), ""
    payload: dict[str, object] = {"manufacturer": int(makers[0])}
    for name in TYPE_FIELDS:
        value = row.doc.get(name)
        if value not in (None, ""):
            payload[name] = value
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
    created, failures = _templates(row, backend, str(type_id))
    verification, detail = _verify(row, backend, str(type_id))
    if failures:
        return (
            NetworkOutcome(
                row.key,
                OPERATION,
                row.label,
                "failed",
                f"{message}, but {len(failures)} of {created + len(failures)} "
                f"templates failed: {failures[0]} Check the type in NetBox.",
                str(type_id),
                verification,
                detail,
            ),
            str(type_id),
        )
    return (
        NetworkOutcome(
            row.key,
            OPERATION,
            row.label,
            "success",
            f"{message} with {created} component templates.",
            str(type_id),
            verification,
            detail,
        ),
        str(type_id),
    )


def _templates(row: TypeImportRow, backend: IpamBackend, type_id: str):
    created = 0
    failures: list[str] = []
    power_ports: dict[str, str] = {}
    for section, (endpoint, allowed) in TEMPLATES.items():
        for item in row.doc.get(section) or ():
            if not isinstance(item, Mapping):
                continue
            payload: dict[str, object] = {"device_type": int(type_id)}
            for name in allowed:
                value = item.get(name)
                if value in (None, ""):
                    continue
                if name == "power_port":
                    if value not in power_ports:
                        failures.append(
                            f"{item.get('name')}: unknown power port {value}."
                        )
                        payload = {}
                        break
                    value = int(power_ports[value])
                payload[name] = value
            if not payload:
                continue
            try:
                template_id = backend.create_object(endpoint, payload)
            except AMBIGUOUS_CREATE_ERRORS:
                try:
                    found = backend.find_ids(
                        endpoint, device_type_id=type_id, name=item.get("name")
                    )
                except NETWORK_ERRORS as error:
                    failures.append(f"{item.get('name')}: {error}")
                    continue
                if len(found) != 1:
                    failures.append(f"{item.get('name')}: interrupted create.")
                    continue
                template_id = found[0]
            except NETWORK_ERRORS as error:
                failures.append(f"{item.get('name')}: {error}")
                continue
            created += 1
            if section == "power-ports":
                power_ports[str(item.get("name"))] = str(template_id)
    return created, failures


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
    for section, (endpoint, _allowed) in TEMPLATES.items():
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
