"""Create/update/read-back of NetBox inventory items.

Used by drive bays (``disk_execute``) and SFP modules (``sfp_execute``) on
top of the shared object writer (``object_writes``): creates look for an item
of the same name on the device first and never duplicate it; interrupted
creates are looked up by name instead of retried; updates skip on drift and
PATCH only the changed fields; every write is read back. Items are never
deleted.

Rows provide ``key``, ``label``, ``name``, ``action``, ``netbox_device_id``,
``item_id``, ``desired`` and ``changes()``. Related fields (``manufacturer``)
and integer fields (``component_id``) are compared and sent by ID.
"""

from __future__ import annotations

from typing import Protocol

from unifi2netbox import object_writes
from unifi2netbox.network_execute import IpamBackend, NetworkOutcome

INVENTORY_ITEMS = "/api/dcim/inventory-items/"
CREATE_OPERATION = "create_inventory_item"
UPDATE_OPERATION = "update_inventory_item"
KIND = object_writes.ObjectKind(
    INVENTORY_ITEMS,
    "item",
    CREATE_OPERATION,
    UPDATE_OPERATION,
    frozenset({"manufacturer", "component_id"}),
)
item_value = object_writes.object_value


class ItemRow(Protocol):
    key: str
    label: str
    action: str
    netbox_device_id: str
    item_id: str
    desired: tuple[tuple[str, str], ...]

    @property
    def name(self) -> str: ...

    def changes(self) -> tuple[tuple[str, str, str], ...]: ...


def payload_value(field: str, value: str) -> object:
    return object_writes.payload_value(KIND, field, value)


def create_item(row: ItemRow, backend: IpamBackend, dry_run: bool) -> NetworkOutcome:
    return object_writes.create_object(
        row,
        KIND,
        backend,
        dry_run,
        lookup={"device_id": row.netbox_device_id, "name": row.name},
        name=row.name,
        payload={"name": row.name, **dict(row.desired)},
        extra={"device": int(row.netbox_device_id), "discovered": True},
    )


def update_item(row: ItemRow, backend: IpamBackend, dry_run: bool) -> NetworkOutcome:
    return object_writes.update_object(
        row, KIND, backend, dry_run, object_id=row.item_id, changes=row.changes()
    )


def outcome(row: ItemRow, status: str, message: str) -> NetworkOutcome:
    return object_writes.outcome(row, KIND, status, message)
