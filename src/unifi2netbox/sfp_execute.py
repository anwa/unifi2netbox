"""Write selected SFP-module inventory items to NetBox.

Before each write UniFi is re-read: the port must still hold a module with
the same vendor, part and serial. The writes themselves (no duplicates,
interrupted creates looked up, drift skip, read-back, dry run) are shared
with drive items in ``inventory_items``. Items are never deleted.
"""

from __future__ import annotations

from collections.abc import Mapping

from unifi2netbox.details import InventorySfp
from unifi2netbox.inventory_items import create_item, outcome, update_item
from unifi2netbox.network_execute import IpamBackend, NetworkOutcome
from unifi2netbox.sfp import CREATE, SfpPlan

MODULE = ("vendor", "part", "serial")


def execute_sfp_plan(
    plan: SfpPlan | None,
    backend: IpamBackend,
    *,
    dry_run: bool = False,
    source_sfps: Mapping[tuple[str, int], InventorySfp] | None = None,
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
        elif source_sfps is not None and not same_module(
            row.sfp, source_sfps.get((row.unifi_device_id, row.port_idx))
        ):
            outcomes.append(
                outcome(row, "skipped", "UniFi reports another module now; refresh.")
            )
        elif row.action == CREATE:
            outcomes.append(create_item(row, backend, dry_run))
        else:
            outcomes.append(update_item(row, backend, dry_run))
    return tuple(outcomes)


def same_module(planned: InventorySfp | None, fresh: InventorySfp | None) -> bool:
    return (
        planned is not None
        and fresh is not None
        and all(getattr(planned, f) == getattr(fresh, f) for f in MODULE)
    )
