"""NetBox device type definitions in the devicetype-library format (Qt-free).

Files follow netbox-community/devicetype-library: one YAML file per model under
``device-types/<Manufacturer>/<model or part number>.yaml``, validated against
the library's JSON schema (bundled under ``resources/devicetype-schema``) and
the rules of its ``CONTRIBUTING.md``:

- the file name is the model or the part number, without the manufacturer,
- the slug starts with the slugified manufacturer and ends with the slugified
  model or part number (lowercase letters, digits and hyphens only),
- no empty or null values,
- ``weight``, ``weight_unit`` and ``airflow`` are recommended,
- attributes come before components, two-space indentation, lists indented
  by two (``  - name: ...``), quotes only where needed, a final newline.

Documents are ruamel ``CommentedMap`` objects, so an existing file is written
back with its key order and comments; new documents use the library order.
"""

from __future__ import annotations

import copy
import io
import json
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import cache
from importlib.resources import files
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError
from ruamel.yaml.scalarstring import LiteralScalarString

DEVICE_TYPES = "device-types"
SUFFIXES = (".yaml", ".yml")

# Attribute order for new documents (CONTRIBUTING: attributes first).
# Library attributes plus every NetBox 4.7 device type field (M13).
ATTRIBUTES = (
    "manufacturer",
    "model",
    "slug",
    "part_number",
    "description",
    "u_height",
    "is_full_depth",
    "exclude_from_utilization",
    "airflow",
    "cooling_method",
    "weight",
    "weight_unit",
    "subdevice_role",
    "is_powered",
    "default_platform",
    "owner",
    "end_of_life",
    "front_image",
    "rear_image",
    "tags",
    "custom_fields",
    "comments",
)
# Device type fields NetBox has but the devicetype-library schema does not.
NETBOX_ATTRIBUTES = (
    "exclude_from_utilization",
    "cooling_method",
    "default_platform",
    "owner",
    "end_of_life",
    "tags",
    "custom_fields",
)
# Attributes that refer to NetBox objects, by name (tags: by slug).
REFERENCES = {
    "manufacturer": "dcim/manufacturers",
    "default_platform": "dcim/platforms",
    "owner": "users/owners",
}
COMPONENTS = (
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
# Component section -> NetBox template endpoint.
SECTION_ENDPOINTS = {
    "console-ports": "dcim/console-port-templates",
    "console-server-ports": "dcim/console-server-port-templates",
    "power-ports": "dcim/power-port-templates",
    "power-outlets": "dcim/power-outlet-templates",
    "interfaces": "dcim/interface-templates",
    "front-ports": "dcim/front-port-templates",
    "rear-ports": "dcim/rear-port-templates",
    "module-bays": "dcim/module-bay-templates",
    "device-bays": "dcim/device-bay-templates",
    "inventory-items": "dcim/inventory-item-templates",
    "cooling-intakes": "dcim/cooling-intake-templates",
    "cooling-outflows": "dcim/cooling-outflow-templates",
}
# Component section -> definition name in the library schema.
COMPONENT_DEFINITIONS = {
    "console-ports": "console-port",
    "console-server-ports": "console-server-port",
    "power-ports": "power-port",
    "power-outlets": "power-outlet",
    "interfaces": "interface",
    "front-ports": "front-port",
    "rear-ports": "rear-port",
    "port-mappings": "port-mappings",
    "module-bays": "module-bay",
    "device-bays": "device-bay",
    "inventory-items": "inventory-item",
    "cooling-intakes": "cooling-intake",
    "cooling-outflows": "cooling-outflow",
}
# Template fields handled elsewhere or not stored in the YAML.
_TEMPLATE_SKIP = {"device_type", "module_type", "rear_ports", "front_ports"}
_DATE = r"^\d{4}-\d{2}-\d{2}$"
# Template fields whose NetBox metadata has no usable type or choices.
_COMPONENT_TEMPLATES = [
    "dcim.consoleporttemplate",
    "dcim.consoleserverporttemplate",
    "dcim.frontporttemplate",
    "dcim.interfacetemplate",
    "dcim.poweroutlettemplate",
    "dcim.powerporttemplate",
    "dcim.rearporttemplate",
]
_TEMPLATE_OVERRIDES = {
    "inventory-items": {
        "component_type": {"type": "string", "enum": _COMPONENT_TEMPLATES},
    },
    "module-bays": {
        "module_bay_types": {"type": "array", "items": {"type": "string"}},
    },
}
RECOMMENDED = ("weight", "weight_unit", "airflow")
_UNSAFE_FILE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

# Short explanations for the table view (our own words).
FIELD_HELP = {
    "manufacturer": "Manufacturer name exactly as in NetBox and the library "
    "folder name, for example 'Ubiquiti'.",
    "model": "Model name shown in NetBox, for example 'UniFi Switch 24 Pro'.",
    "slug": "URL-safe ID: slugified manufacturer, a hyphen, then the slugified "
    "model or part number (lowercase letters, digits, hyphens).",
    "part_number": "Manufacturer part number or SKU, for example 'USW-Pro-24'. "
    "The app also matches UniFi models by it.",
    "description": "Short description of the device type.",
    "u_height": "Height in rack units; 0 for devices that are not rack mounted.",
    "is_full_depth": "True if the device occupies the full rack depth "
    "(front and rear).",
    "airflow": "Direction of the air flow, for example front-to-rear or passive "
    "(recommended by the library).",
    "weight": "Weight of the device (recommended by the library).",
    "weight_unit": "Unit of the weight: kg, g, lb or oz.",
    "front_image": "True if a front image exists (elevation-images folder); "
    "uploaded on import.",
    "rear_image": "True if a rear image exists (elevation-images folder); "
    "uploaded on import.",
    "exclude_from_utilization": "True to leave devices of this type out of the "
    "rack utilization.",
    "cooling_method": "How the device is cooled: air, liquid, hybrid or immersion.",
    "default_platform": "Default operating system (NetBox platform) for devices "
    "of this type.",
    "owner": "NetBox owner responsible for this device type.",
    "end_of_life": "Date after which the manufacturer no longer supports the type "
    "(YYYY-MM-DD).",
    "tags": "NetBox tags, by slug.",
    "custom_fields": "Values of NetBox custom fields for device types.",
    "subdevice_role": "parent if the device has device bays, child if it sits "
    "in another device's bay.",
    "is_powered": "False for devices without power (for example patch panels).",
    "comments": "Free text, for example a link to the data sheet or tech specs.",
}
COLUMN_HELP = {
    "name": "Name as shown by the device's operating system.",
    "label": "Physical label, if it differs from the name.",
    "type": "Connector or port type.",
    "enabled": "False if the port is disabled by default.",
    "mgmt_only": "True for a dedicated management port.",
    "description": "Short description.",
    "bridge": "Name of the interface this one is bridged to.",
    "poe_mode": "pse supplies PoE, pd is powered by PoE.",
    "poe_type": "PoE standard of the port.",
    "rf_role": "Wireless role (access point or station).",
    "maximum_draw": "Maximum power draw in watts.",
    "allocated_draw": "Allocated power draw in watts.",
    "power_port": "Power port that feeds this outlet.",
    "feed_leg": "Phase leg of a three-phase feed.",
    "position": "Position of the bay or item.",
    "positions": "Number of positions of the rear port.",
    "rear_port": "Rear port this front port maps to.",
    "rear_port_position": "Position on the rear port.",
    "manufacturer": "Manufacturer of the item.",
    "part_id": "Part number of the item.",
    "channels": "Number of wireless channels (virtual interfaces).",
    "channel_id": "Channel number.",
    "parent": "Parent component (by name).",
    "role": "NetBox inventory item role.",
    "component_type": "Kind of component the item belongs to.",
    "component_name": "Name of the component the item belongs to.",
    "module_bay_types": "Module type profiles the bay accepts.",
    "diameter": "Diameter of the cooling connection.",
    "diameter_unit": "Unit of the diameter.",
    "max_flow": "Maximum coolant flow.",
    "max_flow_unit": "Unit of the flow.",
    "cooling_intake": "Cooling intake this outflow belongs to (by name).",
    "color": "Cable color (hex).",
}


@dataclass(frozen=True)
class Issue:
    level: str  # "error" or "warning"
    location: str
    message: str

    def __str__(self) -> str:
        where = f"{self.location}: " if self.location else ""
        return f"{self.level.capitalize()}: {where}{self.message}"


class DeviceTypeError(ValueError):
    pass


# -- schema --------------------------------------------------------------------


@cache
def _schemas() -> dict[str, dict]:
    folder = files("unifi2netbox") / "resources" / "devicetype-schema"
    result = {}
    for name in (
        "components.json",
        "devicetype.json",
        "generated_schema.json",
        "reusable.json",
    ):
        result[name] = json.loads((folder / name).read_text(encoding="utf-8"))
    return result


@cache
def netbox_metadata() -> dict:
    """Writable NetBox fields per endpoint (bundled, newest NetBox series)."""
    folder = files("unifi2netbox") / "resources" / "netbox-metadata"
    names = sorted(
        (item.name for item in folder.iterdir() if item.name.endswith(".json")),
        key=lambda n: tuple(int(p) for p in re.findall(r"\d+", n)),
    )
    if not names:
        return {"netbox_version": "", "endpoints": {}}
    return json.loads((folder / names[-1]).read_text(encoding="utf-8"))


def _netbox_property(field: Mapping) -> dict:
    """JSON schema of one NetBox field as stored in the YAML (references by name)."""
    if field.get("choices"):
        return {"type": "string", "enum": list(field["choices"])}
    kind = field.get("type")
    if kind == "boolean":
        return {"type": "boolean"}
    if kind == "integer":
        return {"type": "integer"}
    if kind == "decimal":
        return {"type": "number"}
    if kind == "date":
        return {"type": "string", "pattern": _DATE}
    if kind == "field" and field.get("children"):
        return {"type": "array", "items": {"type": "string"}}
    if kind == "field":
        return {"type": ["string", "array"]}
    return {"type": "string"}


@cache
def _extended() -> dict[str, dict]:
    """The library schema plus every NetBox device type and template field."""
    schemas = copy.deepcopy(_schemas())
    endpoints = netbox_metadata().get("endpoints", {})
    device = schemas["devicetype.json"]
    props = device["properties"]
    netbox = endpoints.get("dcim/device-types", {})
    for name in NETBOX_ATTRIBUTES:
        if name == "tags":
            props[name] = {"type": "array", "items": {"type": "string"}}
        elif name == "custom_fields":
            props[name] = {"type": "object"}
        elif name in netbox:
            props[name] = _netbox_property(netbox[name])
    components = schemas["components.json"]["definitions"]
    for section, endpoint in SECTION_ENDPOINTS.items():
        definition = COMPONENT_DEFINITIONS[section]
        node = components.setdefault(
            definition, {"type": "object", "additionalProperties": False}
        )
        node.setdefault("properties", {})
        fields = endpoints.get(endpoint, {})
        for name, field in fields.items():
            if name in _TEMPLATE_SKIP or name in node["properties"]:
                continue
            if name == "component_id":
                node["properties"]["component_name"] = {"type": "string"}
                continue
            node["properties"][name] = _netbox_property(field)
        node["properties"].update(copy.deepcopy(_TEMPLATE_OVERRIDES.get(section, {})))
        if "required" not in node:
            node["required"] = [
                n
                for n, f in fields.items()
                if f.get("required") and n not in _TEMPLATE_SKIP
            ]
        if section not in props:
            props[section] = {
                "type": "array",
                "items": {
                    "$ref": "urn:devicetype-library:components#/definitions/"
                    + definition
                },
            }
    return schemas


@cache
def _validator() -> Draft202012Validator:
    schemas = _extended()
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
    )
    return Draft202012Validator(schemas["devicetype.json"], registry=registry)


