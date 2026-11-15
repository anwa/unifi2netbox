"""Plan NetBox inventory items for SFP modules of matched devices (M11).

Each SFP module that UniFi reports in a port becomes the inventory item
``Transceiver <interface>`` of the matched NetBox device, linked to the paired
interface (``component_type`` ``dcim.interface``). Part ID, serial and
description (compliance and revision) come from UniFi; the manufacturer is
set only when an existing NetBox manufacturer matches the module vendor
(``UBNT`` and ``Ubiquiti Inc.`` match ``Ubiquiti``); none is created.

Like drive items: missing items are created, differing ones updated (an empty
UniFi value never clears NetBox), equal ones are in sync, duplicate names are
conflicts, and an item whose port has no module any more is kept (never
deleted). Ports without a paired NetBox interface only get a note.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from unifi2netbox.details import InventorySfp
from unifi2netbox.interface_plan import DevicePair
from unifi2netbox.inventory import (
    InventoryInterface,
    InventoryItem,
    InventoryManufacturer,
    InventoryPort,
)
from unifi2netbox.ports import match_ports

CREATE = "create"
UPDATE = "update"
IN_SYNC = "in_sync"
CONFLICT = "conflict"
REFERENCE = "reference"
NOTE = "note"

PREFIX = "Transceiver "
FIELDS = (
    "part_id",
    "serial",
    "description",
    "manufacturer",
    "component_type",
    "component_id",
)
_VENDOR_ALIASES = {"ubnt": "ubiquiti"}
_SUFFIXES = re.compile(r"(inc|ltd|llc|corp|corporation|co|gmbh|oem)$")


@dataclass(frozen=True)
class SfpPlanRow:
    key: str
    unifi_device_id: str
    netbox_device_id: str
    device_name: str
    port_idx: int
    interface_name: str
    action: str
    sfp: InventorySfp | None = None
    item_id: str = ""
    current: tuple[tuple[str, str], ...] = ()
    desired: tuple[tuple[str, str], ...] = ()
    selected: bool = False
    notes: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return f"{PREFIX}{self.interface_name}"

    @property
    def label(self) -> str:
        return f"{self.device_name} {self.name}"

    @property
    def selectable(self) -> bool:
        return self.action in (CREATE, UPDATE)

    def changes(self) -> tuple[tuple[str, str, str], ...]:
        current = dict(self.current)
        return tuple(
            (field, current.get(field, ""), value)
            for field, value in self.desired
            if value and value != current.get(field, "")
        )


@dataclass(frozen=True)
class SfpPlan:
    rows: tuple[SfpPlanRow, ...] = ()
    blocker: str = ""

    def selected_rows(self) -> tuple[SfpPlanRow, ...]:
        return tuple(row for row in self.rows if row.selected and row.selectable)

    @property
    def operation_count(self) -> int:
        return len(self.selected_rows())

    def rows_for(self, netbox_device_id: str) -> tuple[SfpPlanRow, ...]:
        return tuple(r for r in self.rows if r.netbox_device_id == netbox_device_id)


def vendor_key(name: str) -> str:
    text = "".join(ch for ch in name.lower() if ch.isalnum())
    text = _SUFFIXES.sub("", text)
    return _VENDOR_ALIASES.get(text, text)


def describe(sfp: InventorySfp) -> str:
    parts = [sfp.compliance] if sfp.compliance else []
    if sfp.revision:
        parts.append(f"rev {sfp.revision}")
    return ", ".join(parts)


def build_sfp_plan(
    pairs: Iterable[DevicePair],
    sfps: Iterable[InventorySfp],
    ports: Iterable[InventoryPort],
    interfaces: Iterable[InventoryInterface],
    items: Iterable[InventoryItem],
    manufacturers: Iterable[InventoryManufacturer],
    *,
    item_error: str = "",
) -> SfpPlan:
    sfps = tuple(sfps)
    if not sfps:
        return SfpPlan()
    if item_error:
        return SfpPlan(blocker=item_error)
    ports = tuple(ports)
    interfaces = tuple(interfaces)
    items = tuple(items)
    vendors: dict[str, list[str]] = {}
    for manufacturer in manufacturers:
        vendors.setdefault(vendor_key(manufacturer.name), []).append(
            manufacturer.source_id
        )
    rows: list[SfpPlanRow] = []
    for pair in pairs:
        modules = {s.port_idx: s for s in sfps if s.device_id == pair.unifi_id}
        device_items = [i for i in items if i.device_id == pair.netbox_id]
        if not modules and not device_items:
            continue
        device_ports = [p for p in ports if p.device_id == pair.unifi_id]
        device_interfaces = [i for i in interfaces if i.device_id == pair.netbox_id]
        paired = {
            m.port.idx: m.interface
            for m in match_ports(device_ports, device_interfaces)
            if m.port is not None and m.interface is not None
        }
        used: set[str] = set()
        for idx, sfp in sorted(modules.items()):
            interface = paired.get(idx)
            base = SfpPlanRow(
                key=f"sfp:{pair.unifi_id}:{idx}",
                unifi_device_id=pair.unifi_id,
                netbox_device_id=pair.netbox_id,
                device_name=pair.device_name,
                port_idx=idx,
                interface_name=interface.name if interface else f"port {idx}",
                action=NOTE,
                sfp=sfp,
            )
            if interface is None:
                rows.append(
                    replace(
                        base,
                        notes=(
                            f"UniFi port {idx} has no paired NetBox interface; the "
                            "module is not written.",
                        ),
                    )
                )
                continue
            used.add(base.name)
            rows.append(_row(base, sfp, interface, device_items, vendors))
        for item in device_items:
            if item.name.startswith(PREFIX) and item.name not in used:
                rows.append(
                    SfpPlanRow(
                        key=f"sfp-item:{item.source_id}",
                        unifi_device_id=pair.unifi_id,
                        netbox_device_id=pair.netbox_id,
                        device_name=pair.device_name,
                        port_idx=0,
                        interface_name=item.name[len(PREFIX) :],
                        action=REFERENCE,
                        item_id=item.source_id,
                        notes=(
                            "UniFi reports no module here now; the NetBox item is "
                            "kept (never deleted).",
                        ),
                    )
                )
    order = {CREATE: 0, UPDATE: 1, CONFLICT: 2, NOTE: 3, IN_SYNC: 4, REFERENCE: 5}
    rows.sort(key=lambda row: (order[row.action], row.device_name, row.port_idx))
    return SfpPlan(rows=tuple(rows))


def select_sfp(plan: SfpPlan, key: str, selected: bool) -> SfpPlan:
    return replace(
        plan,
        rows=tuple(
            replace(row, selected=selected)
            if row.key == key and row.selectable
            else row
            for row in plan.rows
        ),
    )


def _row(
    base: SfpPlanRow,
    sfp: InventorySfp,
    interface: InventoryInterface,
    device_items: list[InventoryItem],
    vendors: Mapping[str, list[str]],
) -> SfpPlanRow:
    notes: list[str] = []
    matches = vendors.get(vendor_key(sfp.vendor), []) if sfp.vendor else []
    manufacturer = matches[0] if len(matches) == 1 else ""
    if sfp.vendor and not manufacturer:
        notes.append(
            f"No single NetBox manufacturer matches '{sfp.vendor}'; the item has "
            "no manufacturer (none is created)."
        )
    desired = (
        ("part_id", sfp.part),
        ("serial", sfp.serial),
        ("description", describe(sfp)),
        ("manufacturer", manufacturer),
        ("component_type", "dcim.interface"),
        ("component_id", interface.source_id),
    )
    same = [i for i in device_items if i.name == base.name]
    if len(same) > 1:
        return replace(
            base,
            action=CONFLICT,
            desired=desired,
            notes=(f"NetBox has {len(same)} items named {base.name}; resolve first.",),
        )
    if not same:
        return replace(
            base, action=CREATE, desired=desired, selected=True, notes=tuple(notes)
        )
    item = same[0]
    current = (
        ("part_id", item.part_id),
        ("serial", item.serial),
        ("description", item.description),
        ("manufacturer", item.manufacturer),
        ("component_type", item.component_type),
        ("component_id", item.component_id),
    )
    row = replace(base, item_id=item.source_id, current=current, desired=desired)
    if not row.changes():
        return replace(row, action=IN_SYNC, notes=tuple(notes))
    if item.serial and sfp.serial and item.serial != sfp.serial:
        notes.append("The serial differs: the module in this port was replaced.")
    return replace(row, action=UPDATE, selected=True, notes=tuple(notes))
