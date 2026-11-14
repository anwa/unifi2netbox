"""Plan NetBox inventory items for the drive bays of a matched UNAS.

Each populated drive bay becomes the inventory item ``Disk <slot>`` of the
NetBox device the UNAS is matched to. Its part ID is the drive model, its
serial the drive serial, its description type, size and firmware. Existing
items are found by name on that device:

- no item: create (preselected),
- item with different values: update the differing fields (preselected);
  an empty UniFi value never clears a NetBox value,
- item with equal values: in sync,
- several items with the same name: conflict, never written,
- empty bay with an item: reference only; items are never deleted.

Operational values (state, temperature, health, pool) are never written.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from unifi2netbox.inventory import InventoryDisk, InventoryItem

CREATE = "create"
UPDATE = "update"
IN_SYNC = "in_sync"
CONFLICT = "conflict"
REFERENCE = "reference"

PART_ID = "part_id"
SERIAL = "serial"
DESCRIPTION = "description"
FIELDS = (PART_ID, SERIAL, DESCRIPTION)


@dataclass(frozen=True)
class DiskPlanRow:
    key: str
    unifi_device_id: str
    netbox_device_id: str
    device_name: str
    disk: InventoryDisk
    action: str
    item_id: str = ""
    current: tuple[tuple[str, str], ...] = ()
    desired: tuple[tuple[str, str], ...] = ()
    selected: bool = False
    notes: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return disk_name(self.disk.slot)

    @property
    def label(self) -> str:
        return f"{self.device_name} {self.name}"

    @property
    def selectable(self) -> bool:
        return self.action in (CREATE, UPDATE)

    def changes(self) -> tuple[tuple[str, str, str], ...]:
        """(field, current, desired) for fields that a write would change."""
        current = dict(self.current)
        return tuple(
            (field, current.get(field, ""), value)
            for field, value in self.desired
            if value and value != current.get(field, "")
        )


@dataclass(frozen=True)
class DiskPlan:
    rows: tuple[DiskPlanRow, ...] = ()
    blocker: str = ""

    def selected_rows(self) -> tuple[DiskPlanRow, ...]:
        return tuple(row for row in self.rows if row.selected and row.selectable)

    @property
    def operation_count(self) -> int:
        return len(self.selected_rows())

    def rows_for(self, unifi_device_id: str) -> tuple[DiskPlanRow, ...]:
        return tuple(r for r in self.rows if r.unifi_device_id == unifi_device_id)


def disk_name(slot: str) -> str:
    return f"Disk {slot}"


def describe(disk: InventoryDisk) -> str:
    """Hardware description: type, size and firmware (never operational data)."""
    parts = [disk.kind] if disk.kind else []
    if disk.size_bytes:
        parts.append(f"{disk.size_bytes / 1e12:.1f} TB")
    text = " ".join(parts)
    if disk.firmware:
        text = (
            f"{text}, firmware {disk.firmware}" if text else f"firmware {disk.firmware}"
        )
    return text


def desired_values(disk: InventoryDisk) -> tuple[tuple[str, str], ...]:
    return ((PART_ID, disk.model), (SERIAL, disk.serial), (DESCRIPTION, describe(disk)))


def item_values(item: InventoryItem) -> tuple[tuple[str, str], ...]:
    return (
        (PART_ID, item.part_id),
        (SERIAL, item.serial),
        (DESCRIPTION, item.description),
    )


def build_disk_plan(
    disks: Iterable[InventoryDisk],
    netbox_ids: Mapping[str, str],
    device_names: Mapping[str, str],
    items: Iterable[InventoryItem],
    *,
    item_error: str = "",
) -> DiskPlan:
    """Rows for drive bays of UNAS devices matched to NetBox devices.

    ``disks`` carry the UniFi device ID used in ``netbox_ids`` (for example
    ``drive:<id>``); ``netbox_ids`` maps matched UniFi IDs to NetBox IDs.
    """
    disks = tuple(disks)
    if not disks:
        return DiskPlan()
    unmatched = sorted(
        {device_names.get(d.device_id, d.device_id) for d in disks}
        - {
            device_names.get(d.device_id, d.device_id)
            for d in disks
            if d.device_id in netbox_ids
        }
    )
    if item_error:
        return DiskPlan(blocker=item_error)
    items = tuple(items)
    rows: list[DiskPlanRow] = []
    for disk in disks:
        netbox_id = netbox_ids.get(disk.device_id)
        if not netbox_id:
            continue
        rows.extend(_row(disk, netbox_id, device_names.get(disk.device_id, ""), items))
    order = {CREATE: 0, UPDATE: 1, CONFLICT: 2, IN_SYNC: 3, REFERENCE: 4}
    rows.sort(key=lambda row: (order[row.action], row.device_name, _slot(row)))
    blocker = (
        f"Create {', '.join(unmatched)} in NetBox and refresh to plan its drives."
        if unmatched and not rows
        else ""
    )
    return DiskPlan(rows=tuple(rows), blocker=blocker)


def select_disk(plan: DiskPlan, key: str, selected: bool) -> DiskPlan:
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
    disk: InventoryDisk, netbox_id: str, device_name: str, items: tuple
) -> list[DiskPlanRow]:
    name = disk_name(disk.slot)
    same = [i for i in items if i.device_id == netbox_id and i.name == name]
    key = f"disk:{disk.device_id}:{disk.slot}"
    base = DiskPlanRow(key, disk.device_id, netbox_id, device_name or "UNAS", disk, "")
    if not disk.model:
        if not same:
            return []
        return [
            replace(
                base,
                action=REFERENCE,
                item_id=same[0].source_id,
                current=item_values(same[0]),
                notes=(
                    "The bay is empty in UniFi Drive; the NetBox item is kept "
                    "(never deleted).",
                ),
            )
        ]
    desired = desired_values(disk)
    if len(same) > 1:
        return [
            replace(
                base,
                action=CONFLICT,
                desired=desired,
                notes=(f"NetBox has {len(same)} items named {name}; resolve first.",),
            )
        ]
    if not same:
        return [replace(base, action=CREATE, desired=desired, selected=True)]
    item = same[0]
    row = replace(
        base, item_id=item.source_id, current=item_values(item), desired=desired
    )
    if not row.changes():
        return [replace(row, action=IN_SYNC)]
    notes = ()
    if item.serial and disk.serial and item.serial != disk.serial:
        notes = ("The serial differs: the drive in this bay was probably replaced.",)
    return [replace(row, action=UPDATE, selected=True, notes=notes)]


def _slot(row: DiskPlanRow) -> tuple[int, str]:
    slot = row.disk.slot
    return (int(slot), "") if slot.isdigit() else (0, slot)