def choices(definition: str, field: str) -> tuple[str, ...]:
    """Allowed values of a field, e.g. ``choices("interface", "type")``."""
    generated = _schemas()["generated_schema.json"]["definitions"]
    if definition in ("airflow", "weight-unit", "subdevice-role"):
        return tuple(generated.get(definition, {}).get("enum", ()))
    node = generated.get(definition, {}).get("properties", {}).get(field, {})
    found = tuple(node.get("enum", ()))
    if found:
        return found
    section = next(
        (s for s, d in COMPONENT_DEFINITIONS.items() if d == definition), None
    )
    return field_spec(section, field).choices if section else ()


def component_columns(section: str) -> tuple[str, ...]:
    """Fields of one component section: library order, then NetBox fields."""
    definition = COMPONENT_DEFINITIONS[section]
    props = _extended()["components.json"]["definitions"][definition].get(
        "properties", {}
    )
    return tuple(props)


def required_columns(section: str) -> tuple[str, ...]:
    definition = COMPONENT_DEFINITIONS[section]
    node = _extended()["components.json"]["definitions"][definition]
    return tuple(node.get("required", ()))


# -- YAML ----------------------------------------------------------------------


def _yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.explicit_start = True
    yaml.width = 4096
    yaml.preserve_quotes = True
    return yaml


