"""Plan NetBox VLAN groups, VLANs and prefixes from UniFi networks.

One VLAN group per NetBox site ("UniFi <site>", scoped to the site) holds a
VLAN per enabled UniFi network. Each network subnet becomes a site-scoped
prefix linked to its VLAN. Existing objects are only completed: names are
aligned and a missing prefix VLAN is filled in, but a prefix that already
points at another VLAN, duplicate prefixes or duplicate UniFi VLAN IDs are
reported as conflicts and never written automatically.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace

from unifi2netbox.inventory import (
    InventoryNetwork,
    InventoryPrefix,
    InventorySite,
    InventoryVlan,
    InventoryVlanGroup,
)

CREATE = "create"
UPDATE = "update"
IN_SYNC = "in_sync"
CONFLICT = "conflict"
NONE = "none"


@dataclass(frozen=True)
class VlanGroupPlan:
    name: str
    slug: str
    site_id: str
    site_name: str
    action: str
    netbox_id: str = ""


@dataclass(frozen=True)
class NetworkPlanRow:
    key: str
    name: str
    vid: int
    subnet: str
    enabled: bool
    vlan_action: str
    prefix_action: str
    netbox_vlan_id: str = ""
    netbox_vlan_name: str = ""
    netbox_prefix_id: str = ""
    vlan_selected: bool = False
    prefix_selected: bool = False
    notes: tuple[str, ...] = ()

    @property
    def selectable(self) -> bool:
        return self.vlan_action in (CREATE, UPDATE) or self.prefix_action in (
            CREATE,
            UPDATE,
        )

    @property
    def selected(self) -> bool:
        return self.vlan_selected or self.prefix_selected

    @property
    def category(self) -> str:
        if CONFLICT in (self.vlan_action, self.prefix_action):
            return CONFLICT
        if CREATE in (self.vlan_action, self.prefix_action):
            return CREATE
        if UPDATE in (self.vlan_action, self.prefix_action):
            return UPDATE
        return IN_SYNC


@dataclass(frozen=True)
class NetworkPlan:
    group: VlanGroupPlan | None
    rows: tuple[NetworkPlanRow, ...]
    blocker: str = ""

    def selected_rows(self) -> tuple[NetworkPlanRow, ...]:
        return tuple(row for row in self.rows if row.selected)

    @property
    def operation_count(self) -> int:
        count = sum(
            int(row.vlan_selected) + int(row.prefix_selected) for row in self.rows
        )
        if count and self.group is not None and self.group.action == CREATE:
            count += 1
        return count


def group_name_for(site_name: str) -> str:
    return f"UniFi {site_name}".strip()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:100] or "unifi"


def build_network_plan(
    networks: tuple[InventoryNetwork, ...],
    sites: tuple[InventorySite, ...],
    vlan_groups: tuple[InventoryVlanGroup, ...],
    vlans: tuple[InventoryVlan, ...],
    prefixes: tuple[InventoryPrefix, ...],
    *,
    site_name: str,
    ipam_error: str = "",
) -> NetworkPlan:
    """Compare UniFi networks with NetBox IPAM for one NetBox site."""
    if not networks:
        return NetworkPlan(None, ())
    if ipam_error:
        return NetworkPlan(None, (), blocker=ipam_error)
    site = next((item for item in sites if item.name == site_name), None)
    if site is None:
        return NetworkPlan(
            None,
            (),
            blocker=(
                "Set 'NetBox site for UniFi devices' in Settings to an existing "
                "NetBox site to plan VLANs and prefixes."
            ),
        )

    name = group_name_for(site.name)
    slug = slugify(name)
    group = next(
        (
            item
            for item in vlan_groups
            if item.slug == slug
            or (
                item.name == name
                and item.scope_type == "dcim.site"
                and item.scope_id == site.source_id
            )
        ),
        None,
    )
    group_plan = VlanGroupPlan(
        name=name,
        slug=slug,
        site_id=site.source_id,
        site_name=site.name,
        action=IN_SYNC if group else CREATE,
        netbox_id=group.source_id if group else "",
    )
    group_vlans = {
        vlan.vid: vlan for vlan in vlans if group and vlan.group_id == group.source_id
    }
    vlan_by_id = {vlan.source_id: vlan for vlan in vlans}
    prefixes_by_value: dict[str, list[InventoryPrefix]] = {}
    for prefix in prefixes:
        prefixes_by_value.setdefault(prefix.prefix, []).append(prefix)
    duplicate_vids = {
        vid for vid, count in Counter(n.vlan_id for n in networks).items() if count > 1
    }

    rows = [
        _plan_row(
            network,
            group_vlans.get(network.vlan_id),
            prefixes_by_value.get(network.subnet, []),
            vlan_by_id,
            duplicate=network.vlan_id in duplicate_vids,
        )
        for network in sorted(networks, key=lambda item: (item.vlan_id, item.name))
    ]
    return NetworkPlan(group_plan, tuple(rows))


def _plan_row(
    network: InventoryNetwork,
    vlan: InventoryVlan | None,
    prefixes: list[InventoryPrefix],
    vlan_by_id: dict[str, InventoryVlan],
    *,
    duplicate: bool,
) -> NetworkPlanRow:
    notes: list[str] = []
    if duplicate:
        vlan_action = CONFLICT
        notes.append(f"Several UniFi networks use VLAN {network.vlan_id}.")
    elif vlan is None:
        vlan_action = CREATE
    elif vlan.name != network.name:
        vlan_action = UPDATE
        notes.append(f"NetBox VLAN is named '{vlan.name}'.")
    else:
        vlan_action = IN_SYNC

    prefix_id = ""
    if not network.subnet:
        prefix_action = NONE
    elif len(prefixes) > 1:
        prefix_action = CONFLICT
        notes.append(f"NetBox has {len(prefixes)} prefixes {network.subnet}.")
    elif not prefixes:
        prefix_action = CREATE
    else:
        prefix = prefixes[0]
        prefix_id = prefix.source_id
        linked = vlan_by_id.get(prefix.vlan_id)
        if not prefix.vlan_id:
            prefix_action = UPDATE
            notes.append("NetBox prefix has no VLAN yet.")
        elif (
            linked is not None
            and vlan is not None
            and linked.source_id == vlan.source_id
        ):
            prefix_action = IN_SYNC
        else:
            prefix_action = CONFLICT
            other = f"VLAN {linked.vid}" if linked else "another VLAN"
            notes.append(f"NetBox prefix already points to {other}.")

    if not network.enabled:
        notes.append("Disabled in UniFi; shown for reference only.")
    writable = network.enabled and not duplicate
    return NetworkPlanRow(
        key=f"network:{network.source_id}",
        name=network.name,
        vid=network.vlan_id,
        subnet=network.subnet,
        enabled=network.enabled,
        vlan_action=vlan_action,
        prefix_action=prefix_action,
        netbox_vlan_id=vlan.source_id if vlan else "",
        netbox_vlan_name=vlan.name if vlan else "",
        netbox_prefix_id=prefix_id,
        vlan_selected=writable and vlan_action in (CREATE, UPDATE),
        prefix_selected=writable and prefix_action in (CREATE, UPDATE),
        notes=tuple(notes),
    )


def select_network(
    plan: NetworkPlan, key: str, part: str, selected: bool
) -> NetworkPlan:
    """Select or clear the VLAN, the prefix or both ("all") of one network."""
    rows = []
    for row in plan.rows:
        if row.key == key and row.enabled:
            if part in ("vlan", "all") and row.vlan_action in (CREATE, UPDATE):
                row = replace(row, vlan_selected=selected)
            if part in ("prefix", "all") and row.prefix_action in (CREATE, UPDATE):
                row = replace(row, prefix_selected=selected)
        rows.append(row)
    return replace(plan, rows=tuple(rows))
