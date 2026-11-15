"""Additional UniFi details from internal Network endpoints (read-only).

The official Integration API has no SFP modules, DHCP ranges, wireless LANs or
DHCP reservations. This module reduces the internal ``stat/device``,
``rest/networkconf``, ``rest/wlanconf`` and ``rest/user`` payloads to an
explicit field allow-list right where they are parsed:

- SFP modules: vendor, part, serial, compliance and revision of a module that
  UniFi reports as present (``sfp_found``).
- DHCP ranges: start and end of networks with an enabled DHCP server.
- Wireless LANs: SSID, enabled, security type, WPA mode and cipher, network
  VLAN, hidden and guest flags. Passphrases and every ``x_*`` field are never
  read.
- Reservations: only clients with a fixed IP (``use_fixedip``): MAC, fixed IP,
  name, hostname and an enabled local DNS record.

Raw payloads are never stored, so secrets do not leave this module.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class InventorySfp:
    """A transceiver module plugged into a UniFi port (internal API)."""

    device_id: str
    port_idx: int
    vendor: str = ""
    part: str = ""
    serial: str = ""
    compliance: str = ""
    revision: str = ""


@dataclass(frozen=True)
class InventoryDhcpRange:
    """The DHCP pool of one UniFi network, by VLAN ID."""

    vlan_id: int
    network_name: str
    start: str
    end: str


@dataclass(frozen=True)
class InventoryWlan:
    """One UniFi wireless network; never carries a passphrase."""

    source_id: str
    ssid: str
    enabled: bool = True
    security: str = ""
    wpa_mode: str = ""
    wpa_enc: str = ""
    vlan_id: int | None = None
    hidden: bool = False
    guest: bool = False


@dataclass(frozen=True)
class InventoryReservation:
    """A UniFi client with a fixed IP address (DHCP reservation)."""

    mac_address: str
    ip_address: str
    name: str = ""
    hostname: str = ""
    dns_name: str = ""


def read_sfps(
    devices: Iterable[object], device_ids_by_mac: Mapping[str, str]
) -> tuple[InventorySfp, ...]:
    """Present SFP modules of internal devices known by MAC."""
    modules: list[InventorySfp] = []
    for device in devices:
        if not isinstance(device, Mapping):
            continue
        device_id = device_ids_by_mac.get(_mac(device.get("mac")))
        table = device.get("port_table")
        if not device_id or not isinstance(table, list):
            continue
        for port in table:
            if not isinstance(port, Mapping) or port.get("sfp_found") is not True:
                continue
            idx = port.get("port_idx")
            if type(idx) is not int or idx < 1:
                continue
            modules.append(
                InventorySfp(
                    device_id=device_id,
                    port_idx=idx,
                    vendor=_text(port.get("sfp_vendor")),
                    part=_text(port.get("sfp_part")),
                    serial=_text(port.get("sfp_serial")),
                    compliance=_text(port.get("sfp_compliance")),
                    revision=_text(port.get("sfp_rev")),
                )
            )
    return tuple(sorted(modules, key=lambda item: (item.device_id, item.port_idx)))


def network_vlans(rows: Iterable[object]) -> dict[str, tuple[int, str]]:
    """(VLAN ID, name) of LAN networks by internal ID.

    A corporate network without VLAN tagging is the default network (VLAN 1).
    """
    networks: dict[str, tuple[int, str]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        network_id = row.get("_id")
        if not isinstance(network_id, str) or not network_id:
            continue
        purpose = row.get("purpose")
        if purpose not in {"corporate", "guest", "vlan-only"}:
            continue
        vlan = row.get("vlan")
        name = _text(row.get("name"))
        if row.get("vlan_enabled") is True and type(vlan) is int and 1 <= vlan <= 4094:
            networks[network_id] = (vlan, name)
        elif row.get("vlan_enabled") is not True and purpose == "corporate":
            networks[network_id] = (1, name)
    return networks


def read_dhcp_ranges(rows: Iterable[object]) -> tuple[InventoryDhcpRange, ...]:
    """DHCP pools of networks whose DHCP server is enabled."""
    rows = tuple(rows)
    vlans = network_vlans(rows)
    ranges: list[InventoryDhcpRange] = []
    for row in rows:
        if not isinstance(row, Mapping) or row.get("dhcpd_enabled") is not True:
            continue
        network = vlans.get(row.get("_id") if isinstance(row.get("_id"), str) else "")
        start = _ipv4(row.get("dhcpd_start"))
        end = _ipv4(row.get("dhcpd_stop"))
        if network is None or not start or not end:
            continue
        if ipaddress.IPv4Address(start) > ipaddress.IPv4Address(end):
            continue
        ranges.append(InventoryDhcpRange(network[0], network[1], start, end))
    return tuple(sorted(ranges, key=lambda item: (item.vlan_id, item.start)))


def read_wlans(
    rows: Iterable[object], networks: Mapping[str, tuple[int, str]]
) -> tuple[InventoryWlan, ...]:
    """Wireless networks from the allow-listed ``rest/wlanconf`` fields."""
    wlans: list[InventoryWlan] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        source_id = row.get("_id")
        ssid = _text(row.get("name"))
        if not isinstance(source_id, str) or not source_id or not ssid:
            continue
        network_id = row.get("networkconf_id")
        network = networks.get(network_id) if isinstance(network_id, str) else None
        wlans.append(
            InventoryWlan(
                source_id=source_id,
                ssid=ssid,
                enabled=row.get("enabled") is not False,
                security=_text(row.get("security")),
                wpa_mode=_text(row.get("wpa_mode")),
                wpa_enc=_text(row.get("wpa_enc")),
                vlan_id=network[0] if network else None,
                hidden=row.get("hide_ssid") is True,
                guest=row.get("is_guest") is True,
            )
        )
    return tuple(sorted(wlans, key=lambda item: item.ssid.lower()))


def read_reservations(rows: Iterable[object]) -> tuple[InventoryReservation, ...]:
    """Clients with a fixed IP; other client data is never kept.

    An IP reserved for more than one client is ambiguous and left out.
    """
    reservations: dict[str, InventoryReservation] = {}
    duplicates: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping) or row.get("use_fixedip") is not True:
            continue
        address = _ipv4(row.get("fixed_ip"))
        mac = _mac(row.get("mac"))
        if not address or not mac:
            continue
        dns = (
            _text(row.get("local_dns_record"))
            if row.get("local_dns_record_enabled") is True
            else ""
        )
        if address in reservations:
            duplicates.add(address)
        reservations[address] = InventoryReservation(
            mac_address=":".join(mac[i : i + 2] for i in range(0, 12, 2)).upper(),
            ip_address=address,
            name=_text(row.get("name")),
            hostname=_text(row.get("hostname")),
            dns_name=dns,
        )
    return tuple(
        sorted(
            (item for ip, item in reservations.items() if ip not in duplicates),
            key=lambda item: ipaddress.IPv4Address(item.ip_address),
        )
    )


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _ipv4(value: object) -> str:
    try:
        return str(ipaddress.IPv4Address(_text(value)))
    except ValueError:
        return ""


def _mac(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = "".join(ch for ch in value.lower() if ch in "0123456789abcdef")
    return text if len(text) == 12 else ""