def load_yaml(text: str) -> CommentedMap:
    """Parse one definition; raises ``DeviceTypeError`` for invalid YAML."""
    try:
        data = _yaml().load(text)
    except YAMLError as error:
        raise DeviceTypeError(f"Invalid YAML: {error}") from error
    if data is None:
        return CommentedMap()
    if not isinstance(data, Mapping):
        raise DeviceTypeError("A device type file must be a YAML mapping.")
    if not isinstance(data, CommentedMap):
        data = CommentedMap(data)
    return data


def dump_yaml(doc: Mapping) -> str:
    """Write a definition in library style (empties dropped, final newline)."""
    clean = _clean(_ordered(doc))
    stream = io.StringIO()
    _yaml().dump(clean, stream)
    text = stream.getvalue()
    return text if text.endswith("\n") else text + "\n"


def new_document(manufacturer: str = "", model: str = "") -> CommentedMap:
    doc = CommentedMap()
    doc["manufacturer"] = manufacturer
    doc["model"] = model
    doc["slug"] = device_slug(manufacturer, model) if manufacturer and model else ""
    doc["u_height"] = 0
    doc["is_full_depth"] = False
    return doc


def _ordered(doc: Mapping) -> CommentedMap:
    """Attributes before components; existing order kept otherwise."""
    if isinstance(doc, CommentedMap):
        keys = list(doc)
    else:
        keys = [k for k in ATTRIBUTES if k in doc] + [
            k for k in doc if k not in ATTRIBUTES and k not in COMPONENTS
        ]
        keys += [k for k in COMPONENTS if k in doc]
    attributes = [k for k in keys if k not in COMPONENTS]
    components = [k for k in keys if k in COMPONENTS]
    if isinstance(doc, CommentedMap) and keys == attributes + components:
        return doc
    ordered = CommentedMap()
    for key in attributes + components:
        ordered[key] = doc[key]
    return ordered


