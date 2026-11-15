"""Plan the management IP of matched devices as NetBox primary IPv4 (M11).

For each matched device whose UniFi data reports an IPv4 address:

- The prefix length comes from the UniFi network whose subnet contains the
  IP; without such a network the row only carries a note.
- The IP is assigned to the device's management-only interface. With none,
  an interface named ``Management`` is used; if that does not exist either,
  a virtual, management-only ``Management`` interface is created. Several
  management-only interfaces are a conflict.
- A missing IP address is created (status active) on that interface; an
  unassigned one is assigned to it; one assigned to anything else, or a
  duplicate address, is a conflict.
- The IP becomes the device's primary IPv4. A device with another primary
  IPv4 is a conflict and is never overwritten.

Devices created in the same run get their management IP after a refresh.
Nothing is ever deleted or unassigned.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass, replace

from unifi2netbox.inventory import (
    InventoryDevice,
    InventoryInterface,
    InventoryIpAddress,
    InventoryNetwork,
)

CREATE = "create"
UPDATE = "update"
IN_SYNC = "in_sync"
CONFLICT = "conflict"
NOTE = "note"

INTERFACE_NAME = "Management"


@dataclass(frozen=True)
class MgmtPair:
    device_key: str
    device_name: str
    unifi_id: str
    netbox_id: str


@dataclass(frozen=True)
class MgmtIpRow:
    key: str
    device_key: str
    device_name: str
    unifi_device_id: str
    netbox_device_id: str
    ip: str
    action: str
    address: str = ""
    interface_id: str = ""
    interface_name: str = ""
    ip_id: str = ""
    # Planned steps: create the interface, create or assign the IP, set the
    # primary IPv4. An empty step list means in sync.
    steps: tuple[str, ...] = ()
    current_primary_id: str = ""
    selected: bool = False
    notes: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return f"{self.device_name} {self.ip}"

    @property
    def selectable(self) -> bool:
        return self.action in (CREATE, UPDATE)

    def describe(self) -> str:
        texts = {
            "create_interface": f"create interface {INTERFACE_NAME}",
            "create_ip": f"create {self.address}",
            "assign_ip": f"assign {self.address}",
            "set_primary": "set primary IPv4",
        }
        return ", ".join(texts[step] for step in self.steps)


@dataclass(frozen=True)
class MgmtIpPlan:
    rows: tuple[MgmtIpRow, ...] = ()
    blocker: str = ""

    def selected_rows(self) -> tuple[MgmtIpRow, ...]:
        return tuple(row for row in self.rows if row.selected and row.selectable)

    @property
    def operation_count(self) -> int:
        return len(self.selected_rows())

    def row_for(self, netbox_device_id: str) -> MgmtIpRow | None:
        return next(
            (row for row in self.rows if row.netbox_device_id == netbox_device_id),
            None,
        )


def build_mgmt_ip_plan(
    pairs: Iterable[MgmtPair],
    unifi_devices: Iterable[InventoryDevice],
    netbox_devices: Iterable[InventoryDevice],
    interfaces: Iterable[InventoryInterface],
    addresses: Iterable[InventoryIpAddress],
    networks: Iterable[InventoryNetwork],
    *,
    address_error: str = "",
) -> MgmtIpPlan:
    if address_error:
        return MgmtIpPlan(blocker=address_error)
    unifi = {device.source_id: device for device in unifi_devices}
    netbox = {device.source_id: device for device in netbox_devices}
    interfaces = tuple(interfaces)
    addresses = tuple(addresses)
    subnets = [
        ipaddress.IPv4Network(network.subnet)
        for network in networks
        if network.subnet and ":" not in network.subnet
    ]
    rows = []
    for pair in pairs:
        source = unifi.get(pair.unifi_id)
        target = netbox.get(pair.netbox_id)
        if source is None or target is None or not source.ip_address:
            continue
        rows.append(_row(pair, source, target, interfaces, addresses, subnets))
    order = {CREATE: 0, UPDATE: 1, CONFLICT: 2, NOTE: 3, IN_SYNC: 4}
    rows.sort(key=lambda row: (order[row.action], row.device_name.lower()))
    return MgmtIpPlan(rows=tuple(rows))


def select_mgmt_ip(plan: MgmtIpPlan, key: str, selected: bool) -> MgmtIpPlan:
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
    pair: MgmtPair,
    source: InventoryDevice,
    target: InventoryDevice,
    interfaces: tuple[InventoryInterface, ...],
    addresses: tuple[InventoryIpAddress, ...],
    subnets: list[ipaddress.IPv4Network],
) -> MgmtIpRow:
    ip = source.ip_address
    base = MgmtIpRow(
        key=f"mgmt-ip:{pair.netbox_id}",
        device_key=pair.device_key,
        device_name=pair.device_name or target.name,
        unifi_device_id=pair.unifi_id,
        netbox_device_id=pair.netbox_id,
        ip=ip,
        action=NOTE,
        current_primary_id=target.primary_ip_id,
    )
    if target.primary_ip_id and target.ip_address == ip:
        return replace(base, action=IN_SYNC, ip_id=target.primary_ip_id)
    if target.primary_ip_id:
        return replace(
            base,
            action=CONFLICT,
            notes=(
                f"NetBox has the primary IPv4 {target.ip_address}; UniFi reports "
                f"{ip}. The primary IP is never overwritten.",
            ),
        )
    host = ipaddress.IPv4Address(ip)
    containing = [net for net in subnets if host in net]
    if not containing and host.is_global:
        return replace(
            base,
            notes=(
                f"UniFi reports the public (WAN) address {ip}; it is not used as "
                "the management IP.",
            ),
        )
    if not containing:
        return replace(
            base,
            notes=(f"No UniFi network contains {ip}; its prefix length is unknown.",),
        )
    network = max(containing, key=lambda net: net.prefixlen)
    address = f"{ip}/{network.prefixlen}"
    base = replace(base, address=address)

    own = [i for i in interfaces if i.device_id == pair.netbox_id]
    managed = [i for i in own if i.mgmt_only]
    named = [i for i in own if i.name == INTERFACE_NAME]
    steps: list[str] = []
    notes: list[str] = []
    same = [a for a in addresses if a.address.split("/", 1)[0] == ip]
    if len(same) > 1:
        return replace(
            base,
            action=CONFLICT,
            notes=(f"NetBox has {len(same)} IP addresses {ip}; resolve them first.",),
        )
    holder = next(
        (
            i
            for i in own
            if same
            and same[0].assigned_object_type == "dcim.interface"
            and same[0].assigned_object_id == i.source_id
        ),
        None,
    )
    if holder is not None:
        # The IP already sits on an interface of this device: keep it there.
        managed, named = [holder], []
    if len(managed) > 1:
        return replace(
            base,
            action=CONFLICT,
            notes=(
                f"The NetBox device has {len(managed)} management-only "
                "interfaces; choose one in NetBox first.",
            ),
        )
    if managed:
        interface = managed[0]
    elif named:
        interface = named[0]
        notes.append(
            f"Uses the existing interface {INTERFACE_NAME}, which is not marked "
            "management only."
        )
    else:
        interface = None
        steps.append("create_interface")

    ip_id = ""
    if same:
        existing = same[0]
        ip_id = existing.source_id
        on_interface = (
            interface is not None
            and existing.assigned_object_type == "dcim.interface"
            and existing.assigned_object_id == interface.source_id
        )
        if existing.assigned_object_id and not on_interface:
            return replace(
                base,
                action=CONFLICT,
                ip_id=ip_id,
                notes=(
                    f"NetBox IP {existing.address} is assigned to another object; "
                    "it is not moved.",
                ),
            )
        if existing.address != address:
            notes.append(
                f"NetBox keeps its address {existing.address} (UniFi network "
                f"suggests /{network.prefixlen})."
            )
        if not on_interface:
            steps.append("assign_ip")
    else:
        steps.append("create_ip")
    steps.append("set_primary")
    return replace(
        base,
        action=CREATE
        if "create_ip" in steps or "create_interface" in steps
        else UPDATE,
        interface_id=interface.source_id if interface else "",
        interface_name=interface.name if interface else INTERFACE_NAME,
        ip_id=ip_id,
        steps=tuple(steps),
        selected=True,
        notes=tuple(notes),
    )
