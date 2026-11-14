"""Suggest NetBox cables from unambiguous UniFi link evidence.

Evidence (``links.py``) is grouped per pair of UniFi devices. A pair becomes a
cable suggestion only when:

- all observations agree on one port at each end (otherwise: conflict),
- no port is claimed by another device pair (otherwise: conflict),
- both devices are matched to NetBox and both ports map to an interface:
  through the port pairing of ``ports.py``, or, for devices without UniFi port
  data, through the only physical NetBox interface when the evidence names no
  port or port 1,
- neither interface already has a different cable (never replaced).

Suggestions seen from two or more observations are preselected; single
observations are offered but left unchecked. Cables are only created, never
changed or deleted.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from unifi2netbox.inventory import InventoryInterface, InventoryPort
from unifi2netbox.links import LLDP, InventoryLink
from unifi2netbox.ports import interface_family, match_ports

CREATE = "create"
IN_SYNC = "in_sync"
CONFLICT = "conflict"
REFERENCE = "reference"


@dataclass(frozen=True)
class CableEnd:
    unifi_device_id: str
    device_name: str
    port_idx: int | None
    interface_id: str = ""
    interface_name: str = ""

    @property
    def label(self) -> str:
        port = self.interface_name or (
            f"port {self.port_idx}" if self.port_idx else "unknown port"
        )
        return f"{self.device_name} {port}"


@dataclass(frozen=True)
class CablePlanRow:
    key: str
    a: CableEnd
    b: CableEnd
    sources: tuple[str, ...]
    action: str
    selected: bool = False
    notes: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return f"{self.a.label} ↔ {self.b.label}"

    @property
    def selectable(self) -> bool:
        return self.action == CREATE


@dataclass(frozen=True)
class CablePlan:
    rows: tuple[CablePlanRow, ...] = ()
    blocker: str = ""

    def selected_rows(self) -> tuple[CablePlanRow, ...]:
        return tuple(row for row in self.rows if row.selected and row.selectable)

    @property
    def operation_count(self) -> int:
        return len(self.selected_rows())


def build_cable_plan(
    links: Iterable[InventoryLink],
    device_names: Mapping[str, str],
    netbox_ids: Mapping[str, str],
    ports: Iterable[InventoryPort],
    interfaces: Iterable[InventoryInterface],
    *,
    port_config_error: str = "",
) -> CablePlan:
    """Cable suggestions; ``netbox_ids`` maps matched UniFi to NetBox IDs."""
    links = tuple(links)
    if not links:
        return CablePlan(
            blocker=port_config_error or "UniFi reported no links between devices."
        )
    ports = tuple(ports)
    interfaces = tuple(interfaces)

    # Group observations per unordered device pair, ports oriented to the pair.
    grouped: dict[tuple[str, str], list[tuple[int | None, int | None, str]]] = (
        defaultdict(list)
    )
    for link in links:
        a, b = link.device_id, link.peer_device_id
        if a <= b:
            grouped[(a, b)].append(
                (link.port_idx, link.peer_port_idx, _source(link, device_names))
            )
        else:
            grouped[(b, a)].append(
                (link.peer_port_idx, link.port_idx, _source(link, device_names))
            )

    resolved: dict[
        tuple[str, str], tuple[int | None, int | None, tuple[str, ...], list[str]]
    ] = {}
    for pair, observations in grouped.items():
        notes: list[str] = []
        a_ports = {p for p, _, _ in observations if p is not None}
        b_ports = {p for _, p, _ in observations if p is not None}
        if len(a_ports) > 1 or len(b_ports) > 1:
            notes.append("UniFi reports different ports for this link; not suggested.")
        resolved[pair] = (
            min(a_ports) if len(a_ports) == 1 else None,
            min(b_ports) if len(b_ports) == 1 else None,
            tuple(sorted({source for _, _, source in observations})),
            notes,
        )

    claims: dict[tuple[str, int], list[tuple[str, str]]] = defaultdict(list)
    for (a, b), (pa, pb, _, notes) in resolved.items():
        if notes:
            continue
        if pa is not None:
            claims[(a, pa)].append((a, b))
        if pb is not None:
            claims[(b, pb)].append((a, b))
    for (device, port), pairs in claims.items():
        if len(pairs) > 1:
            for pair in pairs:
                resolved[pair][3].append(
                    f"{device_names.get(device, device)} port {port} is reported "
                    "for more than one neighbor; not suggested."
                )

    port_maps = _port_maps(netbox_ids, ports, interfaces)
    by_id = {item.source_id: item for item in interfaces}
    rows = [
        _row(pair, value, device_names, netbox_ids, port_maps, interfaces, by_id)
        for pair, value in sorted(resolved.items())
    ]
    order = {CREATE: 0, IN_SYNC: 1, CONFLICT: 2, REFERENCE: 3}
    rows.sort(key=lambda row: (order[row.action], row.label))
    return CablePlan(rows=tuple(rows))


def select_cable(plan: CablePlan, key: str, selected: bool) -> CablePlan:
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
    pair: tuple[str, str],
    value: tuple[int | None, int | None, tuple[str, ...], list[str]],
    names: Mapping[str, str],
    netbox_ids: Mapping[str, str],
    port_maps: Mapping[str, dict[int, InventoryInterface]],
    interfaces: tuple[InventoryInterface, ...],
    by_id: Mapping[str, InventoryInterface],
) -> CablePlanRow:
    (a_id, b_id), (pa, pb, sources, notes) = pair, value
    notes = list(notes)
    ends = []
    for device_id, port in ((a_id, pa), (b_id, pb)):
        interface, reason = _interface_for(
            device_id, port, netbox_ids, port_maps, interfaces
        )
        if reason:
            notes.append(f"{names.get(device_id, device_id)}: {reason}")
        ends.append(
            CableEnd(
                device_id,
                names.get(device_id, device_id),
                port,
                interface.source_id if interface else "",
                interface.name if interface else "",
            )
        )
    a, b = ends
    key = f"cable:{a_id}:{pa or 0}-{b_id}:{pb or 0}"
    if any("not suggested" in note for note in notes):
        return CablePlanRow(key, a, b, sources, CONFLICT, notes=tuple(notes))
    if not (a.interface_id and b.interface_id):
        return CablePlanRow(key, a, b, sources, REFERENCE, notes=tuple(notes))
    ia, ib = by_id[a.interface_id], by_id[b.interface_id]
    if ib.source_id in ia.link_peer_ids:
        return CablePlanRow(key, a, b, sources, IN_SYNC, notes=tuple(notes))
    for end, item in ((a, ia), (b, ib)):
        if item.cable_id:
            notes.append(
                f"{end.label} already has another cable in NetBox; it is never "
                "replaced."
            )
    if ia.cable_id or ib.cable_id:
        return CablePlanRow(key, a, b, sources, CONFLICT, notes=tuple(notes))
    confirmed = len(sources) >= 2
    if not confirmed:
        notes.append("Seen from one observation only; check before selecting.")
    return CablePlanRow(key, a, b, sources, CREATE, confirmed, tuple(notes))


def _interface_for(
    device_id: str,
    port: int | None,
    netbox_ids: Mapping[str, str],
    port_maps: Mapping[str, dict[int, InventoryInterface]],
    interfaces: tuple[InventoryInterface, ...],
) -> tuple[InventoryInterface | None, str]:
    netbox_id = netbox_ids.get(device_id)
    if not netbox_id:
        return None, "not matched to a NetBox device."
    mapping = port_maps.get(device_id)
    if mapping:
        if port is None:
            return None, "the port number is unknown."
        interface = mapping.get(port)
        if interface is None:
            return None, f"port {port} has no paired NetBox interface."
        return interface, ""
    physical = [
        item
        for item in interfaces
        if item.device_id == netbox_id and interface_family(item.type)
    ]
    if len(physical) == 1 and port in (None, 1):
        return physical[0], ""
    return None, "no unambiguous NetBox interface for this port."


def _port_maps(
    netbox_ids: Mapping[str, str],
    ports: tuple[InventoryPort, ...],
    interfaces: tuple[InventoryInterface, ...],
) -> dict[str, dict[int, InventoryInterface]]:
    maps: dict[str, dict[int, InventoryInterface]] = {}
    for unifi_id, netbox_id in netbox_ids.items():
        device_ports = [p for p in ports if p.device_id == unifi_id]
        if not device_ports:
            continue
        device_interfaces = [i for i in interfaces if i.device_id == netbox_id]
        maps[unifi_id] = {
            match.port.idx: match.interface
            for match in match_ports(device_ports, device_interfaces)
            if match.port is not None and match.interface is not None
        }
    return maps


def _source(link: InventoryLink, names: Mapping[str, str]) -> str:
    kind = "LLDP" if link.source == LLDP else "Uplink"
    return f"{kind} from {names.get(link.device_id, link.device_id)}"