def _clean(value):
    """Drop None, empty strings and empty lists or mappings recursively."""
    if isinstance(value, Mapping):
        target = value if isinstance(value, CommentedMap) else CommentedMap(value)
        for key in list(target):
            item = _clean(target[key])
            if _empty(item):
                del target[key]
            else:
                target[key] = item
        return target
    if isinstance(value, list):
        items = [_clean(item) for item in value]
        items = [item for item in items if not _empty(item)]
        if isinstance(value, CommentedSeq):
            value[:] = items
            return value
        return CommentedSeq(items)
    if isinstance(value, str) and "\n" in value.strip("\n"):
        text = value if value.endswith("\n") else value + "\n"
        return LiteralScalarString(text)
    return value


def _empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, Mapping)):
        return not value
    return False


# -- names ---------------------------------------------------------------------


def slugify(value: str) -> str:
    text = value.strip().lower().replace("+", "-plus")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return re.sub(r"-{2,}", "-", text).strip("-")


def device_slug(manufacturer: str, model_or_part: str) -> str:
    return f"{slugify(manufacturer)}-{slugify(model_or_part)}"


def file_stem(doc: Mapping) -> str:
    """Preferred file name: the part number, else the model."""
    return str(doc.get("part_number") or doc.get("model") or "").strip()


def safe_file_name(stem: str) -> bool:
    return bool(stem) and not _UNSAFE_FILE.search(stem) and stem not in (".", "..")


# -- validation ----------------------------------------------------------------


