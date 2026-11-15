"""Plan site-level UniFi details as NetBox objects (M11 slice 6).

Three kinds of rows, all for the configured NetBox site:

- Wireless LANs: SSID, status (active/disabled), authentication type and
  cipher, the VLAN of the site VLAN group (``UniFi <site>``) and the site
  scope. Passphrases are never read. Disabled WLANs are shown but not
  preselected. A VLAN missing in NetBox is set after the networks are
  written and refreshed.
- IP ranges: the DHCP pool of a UniFi network (start/end with the network's
  prefix length), description ``DHCP <network>``, status active. A NetBox
  range that overlaps with other bounds is a conflict.
- Reserved IP addresses: fixed client IPs with the prefix length of the UniFi
  network that contains them, status reserved, the enabled local DNS record
  as DNS name and the client name (else hostname) as description. They are
  not assigned to anything.

Existing objects are only completed or aligned field by field:

- ``UPDATE`` fields (status, authentication) follow UniFi.
- ``FILL`` fields are filled when empty; a different NetBox value is kept
  with a note.
- ``LINK`` fields (WLAN VLAN and scope, reservation DNS name and
  description) are filled when empty; a different value is a conflict.
- Create-only fields (range and reservation status) are never changed.

Missing UniFi values never clear NetBox values. Several matching NetBox
objects are a conflict. Nothing is ever deleted.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace

from unifi2netbox.details import InventoryDhcpRange, InventoryReservation, InventoryWlan
from unifi2netbox.inventory import (
    InventoryIpAddress,
    InventoryIpRange,
    InventoryNetwork,
    InventorySite,
    InventoryVlan,
    InventoryVlanGroup,
    InventoryWirelessLan,
)
from unifi2netbox.networks import group_name_for, slugify

CREATE = "create"
UPDATE = "update"
IN_SYNC = "in_sync"
CONFLICT = "conflict"
NOTE = "note"

WLAN = "wlan"
RANGE = "range"
RESERVATION = "reservation"
KIND_LABELS = {WLAN: "Wireless LAN", RANGE: "IP range", RESERVATION: "Reserved IP"}

# Field policies.
_UPDATE, _FILL, _LINK, _CREATE_ONLY = "update", "fill", "link", "create_only"
_POLICIES = {
    WLAN: {
        "ssid": _CREATE_ONLY,
        "status": _UPDATE,
        "auth_type": _UPDATE,
        "auth_cipher": _UPDATE,
        "vlan": _LINK,
        "scope_type": _LINK,
        "scope_id": _LINK,
    },
    RANGE: {
        "start_address": _CREATE_ONLY,
        "end_address": _CREATE_ONLY,
        "status": _CREATE_ONLY,
        "description": _FILL,
    },
    RESERVATION: {
        "address": _CREATE_ONLY,
        "status": _CREATE_ONLY,
        "dns_name": _LINK,
        "description": _LINK,
    },
}

AUTH_TYPES = {
    "open": "open",
    "wep": "wep",
    "wpapsk": "wpa-personal",
    "wpaeap": "wpa-enterprise",
}
AUTH_CIPHERS = {
    "auto": "auto",
    "tkip": "tkip",
    "ccmp": "aes",
    "gcmp": "aes",
    "ccmp-256": "aes",
    "gcmp-256": "aes",
}
_DNS_NAME = re.compile(r"^([0-9A-Za-z_-]+|\*)(\.[0-9A-Za-z_-]+)*\.?$")
_DESCRIPTION_MAX = 200


@dataclass(frozen=True)
class SiteDetailRow:
    key: str
    kind: str
    name: str
    action: str
    source_key: str = ""
    source: object | None = None
    netbox_id: str = ""
    current: tuple[tuple[str, str], ...] = ()
    desired: tuple[tuple[str, str], ...] = ()
    selected: bool = False
    notes: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return f"{KIND_LABELS[self.kind]} {self.name}"

    @property
    def selectable(self) -> bool:
        return self.action in (CREATE, UPDATE)

    def changes(self) -> tuple[tuple[str, str, str], ...]:
        """(field, current, desired) of the fields a write would set."""
        if self.action == CREATE:
            return tuple((field, "", value) for field, value in self.desired if value)
        current = dict(self.current)
        policies = _POLICIES[self.kind]
        result = []
        for field, value in self.desired:
            before = current.get(field, "")
            if not value or value == before:
                continue
            policy = policies.get(field, _CREATE_ONLY)
            if policy == _UPDATE or (policy in (_FILL, _LINK) and not before):
                result.append((field, before, value))
        return tuple(result)


@dataclass(frozen=True)
class SiteDetailPlan:
    rows: tuple[SiteDetailRow, ...] = ()
    note: str = ""

    def selected_rows(self, kinds: Iterable[str] = ()) -> tuple[SiteDetailRow, ...]:
        wanted = set(kinds)
        return tuple(
            row
            for row in self.rows
            if row.selected and row.selectable and (not wanted or row.kind in wanted)
        )

    @property
    def operation_count(self) -> int:
        return len(self.selected_rows())

    def rows_of(self, kind: str) -> tuple[SiteDetailRow, ...]:
        return tuple(row for row in self.rows if row.kind == kind)


def build_site_detail_plan(
    *,
    wlans: Iterable[InventoryWlan],
    dhcp_ranges: Iterable[InventoryDhcpRange],
    reservations: Iterable[InventoryReservation],
    networks: Iterable[InventoryNetwork],
    sites: Iterable[InventorySite],
    vlan_groups: Iterable[InventoryVlanGroup],
    vlans: Iterable[InventoryVlan],
    wireless_lans: Iterable[InventoryWirelessLan],
    ip_ranges: Iterable[InventoryIpRange],
    ip_addresses: Iterable[InventoryIpAddress],
    site_name: str,
    client_error: str = "",
    ipam_error: str = "",
    address_error: str = "",
    wireless_error: str = "",
) -> SiteDetailPlan:
    """Compare UniFi WLANs, DHCP ranges and reservations with NetBox."""
    wlans, dhcp_ranges, reservations = (
        tuple(wlans),
        tuple(dhcp_ranges),
        tuple(reservations),
    )
    if not (wlans or dhcp_ranges or reservations):
        return SiteDetailPlan(note=client_error)
    site = next((item for item in sites if item.name == site_name.strip()), None)
    if site is None:
        return SiteDetailPlan(
            note=(
                "Set 'NetBox site for UniFi devices' in Settings to an existing "
                "NetBox site to plan wireless LANs, IP ranges and reservations."
            )
        )
    subnets = _subnets(networks)
    rows: list[SiteDetailRow] = []
    if wireless_error or ipam_error:
        blocker = wireless_error or ipam_error
        rows += [_note(WLAN, w.ssid, f"wlan:{w.source_id}", blocker) for w in wlans]
    else:
        group = _site_group(site, tuple(vlan_groups))
        group_vlans = {
            vlan.vid: vlan.source_id
            for vlan in vlans
            if group is not None and vlan.group_id == group
        }
        existing = tuple(wireless_lans)
        rows += [_wlan_row(w, site, group_vlans, existing) for w in wlans]
    if address_error:
        rows += [
            _note(RANGE, f"{r.start}-{r.end}", f"range:{r.vlan_id}", address_error)
            for r in dhcp_ranges
        ]
        rows += [
            _note(
                RESERVATION, r.ip_address, f"reservation:{r.ip_address}", address_error
            )
            for r in reservations
        ]
    else:
        existing_ranges = tuple(ip_ranges)
        rows += [_range_row(r, subnets, existing_ranges) for r in dhcp_ranges]
        by_host: dict[str, list[InventoryIpAddress]] = {}
        for address in ip_addresses:
            by_host.setdefault(_host(address.address), []).append(address)
        rows += [_reservation_row(r, subnets, by_host) for r in reservations]
    order = {CREATE: 0, UPDATE: 1, CONFLICT: 2, NOTE: 3, IN_SYNC: 4}
    kinds = {WLAN: 0, RANGE: 1, RESERVATION: 2}
    rows.sort(key=lambda row: (kinds[row.kind], order[row.action], _sort_key(row)))
    return SiteDetailPlan(tuple(rows), note=client_error)


def select_site_detail(
    plan: SiteDetailPlan, key: str, selected: bool
) -> SiteDetailPlan:
    """Select or clear one row; ``key`` ``"kind:*"`` selects all of a kind."""
    kind = key[:-2] if key.endswith(":*") else ""
    rows = tuple(
        replace(row, selected=selected)
        if row.selectable and (row.key == key or row.kind == kind)
        else row
        for row in plan.rows
    )
    return replace(plan, rows=rows)


# -- wireless LANs -----------------------------------------------------------


def _wlan_row(
    wlan: InventoryWlan,
    site: InventorySite,
    group_vlans: dict[int, str],
    existing: tuple[InventoryWirelessLan, ...],
) -> SiteDetailRow:
    notes: list[str] = []
    vlan_id = ""
    if wlan.vlan_id is not None:
        vlan_id = group_vlans.get(wlan.vlan_id, "")
        if not vlan_id:
            notes.append(
                f"VLAN {wlan.vlan_id} is not in the site VLAN group yet; it is set "
                "after the networks are written and refreshed."
            )
    auth_type = AUTH_TYPES.get(wlan.security.lower(), "")
    auth_cipher = AUTH_CIPHERS.get(wlan.wpa_enc.lower(), "") if auth_type else ""
    if wlan.security and not auth_type:
        notes.append(f"UniFi security '{wlan.security}' has no NetBox equivalent.")
    desired = (
        ("ssid", wlan.ssid),
        ("status", "active" if wlan.enabled else "disabled"),
        ("auth_type", auth_type),
        ("auth_cipher", auth_cipher),
        ("vlan", vlan_id),
        ("scope_type", "dcim.site"),
        ("scope_id", site.source_id),
    )
    if not wlan.enabled:
        notes.append("Disabled in UniFi; not preselected.")
    matches = [item for item in existing if item.ssid == wlan.ssid]
    base = dict(
        key=f"wlan:{wlan.source_id}",
        kind=WLAN,
        name=wlan.ssid,
        source_key=wlan.source_id,
        source=wlan,
        desired=desired,
    )
    if len(matches) > 1:
        notes.append(f"NetBox has {len(matches)} wireless LANs with this SSID.")
        return SiteDetailRow(action=CONFLICT, notes=tuple(notes), **base)
    if not matches:
        return SiteDetailRow(
            action=CREATE, selected=wlan.enabled, notes=tuple(notes), **base
        )
    target = matches[0]
    current = (
        ("ssid", target.ssid),
        ("status", target.status),
        ("auth_type", target.auth_type),
        ("auth_cipher", target.auth_cipher),
        ("vlan", target.vlan_id),
        ("scope_type", target.scope_type),
        ("scope_id", target.scope_id),
    )
    return _existing_row(base, target.source_id, current, notes, wlan.enabled)


# -- IP ranges ---------------------------------------------------------------


def _range_row(
    pool: InventoryDhcpRange,
    subnets: tuple[ipaddress.IPv4Network, ...],
    existing: tuple[InventoryIpRange, ...],
) -> SiteDetailRow:
    name = f"{pool.start}-{pool.end}"
    key = f"range:{pool.vlan_id}:{pool.start}"
    network = _containing(pool.start, subnets)
    if network is None or ipaddress.IPv4Address(pool.end) not in network:
        return _note(
            RANGE, name, key, "No UniFi network subnet contains this DHCP range."
        )
    length = network.prefixlen
    desired = (
        ("start_address", f"{pool.start}/{length}"),
        ("end_address", f"{pool.end}/{length}"),
        ("status", "active"),
        ("description", _description(f"DHCP {pool.network_name}".strip())),
    )
    base = dict(
        key=key,
        kind=RANGE,
        name=name,
        source_key=key,
        source=pool,
        desired=desired,
    )
    start, end = ipaddress.IPv4Address(pool.start), ipaddress.IPv4Address(pool.end)
    exact = [
        item
        for item in existing
        if _host(item.start_address) == pool.start
        and _host(item.end_address) == pool.end
    ]
    overlapping = [
        item for item in existing if item not in exact and _overlaps(item, start, end)
    ]
    if overlapping or len(exact) > 1:
        other = (overlapping or exact)[0]
        return SiteDetailRow(
            action=CONFLICT,
            notes=(
                f"NetBox range {_host(other.start_address)}-"
                f"{_host(other.end_address)} overlaps this DHCP range.",
            ),
            **base,
        )
    if not exact:
        return SiteDetailRow(action=CREATE, selected=True, **base)
    target = exact[0]
    current = (
        ("start_address", target.start_address),
        ("end_address", target.end_address),
        ("status", target.status),
        ("description", target.description),
    )
    return _existing_row(base, target.source_id, current, [], True)


# -- reservations ------------------------------------------------------------


def _reservation_row(
    reservation: InventoryReservation,
    subnets: tuple[ipaddress.IPv4Network, ...],
    by_host: dict[str, list[InventoryIpAddress]],
) -> SiteDetailRow:
    ip = reservation.ip_address
    key = f"reservation:{ip}"
    network = _containing(ip, subnets)
    if network is None:
        return _note(
            RESERVATION, ip, key, "No UniFi network subnet contains this reserved IP."
        )
    notes: list[str] = []
    dns_name = reservation.dns_name
    if dns_name and not _DNS_NAME.match(dns_name):
        notes.append(f"Local DNS record '{dns_name}' is not a valid NetBox DNS name.")
        dns_name = ""
    desired = (
        ("address", f"{ip}/{network.prefixlen}"),
        ("status", "reserved"),
        ("dns_name", dns_name),
        ("description", _description(reservation.name or reservation.hostname)),
    )
    base = dict(
        key=key,
        kind=RESERVATION,
        name=ip,
        source_key=ip,
        source=reservation,
        desired=desired,
    )
    matches = by_host.get(ip, [])
    if len(matches) > 1:
        notes.append(f"NetBox has {len(matches)} IP addresses {ip}.")
        return SiteDetailRow(action=CONFLICT, notes=tuple(notes), **base)
    if not matches:
        return SiteDetailRow(action=CREATE, selected=True, notes=tuple(notes), **base)
    target = matches[0]
    current = (
        ("address", target.address),
        ("status", target.status),
        ("dns_name", target.dns_name),
        ("description", target.description),
    )
    if target.address != desired[0][1]:
        notes.append(f"NetBox has this IP as {target.address}.")
    return _existing_row(base, target.source_id, current, notes, True)


# -- shared ------------------------------------------------------------------


def _existing_row(
    base: dict,
    netbox_id: str,
    current: tuple[tuple[str, str], ...],
    notes: list[str],
    preselect: bool,
) -> SiteDetailRow:
    policies = _POLICIES[base["kind"]]
    before = dict(current)
    conflicts = []
    for field, value in base["desired"]:
        now = before.get(field, "")
        if not value or not now or value == now:
            continue
        if policies.get(field) == _LINK:
            conflicts.append(field)
        elif policies.get(field) == _FILL:
            notes.append(f"NetBox keeps its {field.replace('_', ' ')} '{now}'.")
    if conflicts:
        notes.append(f"NetBox has other values in {', '.join(conflicts)}.")
        return SiteDetailRow(
            action=CONFLICT,
            netbox_id=netbox_id,
            current=current,
            notes=tuple(notes),
            **base,
        )
    row = SiteDetailRow(
        action=UPDATE,
        netbox_id=netbox_id,
        current=current,
        notes=tuple(notes),
        **base,
    )
    if not row.changes():
        return replace(row, action=IN_SYNC)
    return replace(row, selected=preselect)


def _note(kind: str, name: str, key: str, message: str) -> SiteDetailRow:
    return SiteDetailRow(key=key, kind=kind, name=name, action=NOTE, notes=(message,))


def _site_group(site: InventorySite, groups: tuple[InventoryVlanGroup, ...]) -> str:
    name = group_name_for(site.name)
    slug = slugify(name)
    for group in groups:
        if group.slug == slug or (
            group.name == name
            and group.scope_type == "dcim.site"
            and group.scope_id == site.source_id
        ):
            return group.source_id
    return ""


def _subnets(networks: Iterable[InventoryNetwork]) -> tuple[ipaddress.IPv4Network, ...]:
    result = []
    for network in networks:
        if not network.subnet or ":" in network.subnet:
            continue
        try:
            result.append(ipaddress.IPv4Network(network.subnet, strict=False))
        except ValueError:
            continue
    return tuple(result)


def _containing(
    ip: str, subnets: tuple[ipaddress.IPv4Network, ...]
) -> ipaddress.IPv4Network | None:
    host = ipaddress.IPv4Address(ip)
    matches = [net for net in subnets if host in net]
    return max(matches, key=lambda net: net.prefixlen) if matches else None


def _host(value: str) -> str:
    return value.split("/", 1)[0].strip()


def _overlaps(
    item: InventoryIpRange, start: ipaddress.IPv4Address, end: ipaddress.IPv4Address
) -> bool:
    try:
        first = ipaddress.IPv4Address(_host(item.start_address))
        last = ipaddress.IPv4Address(_host(item.end_address))
    except ValueError:
        return False
    return first <= end and start <= last


def _description(value: str) -> str:
    return value.strip()[:_DESCRIPTION_MAX]


def _sort_key(row: SiteDetailRow) -> tuple:
    if row.kind == WLAN:
        return (0, row.name.lower())
    try:
        return (ipaddress.IPv4Address(row.name.split("-", 1)[0]).packed, "")
    except ValueError:
        return (b"", row.name)
