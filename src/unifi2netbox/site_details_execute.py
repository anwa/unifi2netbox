"""Write selected wireless LANs, IP ranges and reserved IPs to NetBox.

Before each write UniFi is re-read: the WLAN, DHCP range or reservation must
still carry the planned values, otherwise the row is skipped. The writes use
the shared object writer (no duplicates, interrupted creates looked up,
drift skip, read-back, dry run). Nothing is ever deleted.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from unifi2netbox.details import InventoryDhcpRange, InventoryReservation, InventoryWlan
from unifi2netbox.network_execute import IpamBackend, NetworkOutcome
from unifi2netbox.object_writes import (
    ObjectKind,
    create_object,
    outcome,
    update_object,
)
from unifi2netbox.site_details import (
    CREATE,
    RANGE,
    RESERVATION,
    WLAN,
    SiteDetailPlan,
    SiteDetailRow,
)

KINDS = {
    WLAN: ObjectKind(
        "/api/wireless/wireless-lans/",
        "wireless LAN",
        "create_wireless_lan",
        "update_wireless_lan",
        frozenset({"vlan", "scope_id"}),
    ),
    RANGE: ObjectKind(
        "/api/ipam/ip-ranges/", "IP range", "create_ip_range", "update_ip_range"
    ),
    RESERVATION: ObjectKind(
        "/api/ipam/ip-addresses/",
        "IP address",
        "create_reserved_ip",
        "update_reserved_ip",
    ),
}


def execute_site_detail_plan(
    plan: SiteDetailPlan | None,
    backend: IpamBackend,
    *,
    kinds: Iterable[str] = (),
    dry_run: bool = False,
    source_items: Mapping[tuple[str, str], object] | None = None,
    source_error: str = "",
) -> tuple[NetworkOutcome, ...]:
    """``source_items`` maps (kind, source key) to freshly read UniFi values."""
    if plan is None:
        return ()
    outcomes = []
    for row in plan.selected_rows(kinds):
        kind = KINDS[row.kind]
        if source_error:
            outcomes.append(
                outcome(
                    row,
                    kind,
                    "skipped",
                    f"UniFi could not be re-read before writing ({source_error}); "
                    "nothing was written.",
                )
            )
        elif (
            source_items is not None
            and source_items.get((row.kind, row.source_key)) != row.source
        ):
            outcomes.append(
                outcome(
                    row, kind, "skipped", "UniFi changed since the preview; refresh."
                )
            )
        elif row.action == CREATE:
            outcomes.append(
                create_object(
                    row,
                    kind,
                    backend,
                    dry_run,
                    lookup=lookup(row),
                    name=row.name,
                    payload=dict(row.desired),
                )
            )
        else:
            outcomes.append(
                update_object(
                    row,
                    kind,
                    backend,
                    dry_run,
                    object_id=row.netbox_id,
                    changes=row.changes(),
                )
            )
    return tuple(outcomes)


def lookup(row: SiteDetailRow) -> dict[str, object]:
    desired = dict(row.desired)
    if row.kind == WLAN:
        return {"ssid": desired["ssid"]}
    if row.kind == RANGE:
        return {
            "start_address": desired["start_address"].split("/", 1)[0],
            "end_address": desired["end_address"].split("/", 1)[0],
        }
    return {"address": desired["address"].split("/", 1)[0]}


def source_items(
    wlans: Iterable[InventoryWlan],
    ranges: Iterable[InventoryDhcpRange],
    reservations: Iterable[InventoryReservation],
) -> dict[tuple[str, str], object]:
    """Fresh UniFi values keyed like ``SiteDetailRow.source_key``."""
    items: dict[tuple[str, str], object] = {}
    for wlan in wlans:
        items[(WLAN, wlan.source_id)] = wlan
    for pool in ranges:
        items[(RANGE, f"range:{pool.vlan_id}:{pool.start}")] = pool
    for reservation in reservations:
        items[(RESERVATION, reservation.ip_address)] = reservation
    return items
