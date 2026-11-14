"""Physical link evidence between UniFi devices (internal API, read-only).

Two independent observations are read from the internal ``stat/device``
payload:

- ``uplink``: a device names the MAC of its upstream device, the remote port
  number (``uplink_remote_port``) and usually its own port (``port_idx``);
- ``lldp_table``: per local port, the neighbor's chassis MAC and a port ID such
  as ``Port 25`` or ``local Port 3``; a MAC-style port ID leaves the remote
  port open.

Only neighbors that are UniFi devices of the same site (known by MAC) become
links; MAC addresses are resolved to official device IDs right here and are
not stored. A port number that cannot be read stays ``None``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

UPLINK = "uplink"
LLDP = "lldp"

_PORT_ID = re.compile(r"^(?:local\s+)?port\s+(\d+)$", re.IGNORECASE)


@dataclass(frozen=True)
class InventoryLink:
    """One observation that ``device_id`` port ``port_idx`` reaches a peer."""

    device_id: str
    port_idx: int | None
    peer_device_id: str
    peer_port_idx: int | None
    source: str


def read_links(
    devices: Iterable[object], device_ids_by_mac: Mapping[str, str]
) -> tuple[InventoryLink, ...]:
    links: set[InventoryLink] = set()
    for device in devices:
        if not isinstance(device, Mapping):
            continue
        device_id = device_ids_by_mac.get(_mac(device.get("mac")))
        if not device_id:
            continue
        uplink = device.get("uplink")
        if isinstance(uplink, Mapping) and uplink.get("type") == "wire":
            peer = device_ids_by_mac.get(_mac(uplink.get("uplink_mac")))
            remote = _positive(uplink.get("uplink_remote_port"))
            if peer and peer != device_id and remote is not None:
                links.add(
                    InventoryLink(
                        device_id,
                        _positive(uplink.get("port_idx")),
                        peer,
                        remote,
                        UPLINK,
                    )
                )
        table = device.get("lldp_table")
        for entry in table if isinstance(table, list) else ():
            if not isinstance(entry, Mapping) or entry.get("is_wired") is False:
                continue
            peer = device_ids_by_mac.get(_mac(entry.get("chassis_id")))
            local = _positive(entry.get("local_port_idx"))
            if not peer or peer == device_id or local is None:
                continue
            links.add(
                InventoryLink(
                    device_id, local, peer, _port_id(entry.get("port_id")), LLDP
                )
            )
    return tuple(
        sorted(
            links,
            key=lambda link: (
                link.device_id,
                link.port_idx or 0,
                link.peer_device_id,
                link.peer_port_idx or 0,
                link.source,
            ),
        )
    )


def _port_id(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    match = _PORT_ID.match(value.strip())
    return int(match.group(1)) if match and int(match.group(1)) > 0 else None


def _positive(value: object) -> int | None:
    return value if type(value) is int and value > 0 else None


def _mac(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = "".join(ch for ch in value.lower() if ch in "0123456789abcdef")
    return text if len(text) == 12 else ""
