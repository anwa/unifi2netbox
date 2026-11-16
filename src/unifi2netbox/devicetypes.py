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

import io
import json
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
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
ATTRIBUTES = (
    "manufacturer",
    "model",
    "slug",
    "part_number",
    "description",
    "u_height",
    "is_full_depth",
    "airflow",
    "weight",
    "weight_unit",
    "front_image",
    "rear_image",
    "subdevice_role",
    "is_powered",
    "comments",
)
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
)
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
    "front_image": "True if the library has a front image for this model.",
    "rear_image": "True if the library has a rear image for this model.",
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
def _validator() -> Draft202012Validator:
    schemas = _schemas()
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
    return tuple(node.get("enum", ()))


def component_columns(section: str) -> tuple[str, ...]:
    """Fields of one component section in schema order."""
    definition = COMPONENT_DEFINITIONS[section]
    props = _schemas()["components.json"]["definitions"][definition].get(
        "properties", {}
    )
    return tuple(props)


def required_columns(section: str) -> tuple[str, ...]:
    definition = COMPONENT_DEFINITIONS[section]
    node = _schemas()["components.json"]["definitions"][definition]
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
    if doc.get("weight") is not None and not doc.get("weight_unit"):
        issues.append(Issue("error", "weight_unit", "A weight needs a weight unit."))
    for field in RECOMMENDED:
        if doc.get(field) in (None, ""):
            issues.append(
                Issue("warning", field, "Recommended by the library; add it if known.")
            )
    return tuple(issues)


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