def validate(doc: Mapping, path: Path | None = None) -> tuple[Issue, ...]:
    """Schema errors plus the CONTRIBUTING rules; warnings for advice."""
    issues: list[Issue] = []
    plain = json.loads(json.dumps(doc, default=str))
    for error in sorted(_validator().iter_errors(plain), key=lambda e: list(e.path)):
        if error.validator == "multipleOf" and _exact_multiple(
            error.instance, error.validator_value
        ):
            continue  # 2.3 / 0.01 is 229.999... in floating point
        where = "/".join(str(part) for part in error.path)
        issues.append(Issue("error", where, error.message))
    issues += _empty_values(doc, "")
    manufacturer = str(doc.get("manufacturer") or "").strip()
    model = str(doc.get("model") or "").strip()
    part = str(doc.get("part_number") or "").strip()
    slug = str(doc.get("slug") or "").strip()
    if manufacturer and slug:
        endings = {slugify(name) for name in (model, part) if name}
        if not re.fullmatch(r"[a-z0-9-]+", slug):
            issues.append(
                Issue(
                    "error", "slug", "Use only lowercase letters, digits and hyphens."
                )
            )
        if not slug.startswith(slugify(manufacturer) + "-"):
            issues.append(
                Issue(
                    "error",
                    "slug",
                    f"Must start with '{slugify(manufacturer)}-' (the slugified "
                    "manufacturer).",
                )
            )
        elif endings and not any(slug.endswith(end) for end in endings):
            issues.append(
                Issue(
                    "error",
                    "slug",
                    "Must end with the slugified model or part number "
                    f"({' or '.join(sorted(endings))}).",
                )
            )
    if path is not None:
        if path.suffix not in SUFFIXES:
            issues.append(Issue("error", "file", "The file must end in .yaml or .yml."))
        if path.stem not in {name for name in (model, part) if name}:
            issues.append(
                Issue(
                    "error",
                    "file",
                    f"The file name '{path.name}' must be the model or the part "
                    "number.",
                )
            )
        if manufacturer and path.parent.name != manufacturer:
            issues.append(
                Issue(
                    "error",
                    "file",
                    f"The folder '{path.parent.name}' must be the manufacturer "
                    f"'{manufacturer}'.",
                )
            )
    for section in COMPONENTS:
        names = [
            str(item.get("name"))
            for item in doc.get(section) or ()
            if isinstance(item, Mapping) and item.get("name")
        ]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            issues.append(
                Issue("error", section, f"Duplicate names: {', '.join(duplicates)}.")
            )
    issues += _sibling_issues(doc)
    if doc.get("weight") is not None and not doc.get("weight_unit"):
        issues.append(Issue("error", "weight_unit", "A weight needs a weight unit."))
    for field in RECOMMENDED:
        if doc.get(field) in (None, ""):
            issues.append(
                Issue("warning", field, "Recommended by the library; add it if known.")
            )
    return tuple(issues)


# (section, column) -> section whose component names the column refers to.
SIBLING_REFERENCES = {
    ("power-outlets", "power_port"): "power-ports",
    ("interfaces", "parent"): "interfaces",
    ("interfaces", "bridge"): "interfaces",
    ("port-mappings", "front_port"): "front-ports",
    ("port-mappings", "rear_port"): "rear-ports",
    ("inventory-items", "parent"): "inventory-items",
    ("cooling-outflows", "cooling_intake"): "cooling-intakes",
}
# inventory-items component_type -> section holding the component.
COMPONENT_TYPE_SECTIONS = {
    "dcim.consoleporttemplate": "console-ports",
    "dcim.consoleserverporttemplate": "console-server-ports",
    "dcim.frontporttemplate": "front-ports",
    "dcim.interfacetemplate": "interfaces",
    "dcim.poweroutlettemplate": "power-outlets",
    "dcim.powerporttemplate": "power-ports",
    "dcim.rearporttemplate": "rear-ports",
}
# (section or None for attributes, column) -> NetBox catalog kind.
CATALOG_REFERENCES = {
    (None, "manufacturer"): "manufacturers",
    (None, "owner"): "owners",
    (None, "default_platform"): "platforms",
    ("inventory-items", "manufacturer"): "manufacturers",
    ("inventory-items", "role"): "inventory_item_roles",
}


