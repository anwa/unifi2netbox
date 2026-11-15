"""Write selected drive inventory items to NetBox with the usual safeguards.

Before each write the drive is re-read from UniFi Drive (optional) and must
still report the same hardware in its bay. Creating, updating, reconciling
interrupted creates and read-back are shared with SFP modules in
``inventory_items``. Items are never deleted.
"""

from __future__ import annotations

from collections.abc import Mapping

from unifi2netbox.disks import CREATE, DiskPlan
from unifi2netbox.inventory import InventoryDisk
from unifi2netbox.inventory_items import (
    CREATE_OPERATION,
    INVENTORY_ITEMS,
    UPDATE_OPERATION,
    create_item,
    outcome,
    update_item,
)
from unifi2netbox.network_execute import IpamBackend, NetworkOutcome

__all__ = [
    "CREATE_OPERATION",
    "INVENTORY_ITEMS",
    "UPDATE_OPERATION",
    "execute_disk_plan",
    "same_hardware",
]

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
                outcome(
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
                outcome(
                    row, "skipped", "UniFi Drive reports other hardware now; refresh."
                )
            )
        elif row.action == CREATE:
            outcomes.append(create_item(row, backend, dry_run))
        else:
            outcomes.append(update_item(row, backend, dry_run))
    return tuple(outcomes)


def same_hardware(planned: InventoryDisk, fresh: InventoryDisk | None) -> bool:
    return fresh is not None and all(
        getattr(planned, field) == getattr(fresh, field) for field in HARDWARE
    )
