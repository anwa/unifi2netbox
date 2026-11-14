"""Match UniFi switch ports to NetBox interfaces of one matched device.

UniFi numbers ports globally (``idx``) and NetBox names interfaces after the
device-type template ("Port 1", "SFP+ 1"). Ports and interfaces are paired per
connector family (copper or optical) in numbering order. Differences in speed
or PoE capability are reported as notes; link state and current speed are
operational and only shown, never compared as configuration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from unifi2netbox.inventory import InventoryInterface, InventoryPort

COPPER = "copper"
OPTICAL = "optical"

_SPEED_PREFIXES = (
    ("100gbase", 100000),
    ("40gbase", 40000),
    ("25gbase", 25000),
    ("10gbase", 10000),
    ("5gbase", 5000),
    ("2.5gbase", 2500),
    ("1000base", 1000),
    ("100base", 100),
    ("10base", 10),
)


@dataclass(frozen=True)
class PortMatch:
    port: InventoryPort | None
    interface: InventoryInterface | None
    notes: tuple[str, ...] = ()

    @property
    def matched(self) -> bool:
        return self.port is not None and self.interface is not None


def connector_family(connector: str) -> str:
    value = connector.strip().upper()
    if value == "RJ45":
        return COPPER
    if value.startswith(("SFP", "QSFP")):
        return OPTICAL
    return ""


def interface_family(interface_type: str) -> str:
    value = interface_type.strip().lower()
    if "sfp" in value or "-x-" in value or value.endswith("-x"):
        return OPTICAL
    if value.endswith(("base-t", "base-tx")):
        return COPPER
    return ""


def interface_speed_mbps(interface_type: str) -> int:
    value = interface_type.strip().lower()
    for prefix, speed in _SPEED_PREFIXES:
        if value.startswith(prefix):
            return speed
    return 0


def connector_kind(connector: str) -> str:
    """Exact connector kind, for example RJ45, SFP, SFPPLUS or SFP28."""
    return connector.strip().upper()


def interface_kind(interface_type: str) -> str:
    """Connector kind implied by a NetBox interface type."""
    value = interface_type.strip().lower()
    if "qsfp" in value:
        return "QSFP"
    if value.endswith("sfp28"):
        return "SFP28"
    if value.endswith("sfpp"):
        return "SFPPLUS"
    if value.endswith("sfp"):
        return "SFP"
    if interface_family(value) == COPPER:
        return "RJ45"
    return ""


def match_ports(
    ports: tuple[InventoryPort, ...] | list[InventoryPort],
    interfaces: tuple[InventoryInterface, ...] | list[InventoryInterface],
) -> tuple[PortMatch, ...]:
    """Pair ports and physical interfaces in numbering order.

    Pass one pairs by exact connector kind (RJ45, SFP, SFP+, SFP28), so mixed
    optical templates such as 28x SFP+ plus 4x SFP28 line up. Pass two pairs
    whatever is left within the copper or optical family.
    """
    remaining_ports = sorted(
        (port for port in ports if connector_family(port.connector)),
        key=lambda port: port.idx,
    )
    remaining_interfaces = sorted(
        (
            item
            for item in interfaces
            if not item.mgmt_only and interface_family(item.type)
        ),
        key=_interface_order,
    )
    pairs: list[tuple[InventoryPort, InventoryInterface]] = []
    for kinds in (
        lambda port, item: connector_kind(port.connector) == interface_kind(item.type),
        lambda port, item: (
            connector_family(port.connector) == interface_family(item.type)
        ),
    ):
        for port in list(remaining_ports):
            item = next((i for i in remaining_interfaces if kinds(port, i)), None)
            if item is None:
                continue
            pairs.append((port, item))
            remaining_ports.remove(port)
            remaining_interfaces.remove(item)
    matches = [PortMatch(port, item, _notes(port, item)) for port, item in pairs]
    matches.extend(
        PortMatch(port, None, _notes(port, None)) for port in remaining_ports
    )
    matches.extend(
        PortMatch(None, item, _notes(None, item)) for item in remaining_interfaces
    )
    unknown = [port for port in ports if not connector_family(port.connector)]
    matches.extend(
        PortMatch(port, None, (f"Unknown connector '{port.connector}'.",))
        for port in sorted(unknown, key=lambda port: port.idx)
    )
    return tuple(
        sorted(
            matches,
            key=lambda match: (
                match.port.idx if match.port else 10_000,
                _interface_order(match.interface) if match.interface else (),
            ),
        )
    )


def _notes(port: InventoryPort | None, interface: InventoryInterface | None) -> tuple:
    if port is None and interface is not None:
        return ("No UniFi port for this NetBox interface.",)
    if interface is None and port is not None:
        return ("No NetBox interface for this UniFi port.",)
    if port is None or interface is None:
        return ()
    notes: list[str] = []
    netbox_speed = interface_speed_mbps(interface.type)
    if port.max_speed_mbps and netbox_speed and port.max_speed_mbps != netbox_speed:
        notes.append(
            f"UniFi port supports {_speed(port.max_speed_mbps)}, NetBox type "
            f"{interface.type} is {_speed(netbox_speed)}."
        )
    poe_capable = bool(port.poe_standard)
    if poe_capable and interface.poe_mode != "pse":
        notes.append("UniFi port supplies PoE; NetBox interface has no PSE mode.")
    elif not poe_capable and interface.poe_mode == "pse":
        notes.append("NetBox marks PoE supply; UniFi port has no PoE.")
    return tuple(notes)


def _speed(mbps: int) -> str:
    if mbps >= 1000:
        value = mbps / 1000
        return f"{value:g} Gbit/s"
    return f"{mbps} Mbit/s"


_KIND_ORDER = ("RJ45", "SFP", "SFPPLUS", "SFP28", "QSFP")


def _interface_order(item: InventoryInterface) -> tuple:
    kind = interface_kind(item.type)
    rank = _KIND_ORDER.index(kind) if kind in _KIND_ORDER else len(_KIND_ORDER)
    return (rank, _natural_key(item.name))


def _natural_key(name: str) -> tuple:
    return tuple(
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", name)
        if part
    )