def component_names(doc: Mapping, section: str) -> tuple[str, ...]:
    return tuple(
        str(item["name"])
        for item in doc.get(section) or ()
        if isinstance(item, Mapping) and item.get("name")
    )


def _sibling_issues(doc: Mapping) -> list[Issue]:
    issues = []
    for (section, column), target in SIBLING_REFERENCES.items():
        known = set(component_names(doc, target))
        for index, item in enumerate(doc.get(section) or ()):
            if not isinstance(item, Mapping) or not item.get(column):
                continue
            value = str(item[column])
            if value not in known:
                issues.append(
                    Issue(
                        "error",
                        f"{section}/{index}/{column}",
                        f"'{value}' is not one of the {target} of this definition.",
                    )
                )
            elif column in ("parent", "bridge") and value == item.get("name"):
                issues.append(
                    Issue(
                        "error",
                        f"{section}/{index}/{column}",
                        "A component cannot refer to itself.",
                    )
                )
    for index, item in enumerate(doc.get("inventory-items") or ()):
        if not isinstance(item, Mapping):
            continue
        target = COMPONENT_TYPE_SECTIONS.get(str(item.get("component_type") or ""))
        name = item.get("component_name")
        where = f"inventory-items/{index}/component_name"
        if name and target is None:
            issues.append(Issue("error", where, "Choose the component type first."))
        elif target and name and str(name) not in component_names(doc, target):
            issues.append(
                Issue(
                    "error",
                    where,
                    f"'{name}' is not one of the {target} of this definition.",
                )
            )
    return issues


def _exact_multiple(value, step) -> bool:
    try:
        return Decimal(str(value)) % Decimal(str(step)) == 0
    except InvalidOperation, ValueError:
        return False


def _empty_values(value, where: str) -> list[Issue]:
    issues = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            location = f"{where}/{key}" if where else str(key)
            if item is None or (isinstance(item, str) and not item.strip()):
                issues.append(Issue("error", location, "Remove empty values."))
            else:
                issues += _empty_values(item, location)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            issues += _empty_values(item, f"{where}/{index}")
    return issues


def errors(issues: Iterable[Issue]) -> tuple[Issue, ...]:
    return tuple(issue for issue in issues if issue.level == "error")


# -- local folder ----------------------------------------------------------------


@dataclass(frozen=True)
class TypeFile:
    manufacturer: str
    path: Path

    @property
    def name(self) -> str:
        return self.path.stem


