"""NetBox device types as local definitions, and their comparison (M14 slice 2).

``read_netbox_types`` reads every device type and every component template
of a NetBox instance in bulk (GET only, paginated, about 14 requests) and
turns each type into a definition in the devicetype-library form, the
reverse of ``devicetype_import``: references become names (manufacturer,
owner, platform, tag slugs, inventory item roles, power ports, parents,
bridges, cooling intakes), ``component_id`` becomes ``component_name`` and
front port ``rear_ports`` become ``port-mappings``. NetBox defaults are left
out, like the library does.

``compare`` matches a local definition with a NetBox type and lists the
differences per field and per template (matched by name). Values are
normalized with NetBox's defaults, so a missing ``enabled: true`` is no
difference. A value missing locally is shown with the NetBox value but never
means "clear it in NetBox" (that is the sync's rule, see M14 slice 5).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

import requests
from ruamel.yaml.comments import CommentedMap

from unifi2netbox.config import NetBoxConfig
from unifi2netbox.devicetype_import import (
    IMAGE_FIELDS,
    TEMPLATES,
    TYPE_FIELDS,
    template_fields,
)
from unifi2netbox.devicetypes import (
    ATTRIBUTES,
    COMPONENT_TYPE_SECTIONS,
    component_columns,
    field_spec,
)
from unifi2netbox.inventory import InventoryError, _netbox_paginated_rows
from unifi2netbox.netbox import ReadOnlySession, RedirectError

DEVICE_TYPES = "/api/dcim/device-types/"
PAGE_SIZE = 1000
MAX_PAGES = 200
SAME = "same"
DIFFERS = "differs"
MISSING = "missing"
LOCAL_ONLY = "local-only"
NETBOX_ONLY = "netbox-only"
# Attributes compared with NetBox (``is_powered`` exists in the library only).
COMPARED = tuple(
    name
    for name in ATTRIBUTES
    if name in TYPE_FIELDS
    or name
    in (
        "manufacturer",
        "default_platform",
        "owner",
        "tags",
        "custom_fields",
        *IMAGE_FIELDS,
    )
)
# Values NetBox assumes when a field is not given (None: per section).
DEFAULTS: dict[str | None, dict[str, object]] = {
    None: {
        "u_height": 1,
        "is_full_depth": True,
        "exclude_from_utilization": False,
        "front_image": False,
        "rear_image": False,
    },
    "interfaces": {"enabled": True, "mgmt_only": False},
    "module-bays": {"enabled": True},
    "device-bays": {"enabled": True},
    "front-ports": {"positions": 1},
    "rear-ports": {"positions": 1},
    "port-mappings": {"front_port_position": 1, "rear_port_position": 1},
}
# Template columns that refer to other objects, by section.
_REFERENCES = {
    "power-outlets": ("power_port",),
    "interfaces": ("parent", "bridge"),
    "cooling-outflows": ("cooling_intake",),
    "inventory-items": ("parent", "role", "manufacturer", "component_name"),
}


class NetBoxTypesError(RuntimeError):
    pass


@dataclass(frozen=True)
class NetBoxType:
    id: str
    doc: Mapping
    device_count: int = 0

    @property
    def manufacturer(self) -> str:
        return str(self.doc.get("manufacturer") or "")

    @property
    def model(self) -> str:
        return str(self.doc.get("model") or "")


@dataclass(frozen=True)
class NetBoxTypes:
    types: tuple[NetBoxType, ...] = ()
    errors: tuple[str, ...] = ()
    loaded: bool = False

    def find(self, doc: Mapping) -> NetBoxType | None:
        """The NetBox type of a definition: by slug, then manufacturer + model/part."""
        slug = str(doc.get("slug") or "").strip()
        if slug:
            found = next(
                (t for t in self.types if str(t.doc.get("slug") or "") == slug), None
            )
            if found is not None:
                return found
        maker = str(doc.get("manufacturer") or "").strip().lower()
        model = str(doc.get("model") or "").strip().lower()
        part = str(doc.get("part_number") or "").strip().lower()
        for item in self.types:
            if item.manufacturer.strip().lower() != maker:
                continue
            if model and item.model.strip().lower() == model:
                return item
            other = str(item.doc.get("part_number") or "").strip().lower()
            if part and other == part:
                return item
        return None


# -- reading ---------------------------------------------------------------------


def read_netbox_types(
    config: NetBoxConfig,
    session_factory: Callable[[NetBoxConfig], requests.Session] = ReadOnlySession,
) -> NetBoxTypes:
    """All device types with their templates, as definitions (GET only)."""
    try:
        with session_factory(config) as session:

            def rows(path: str) -> list[dict]:
                return _netbox_paginated_rows(
                    session,
                    config,
                    path,
                    page_size=PAGE_SIZE,
                    max_pages=MAX_PAGES,
                    limit_error=f"NetBox returned too many objects for {path}.",
                )

            types = rows(DEVICE_TYPES)
            templates = {section: rows(path) for section, path in TEMPLATES.items()}
    except (InventoryError, RedirectError, requests.RequestException) as error:
        message = (
            "NetBox redirected the request."
            if isinstance(error, RedirectError)
            else str(error) or error.__class__.__name__
        )
        return NetBoxTypes(errors=(message,), loaded=False)
    grouped: dict[str, dict[str, list[dict]]] = {}
    for section, items in templates.items():
        for row in items:
            owner = _id(row.get("device_type"))
            if owner:  # module type templates have no device type
                grouped.setdefault(owner, {}).setdefault(section, []).append(row)
    result = tuple(
        NetBoxType(
            _id(row.get("id")),
            netbox_definition(row, grouped.get(_id(row.get("id")), {})),
            int(row.get("device_count") or 0),
        )
        for row in types
    )
    return NetBoxTypes(result, (), True)


def netbox_definition(row: Mapping, templates: Mapping[str, list[Mapping]]):
    """One NetBox device type (API row plus its template rows) as a definition."""
    doc = CommentedMap()
    for name in COMPARED:
        value = _plain(row.get(name))
        if name in IMAGE_FIELDS:
            value = True if row.get(name) else None
        elif name == "tags":
            value = (
                sorted(str(tag.get("slug")) for tag in row.get("tags") or () if tag)
                or None
            )
        elif name == "custom_fields":
            custom = {
                k: v for k, v in (row.get(name) or {}).items() if v not in (None, "")
            }
            value = CommentedMap(sorted(custom.items())) if custom else None
        elif name == "comments" and isinstance(value, str):
            value = value.strip()
        # The library always writes the height and depth, even at defaults.
        if value is None or (
            name not in ("u_height", "is_full_depth") and _is_default(None, name, value)
        ):
            continue
        doc[name] = value
    names = {
        section: {_id(item.get("id")): str(item.get("name") or "") for item in items}
        for section, items in templates.items()
    }
    for section in COMPONENT_ORDER:
        if section == "port-mappings":
            mappings = _mappings(templates.get("front-ports", ()), names)
            if mappings:
                doc[section] = mappings
            continue
        items = templates.get(section, ())  # NetBox's natural order
        converted = [_template(section, item, names) for item in items]
        if converted:
            doc[section] = converted
    return doc


COMPONENT_ORDER = (
    "console-ports",
    "console-server-ports",
    "power-ports",
    "power-outlets",
    "interfaces",
    "front-ports",
    "rear-ports",
    "port-mappings",
    "module-bays",
    "device-bays",
    "inventory-items",
    "cooling-intakes",
    "cooling-outflows",
)


def _template(section: str, item: Mapping, names) -> CommentedMap:
    row = CommentedMap()
    fields = set(template_fields(section)) | set(_REFERENCES.get(section, ()))
    for column in component_columns(section):
        if column not in fields:
            continue
        if column in ("power_port", "bridge", "cooling_intake") or (
            column == "parent" and section == "interfaces"
        ):
            value = _name(item.get(column))
        elif column == "parent":  # inventory items: an ID of a sibling
            value = names.get(section, {}).get(_id(item.get(column))) or None
        elif column in ("role", "manufacturer"):
            value = _name(item.get(column))
        elif column == "component_name":
            target = COMPONENT_TYPE_SECTIONS.get(str(item.get("component_type") or ""))
            value = (
                names.get(target, {}).get(_id(item.get("component_id")))
                if target
                else None
            ) or _name(item.get("component"))
        else:
            value = _plain(item.get(column))
        if value is None or (
            not field_spec(section, column).required
            and _is_default(section, column, value)
        ):
            continue  # required columns are kept, as the library does
        row[column] = value
    return row


def _mappings(front_ports: Iterable[Mapping], names) -> list[CommentedMap]:
    result = []
    for port in front_ports:
        for mapping in port.get("rear_ports") or ():
            if not isinstance(mapping, Mapping):
                continue
            rear = mapping.get("rear_port")
            rear_name = _name(rear) or names.get("rear-ports", {}).get(_id(rear))
            row = CommentedMap()
            row["front_port"] = str(port.get("name") or "")
            row["front_port_position"] = int(mapping.get("position") or 1)
            row["rear_port"] = rear_name or ""
            row["rear_port_position"] = int(mapping.get("rear_port_position") or 1)
            result.append(row)
    return result


def _id(value) -> str:
    if isinstance(value, Mapping):
        value = value.get("id")
    return "" if value in (None, "") else str(value)


def _name(value) -> str | None:
    if isinstance(value, Mapping):
        return str(value.get("name") or value.get("display") or "") or None
    return None


def _plain(value):
    """API values as YAML values: choices by value, whole floats as ints."""
    if isinstance(value, Mapping) and "value" in value and "label" in value:
        value = value.get("value")
    elif isinstance(value, Mapping) and "name" in value:
        value = value.get("name")
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if value in ("", [], {}):
        return None
    return value


# -- comparison ------------------------------------------------------------------


@dataclass(frozen=True)
class FieldDiff:
    name: str
    local: object
    netbox: object


@dataclass(frozen=True)
class RowDiff:
    key: str  # template name (port mappings: "front_port/position")
    kind: str  # local-only, netbox-only, differs
    fields: tuple[FieldDiff, ...] = ()
    netbox_row: Mapping | None = None


@dataclass(frozen=True)
class TypeComparison:
    status: str  # same, differs, missing
    netbox: NetBoxType | None = None
    fields: tuple[FieldDiff, ...] = ()
    templates: Mapping[str, tuple[RowDiff, ...]] = field(default_factory=dict)

    def field_diff(self, name: str) -> FieldDiff | None:
        return next((f for f in self.fields if f.name == name), None)

    def rows(self, section: str) -> tuple[RowDiff, ...]:
        return tuple(self.templates.get(section, ()))

    def row(self, section: str, key: str) -> RowDiff | None:
        return next((r for r in self.rows(section) if r.key == key), None)

    def summary(self) -> str:
        if self.status == MISSING:
            return "Not in NetBox."
        if self.status == SAME:
            return "Equal to NetBox."
        parts = []
        if self.fields:
            parts.append(f"{len(self.fields)} field(s)")
        for section, rows in self.templates.items():
            if rows:
                parts.append(f"{len(rows)} {section}")
        return f"Differs from NetBox: {', '.join(parts)}."


def compare(local: Mapping, types: NetBoxTypes) -> TypeComparison:
    """How a local definition relates to NetBox."""
    found = types.find(local)
    if found is None:
        return TypeComparison(MISSING)
    netbox = found.doc
    fields = tuple(
        FieldDiff(name, local.get(name), netbox.get(name))
        for name in COMPARED
        if _norm(None, name, local.get(name)) != _norm(None, name, netbox.get(name))
    )
    templates = {}
    for section in COMPONENT_ORDER:
        rows = _compare_rows(section, local.get(section), netbox.get(section))
        if rows:
            templates[section] = rows
    status = DIFFERS if fields or templates else SAME
    return TypeComparison(status, found, fields, templates)


def row_key(section: str, row: Mapping) -> str:
    if section == "port-mappings":
        position = row.get("front_port_position") or 1
        return f"{row.get('front_port') or ''}/{position}"
    return str(row.get("name") or "")


def _compare_rows(section: str, local, netbox) -> tuple[RowDiff, ...]:
    local_rows = {row_key(section, r): r for r in local or () if isinstance(r, Mapping)}
    netbox_rows = {
        row_key(section, r): r for r in netbox or () if isinstance(r, Mapping)
    }
    columns = _compared_columns(section)
    result = []
    for key, row in local_rows.items():
        other = netbox_rows.get(key)
        if other is None:
            result.append(RowDiff(key, LOCAL_ONLY))
            continue
        diffs = tuple(
            FieldDiff(column, row.get(column), other.get(column))
            for column in columns
            if _norm(section, column, row.get(column))
            != _norm(section, column, other.get(column))
        )
        if diffs:
            result.append(RowDiff(key, DIFFERS, diffs, other))
    for key, row in netbox_rows.items():
        if key not in local_rows:
            result.append(RowDiff(key, NETBOX_ONLY, (), row))
    return tuple(result)


def _compared_columns(section: str) -> tuple[str, ...]:
    if section == "port-mappings":
        return ("rear_port", "rear_port_position")
    known = set(template_fields(section)) | set(_REFERENCES.get(section, ()))
    return tuple(c for c in component_columns(section) if c in known)


def _is_default(section: str | None, name: str, value) -> bool:
    if value is None or value == "" or value == [] or value == {}:
        return True
    return DEFAULTS.get(section, {}).get(name, object()) == value


def _norm(section: str | None, name: str, value):
    """Comparable form: defaults filled in, numbers as floats, tags sorted."""
    if isinstance(value, Mapping):
        value = {str(k): _norm(None, str(k), v) for k, v in value.items()}
        value = {k: v for k, v in value.items() if v is not None}
        return tuple(sorted(value.items())) or None
    if isinstance(value, list | tuple):
        items = [str(v) for v in value]
        return tuple(sorted(items) if name == "tags" else items) or None
    if value is None or value == "":
        value = DEFAULTS.get(section, {}).get(name)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    try:
        return float(text) if name in ("u_height", "weight") else text
    except ValueError:
        return text
