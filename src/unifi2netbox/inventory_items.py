"""Shared create/update/read-back of NetBox inventory items.

Used by drive bays (``disk_execute``) and SFP modules (``sfp_execute``).
Creates look for an item of the same name on the device first and never
duplicate it; interrupted creates are looked up by name instead of retried.
Updates re-read the item, skip it when a planned field changed since the
preview and PATCH only the changed fields. Every write is read back. Dry runs
run all checks. Items are never deleted.

Rows provide ``key``, ``label``, ``name``, ``action``, ``netbox_device_id``,
``item_id``, ``desired`` and ``changes()``. Related fields (``manufacturer``)
and integer fields (``component_id``) are compared and sent by ID.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from unifi2netbox.network_execute import NETWORK_ERRORS, IpamBackend, NetworkOutcome
from unifi2netbox.write_execute import AMBIGUOUS_CREATE_ERRORS

INVENTORY_ITEMS = "/api/dcim/inventory-items/"
CREATE_OPERATION = "create_inventory_item"
UPDATE_OPERATION = "update_inventory_item"
_ID_FIELDS = frozenset({"manufacturer", "component_id"})


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


def item_value(item: Mapping[str, object], field: str) -> str:
    """Comparable text of one NetBox inventory-item field."""
    value = item.get(field)
    if isinstance(value, Mapping):
        value = value.get("id")
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    return value.strip() if isinstance(value, str) else ""


def payload_value(field: str, value: str) -> object:
    return int(value) if field in _ID_FIELDS and value.isdigit() else value


def create_item(row: ItemRow, backend: IpamBackend, dry_run: bool) -> NetworkOutcome:
    try:
        existing = backend.find_ids(
            INVENTORY_ITEMS, device_id=row.netbox_device_id, name=row.name
        )
    except NETWORK_ERRORS as error:
        return outcome(row, "failed", f"NetBox lookup failed: {error}")
    if existing:
        return outcome(
            row,
            "skipped",
            f"NetBox got an item named {row.name} since the preview; refresh.",
        )
    if dry_run:
        return outcome(row, "skipped", "Dry-run mode: not created.")
    fields = {field: value for field, value in row.desired if value}
    payload: dict[str, object] = {
        "device": int(row.netbox_device_id),
        "name": row.name,
        "discovered": True,
    }
    payload.update({f: payload_value(f, v) for f, v in fields.items()})
    try:
        item_id = backend.create_object(INVENTORY_ITEMS, payload)
        message = "Created in NetBox."
    except AMBIGUOUS_CREATE_ERRORS as error:
        try:
            found = backend.find_ids(
                INVENTORY_ITEMS, device_id=row.netbox_device_id, name=row.name
            )
        except NETWORK_ERRORS as lookup_error:
            return outcome(
                row,
                "failed",
                f"Create was interrupted ({error}) and the lookup failed "
                f"({lookup_error}). Check NetBox before retrying.",
            )
        if len(found) != 1:
            return outcome(
                row,
                "failed",
                f"Create was interrupted ({error}); NetBox shows no single item. "
                "Refresh and review before retrying.",
            )
        item_id, message = (
            found[0],
            f"Create was interrupted ({error}), but NetBox now has it.",
        )
    except NETWORK_ERRORS as error:
        return outcome(row, "failed", str(error))
    verification, detail = verify(backend, item_id, fields | {"name": row.name})
    return NetworkOutcome(
        row.key,
        CREATE_OPERATION,
        row.label,
        "success",
        message,
        str(item_id),
        verification,
        detail,
    )


def update_item(row: ItemRow, backend: IpamBackend, dry_run: bool) -> NetworkOutcome:
    path = f"{INVENTORY_ITEMS}{row.item_id}/"
    changes = row.changes()
    try:
        current = backend.read_object(path)
    except NETWORK_ERRORS as error:
        return outcome(row, "failed", str(error))
    if current is None:
        return outcome(row, "skipped", "The NetBox item no longer exists; refresh.")
    drifted = [f for f, before, _ in changes if item_value(current, f) != before]
    if drifted:
        return outcome(
            row,
            "skipped",
            f"NetBox item changed since the preview ({', '.join(drifted)}); refresh.",
        )
    if dry_run:
        return outcome(row, "skipped", "Dry-run mode: not updated.")
    desired = {field: value for field, _, value in changes}
    payload = {f: payload_value(f, v) for f, v in desired.items()}
    try:
        backend.update_object(path, payload)
    except NETWORK_ERRORS as error:
        return outcome(row, "failed", str(error))
    verification, detail = verify(backend, row.item_id, desired)
    return NetworkOutcome(
        row.key,
        UPDATE_OPERATION,
        row.label,
        "success",
        f"Updated in NetBox ({', '.join(payload)}).",
        row.item_id,
        verification,
        detail,
    )


def verify(
    backend: IpamBackend, item_id: str, expected: Mapping[str, str]
) -> tuple[str, str]:
    try:
        item = backend.read_object(f"{INVENTORY_ITEMS}{item_id}/")
    except NETWORK_ERRORS as error:
        return "unverified", f"Read-back failed: {error}"
    if item is None:
        return "unverified", "The item was not found after the write."
    mismatches = [f for f, value in expected.items() if item_value(item, f) != value]
    if mismatches:
        return "mismatch", f"NetBox differs in {', '.join(mismatches)}."
    return "verified", "NetBox matches the written values."


def outcome(row: ItemRow, status: str, message: str) -> NetworkOutcome:
    operation = CREATE_OPERATION if row.action == "create" else UPDATE_OPERATION
    return NetworkOutcome(row.key, operation, row.label, status, message)
