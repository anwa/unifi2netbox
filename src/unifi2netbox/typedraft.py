"""Draft a device type definition from UniFi data and techspecs (Qt-free).

The UniFi ports of the device are authoritative for interfaces; without them
the techspecs port layout is used. Names follow the library's UniFi files
(``Port N`` for copper, ``SFP+ N`` and so on per connector kind; ``eth0`` for
single-port devices without UniFi port data). Differences between both
sources become notes for the editor.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from ruamel.yaml.comments import CommentedMap

from unifi2netbox.devicetypes import device_slug
from unifi2netbox.interface_plan import POE_TYPES
from unifi2netbox.inventory import InventoryDevice, InventoryPort
from unifi2netbox.techspecs import SpecPorts, TechSpec

# Connector kind -> interface name prefix.
NAME_PREFIX = {
    "RJ45": "Port",
    "SFP": "SFP",
    "SFPPLUS": "SFP+",
    "SFP28": "SFP28",
    "QSFP28": "QSFP28",
    "QSFP": "QSFP",
}
_COPPER = {
    10: "10base-t",
    100: "100base-tx",
    1000: "1000base-t",
    2500: "2.5gbase-t",
    5000: "5gbase-t",
    10000: "10gbase-t",
}
_OPTICAL = {
    "SFP": "1000base-x-sfp",
    "SFPPLUS": "10gbase-x-sfpp",
    "SFP28": "25gbase-x-sfp28",
    "QSFP28": "100gbase-x-qsfp28",
    "QSFP": "40gbase-x-qsfpp",
}


def interface_type(connector: str, speed_mbps: int) -> str:
    """NetBox interface type for a UniFi connector and maximum speed."""
    kind = connector.upper()
    if kind == "RJ45":
        if speed_mbps in _COPPER:
            return _COPPER[speed_mbps]
        return "1000base-t" if not speed_mbps else "other"
    return _OPTICAL.get(kind, "other")


def draft_from_unifi(
    device: InventoryDevice,
    ports: Iterable[InventoryPort] = (),
    spec: TechSpec | None = None,
) -> tuple[CommentedMap, tuple[str, ...]]:
    """A definition for ``device`` plus notes about guesses and differences."""
    notes: list[str] = []
    ports = sorted(ports, key=lambda p: p.idx)
    manufacturer = device.manufacturer.strip()
    if not manufacturer:
        notes.append("UniFi reports no manufacturer: enter it before saving.")
    model = (spec.title if spec else "") or device.model.strip() or device.name
    part_number = (spec.part_number if spec else "") or "-".join(device.model.split())
    doc = CommentedMap()
    doc["manufacturer"] = manufacturer
    doc["model"] = model
    doc["slug"] = (
        device_slug(manufacturer, part_number or model) if manufacturer else ""
    )
    if part_number:
        doc["part_number"] = part_number
    doc["u_height"] = (
        int(spec.u_height)
        if spec and spec.u_height.is_integer()
        else (spec.u_height if spec else 0)
    )
    doc["is_full_depth"] = False
    if spec and spec.weight is not None:
        doc["weight"] = spec.weight
        doc["weight_unit"] = spec.weight_unit
    comments = []
    if spec:
        if spec.dimensions:
            comments.append(f"Dimensions: {spec.dimensions}")
        comments.append(f"[{spec.title} Techspecs]({_canonical(spec.url)})")
    else:
        notes.append("No techspecs data: check height, weight and airflow by hand.")
    if comments:
        doc["comments"] = "\n\n".join(comments)
    if spec is None or not spec.rack_mount:
        notes.append("Airflow is not known; add it if the device has fans.")

    if ports:
        doc["interfaces"] = _from_unifi_ports(ports)
        if spec and spec.ports:
            unifi = Counter(p.connector.upper() for p in ports)
            specs = Counter()
            for item in spec.ports:
                specs[item.kind] += item.count
            if unifi != specs:
                notes.append(
                    "UniFi reports "
                    + _describe(unifi)
                    + ", techspecs lists "
                    + _describe(specs)
                    + "; interfaces follow UniFi."
                )
    elif spec and spec.ports:
        doc["interfaces"] = _from_spec_ports(spec.ports, spec)
        notes.append("Interfaces come from techspecs; UniFi reports no ports.")
    else:
        notes.append("No port data: add the interfaces by hand.")
    return doc, tuple(notes)


def _from_unifi_ports(ports: list[InventoryPort]) -> list[CommentedMap]:
    numbers: Counter[str] = Counter()
    result = []
    for port in ports:
        kind = port.connector.upper()
        numbers[kind] += 1
        item = CommentedMap()
        item["name"] = f"{NAME_PREFIX.get(kind, kind.title())} {numbers[kind]}"
        item["type"] = interface_type(kind, port.max_speed_mbps)
        if port.poe_type in POE_TYPES:
            item["poe_mode"] = "pse"
            item["poe_type"] = POE_TYPES[port.poe_type]
        result.append(item)
    return result


def _from_spec_ports(
    ports: tuple[SpecPorts, ...], spec: TechSpec
) -> list[CommentedMap]:
    total = sum(p.count for p in ports)
    result = []
    index = 0
    numbers: Counter[str] = Counter()
    for group in ports:
        for _ in range(group.count):
            item = CommentedMap()
            if total == 1 or group.kind == "RJ45" and not spec.rack_mount:
                item["name"] = f"eth{index}"
            else:
                numbers[group.kind] += 1
                prefix = NAME_PREFIX.get(group.kind, group.kind)
                item["name"] = f"{prefix} {numbers[group.kind]}"
            item["type"] = interface_type(group.kind, group.speed_mbps)
            if index == 0 and spec.poe_powered:
                item["poe_mode"] = "pd"
                if spec.poe_type:
                    item["poe_type"] = spec.poe_type
            result.append(item)
            index += 1
    return result


def _describe(counts: Counter) -> str:
    return ", ".join(
        f"{count} {NAME_PREFIX.get(kind, kind)}"
        for kind, count in sorted(counts.items())
    )


def _canonical(url: str) -> str:
    """Drop the region query (``?s=eu``) from techspecs links."""
    return url.split("?", 1)[0]


def merge_spec(doc: CommentedMap, spec: TechSpec) -> tuple[str, ...]:
    """Fill gaps in ``doc`` from techspecs; never overwrite entered values."""
    notes: list[str] = []
    filled: list[str] = []
    if not doc.get("part_number") and spec.part_number:
        doc["part_number"] = spec.part_number
        filled.append("part number")
    if not doc.get("model"):
        doc["model"] = spec.title
        filled.append("model")
    if not doc.get("u_height") and spec.u_height:
        doc["u_height"] = (
            int(spec.u_height) if spec.u_height.is_integer() else spec.u_height
        )
        filled.append("rack height")
    if doc.get("weight") is None and spec.weight is not None:
        doc["weight"] = spec.weight
        doc["weight_unit"] = spec.weight_unit
        filled.append("weight")
    link = _canonical(spec.url)
    comments = str(doc.get("comments") or "")
    if link not in comments:
        line = f"[{spec.title} Techspecs]({link})"
        doc["comments"] = f"{comments.rstrip()}\n\n{line}" if comments.strip() else line
        filled.append("techspecs link")
    if not doc.get("interfaces") and spec.ports:
        doc["interfaces"] = _from_spec_ports(spec.ports, spec)
        filled.append("interfaces")
    notes.append(
        f"Filled from techspecs: {', '.join(filled)}."
        if filled
        else "techspecs had nothing to add; existing values were kept."
    )
    return tuple(notes)
