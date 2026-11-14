"""Write selected drive inventory items to NetBox with the usual safeguards.

Before each write the drive is re-read from UniFi Drive (optional) and must
still report the same hardware in its bay. Creates look for an item of the
same name first and never duplicate it; interrupted creates are looked up
by name instead of retried. Updates re-read the item and skip it when a
selected field changed since the preview, then PATCH only those fields.
Every write is read back. Dry runs run all checks. Items are never deleted.
"""

from __future__ import annotations

from collections.abc import Mapping

from unifi2netbox.disks import CREATE, DiskPlan, DiskPlanRow
from unifi2netbox.inventory import InventoryDisk
from unifi2netbox.network_execute import NETWORK_ERRORS, IpamBackend, NetworkOutcome
from unifi2netbox.write_execute import AMBIGUOUS_CREATE_ERRORS

INVENTORY_ITEMS = "/api/dcim/inventory-items/"
CREATE_OPERATION = "create_inventory_item"
UPDATE_OPERATION = "update_inventory_item"
HARDWARE = ("model", "serial", "firmware", "kind", "size_bytes")


def execute_disk_plan(
    plan: DiskPlan | None,
    backend: IpamBackend,
    *,
    dry_run: bool = False,
    source_disks: Mapping[tuple[str, str], InventoryDisk] | None = None,
    source_error: str = "",
) -> tuple[NetworkOutcome, ...]:
    if plan is None:
        return ()
    outcomes = []
    for row in plan.selected_rows():
        if source_error:
            outcomes.append(
                _outcome(
                    row,
                    "skipped",
                    f"UniFi could not be re-read before writing ({source_error}); "
                    "nothing was written.",
                )
            )
        elif source_disks is not None and not same_hardware(
            row.disk, source_disks.get((row.unifi_device_id, row.disk.slot))
        ):
            outcomes.append(
                _outcome(
                    row, "skipped", "UniFi Drive reports other hardware now; refresh."
                )
            )
        elif row.action == CREATE:
            outcomes.append(_create(row, backend, dry_run))
        else:
            outcomes.append(_update(row, backend, dry_run))
    return tuple(outcomes)


def same_hardware(planned: InventoryDisk, fresh: InventoryDisk | None) -> bool:
    return fresh is not None and all(
        getattr(planned, field) == getattr(fresh, field) for field in HARDWARE
    )


def _create(row: DiskPlanRow, backend: IpamBackend, dry_run: bool) -> NetworkOutcome:
    try:
        existing = backend.find_ids(
            INVENTORY_ITEMS, device_id=row.netbox_device_id, name=row.name
        )
    except NETWORK_ERRORS as error:
        return _outcome(row, "failed", f"NetBox lookup failed: {error}")
    if existing:
        return _outcome(
            row,
            "skipped",
            f"NetBox got an item named {row.name} since the preview; refresh.",
        )
    if dry_run:
        return _outcome(row, "skipped", "Dry-run mode: not created.")
    payload: dict[str, object] = {
        "device": int(row.netbox_device_id),
        "name": row.name,
        "discovered": True,
    }
    payload.update({field: value for field, value in row.desired if value})
    try:
        item_id = backend.create_object(INVENTORY_ITEMS, payload)
        message = "Created in NetBox."
    except AMBIGUOUS_CREATE_ERRORS as error:
        try:
            found = backend.find_ids(
                INVENTORY_ITEMS, device_id=row.netbox_device_id, name=row.name
            )
        except NETWORK_ERRORS as lookup_error:
            return _outcome(
                row,
                "failed",
                f"Create was interrupted ({error}) and the lookup failed "
                f"({lookup_error}). Check NetBox before retrying.",
            )
        if len(found) != 1:
            return _outcome(
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
        return _outcome(row, "failed", str(error))
    fields = {field: value for field, value in row.desired if value}
    verification, detail = _verify(backend, item_id, fields | {"name": row.name})
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


def _update(row: DiskPlanRow, backend: IpamBackend, dry_run: bool) -> NetworkOutcome:
    path = f"{INVENTORY_ITEMS}{row.item_id}/"
    changes = row.changes()
    try:
        current = backend.read_object(path)
    except NETWORK_ERRORS as error:
        return _outcome(row, "failed", str(error))
    if current is None:
        return _outcome(row, "skipped", "The NetBox item no longer exists; refresh.")
    drifted = [f for f, before, _ in changes if _text(current.get(f)) != before]
    if drifted:
        return _outcome(
            row,
            "skipped",
            f"NetBox item changed since the preview ({', '.join(drifted)}); refresh.",
        )
    if dry_run:
        return _outcome(row, "skipped", "Dry-run mode: not updated.")
    payload = {field: desired for field, _, desired in changes}
    try:
        backend.update_object(path, payload)
    except NETWORK_ERRORS as error:
        return _outcome(row, "failed", str(error))
    verification, detail = _verify(backend, row.item_id, payload)
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


def _verify(
    backend: IpamBackend, item_id: str, expected: Mapping[str, object]
) -> tuple[str, str]:
    try:
        item = backend.read_object(f"{INVENTORY_ITEMS}{item_id}/")
    except NETWORK_ERRORS as error:
        return "unverified", f"Read-back failed: {error}"
    if item is None:
        return "unverified", "The item was not found after the write."
    mismatches = [f for f, value in expected.items() if _text(item.get(f)) != value]
    if mismatches:
        return "mismatch", f"NetBox differs in {', '.join(mismatches)}."
    return "verified", "NetBox matches the written values."


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _outcome(row: DiskPlanRow, status: str, message: str) -> NetworkOutcome:
    operation = CREATE_OPERATION if row.action == CREATE else UPDATE_OPERATION
    return NetworkOutcome(row.key, operation, row.label, status, message)