class LocalTypeStore:
    """Definitions under ``<root>/device-types/<Manufacturer>/``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @property
    def folder(self) -> Path:
        return self.root / DEVICE_TYPES

    def files(self) -> tuple[TypeFile, ...]:
        if not self.folder.is_dir():
            return ()
        result = []
        for manufacturer in sorted(self.folder.iterdir(), key=lambda p: p.name.lower()):
            if not manufacturer.is_dir():
                continue
            for path in sorted(manufacturer.iterdir(), key=lambda p: p.name.lower()):
                if path.is_file() and path.suffix in SUFFIXES:
                    result.append(TypeFile(manufacturer.name, path))
        return tuple(result)

    def __iter__(self) -> Iterator[TypeFile]:
        return iter(self.files())

    def read(self, path: Path) -> CommentedMap:
        return load_yaml(self._inside(path).read_text(encoding="utf-8"))

    def path_for(self, doc: Mapping) -> Path:
        manufacturer = str(doc.get("manufacturer") or "").strip()
        stem = file_stem(doc)
        if not safe_file_name(manufacturer) or not safe_file_name(stem):
            raise DeviceTypeError(
                "Manufacturer and model or part number must be valid file names."
            )
        return self._inside(self.folder / manufacturer / f"{stem}.yaml")

    def write(self, doc: Mapping, previous: Path | None = None) -> Path:
        """Save ``doc`` under its library path; renames ``previous`` if needed."""
        target = self.path_for(doc)
        text = dump_yaml(doc)
        if previous is not None:
            previous = self._inside(previous)
        if target.exists() and target != previous:
            raise DeviceTypeError(
                f"{target.name} already exists for this manufacturer."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        tmp.replace(target)
        if previous is not None and previous != target and previous.exists():
            previous.unlink()
            if previous.parent != target.parent and not any(previous.parent.iterdir()):
                previous.parent.rmdir()
        return target

    def delete(self, path: Path) -> None:
        path = self._inside(path)
        path.unlink()
        if not any(path.parent.iterdir()):
            path.parent.rmdir()

    def _inside(self, path: Path) -> Path:
        resolved = Path(path).resolve()
        root = self.folder.resolve()
        if root != resolved and root not in resolved.parents:
            raise DeviceTypeError("The file is outside the local type folder.")
        return resolved


# -- field kinds for editors ---------------------------------------------------


@dataclass(frozen=True)
class FieldSpec:
    kind: str  # string, number, integer, boolean, enum, date, list or object
    choices: tuple[str, ...] = ()
    required: bool = False


def _resolve(node: Mapping) -> Mapping:
    """Follow ``$ref`` across the bundled schema files."""
    seen = 0
    while isinstance(node, Mapping) and "$ref" in node and seen < 10:
        seen += 1
        base, _, pointer = str(node["$ref"]).partition("#")
        schema = next(
            (s for s in _extended().values() if s.get("$id") == base),
            None,
        )
        if schema is None:
            return {}
        target: object = schema
        for part in pointer.strip("/").split("/"):
            if not part:
                continue
            target = target.get(part, {}) if isinstance(target, Mapping) else {}
        node = target if isinstance(target, Mapping) else {}
    return node


def field_spec(section: str | None, name: str) -> FieldSpec:
    """Kind and choices of a device type attribute or component column."""
    if section is None:
        schema = _extended()["devicetype.json"]
        node = schema["properties"].get(name, {})
        required = name in schema.get("required", ())
    else:
        definition = _extended()["components.json"]["definitions"][
            COMPONENT_DEFINITIONS[section]
        ]
        node = definition.get("properties", {}).get(name, {})
        required = name in definition.get("required", ())
    node = _resolve(node)
    if node.get("enum"):
        return FieldSpec("enum", tuple(str(v) for v in node["enum"]), required)
    kind = node.get("type", "string")
    if node.get("pattern") == _DATE:
        kind = "date"
    elif kind == "array":
        kind = "list"
    elif kind == "object":
        kind = "object"
    elif kind not in ("string", "number", "integer", "boolean"):
        kind = "string"
    return FieldSpec(kind, (), required)


# -- images (elevation-images, like the library) -------------------------------

IMAGES = "elevation-images"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
IMAGE_SIDES = ("front", "rear")


def image_folder(store: LocalTypeStore, manufacturer: str) -> Path:
    return store.root / IMAGES / manufacturer


def find_image(store: LocalTypeStore, manufacturer: str, slug: str, side: str):
    """The local front or rear image of a device type, if any."""
    if not manufacturer or not slug:
        return None
    folder = image_folder(store, manufacturer)
    for suffix in IMAGE_SUFFIXES:
        candidate = folder / f"{slug}.{side}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def store_image(
    store: LocalTypeStore, manufacturer: str, slug: str, side: str, source: Path
) -> Path:
    """Copy ``source`` as ``<slug>.<side>.<ext>``; replaces an older image."""
    suffix = Path(source).suffix.lower()
    if side not in IMAGE_SIDES or suffix not in IMAGE_SUFFIXES:
        raise DeviceTypeError(
            "Choose a PNG, JPEG, GIF, WebP or SVG image for the front or rear."
        )
    if not safe_file_name(manufacturer) or not slug:
        raise DeviceTypeError("Enter the manufacturer and the slug first.")
    remove_image(store, manufacturer, slug, side)
    target = image_folder(store, manufacturer) / f"{slug}.{side}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(Path(source).read_bytes())
    return target


def remove_image(store: LocalTypeStore, manufacturer: str, slug: str, side: str):
    while (found := find_image(store, manufacturer, slug, side)) is not None:
        found.unlink()


def rename_images(
    store: LocalTypeStore, old: tuple[str, str], new: tuple[str, str]
) -> None:
    """Move images when the manufacturer or slug of a definition changes."""
    if old == new or not all(old) or not all(new):
        return
    for side in IMAGE_SIDES:
        found = find_image(store, old[0], old[1], side)
        if found is None:
            continue
        target = image_folder(store, new[0]) / f"{new[1]}.{side}{found.suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        found.replace(target)
