"""Resolve UniFi port configuration from the internal Network API (read-only).

The official Integration API has no port names, configured enable state,
profiles or VLAN membership (see ``docs/API_CAPABILITIES.md``). This module
turns the allow-listed fields of the internal ``stat/device``, ``rest/portconf``
and ``rest/networkconf`` payloads into an effective configuration per port.

Rules (validated against UniFi Network 11.0):

- A port with an assigned profile (``portconf_id``) takes forwarding, native
  network and tagging from that profile; otherwise the port entry already holds
  its override values.
- ``forward``: ``disabled`` (port off), ``native`` (access), ``all`` (native
  plus every VLAN), ``customize`` with ``tagged_vlan_mgmt`` ``auto`` (all),
  ``block_all`` (access) or ``custom`` (all networks except the excluded ones).
- Trunks that carry every VLAN stay the explicit mode ``tagged-all``; they are
  never expanded into VLAN lists, so new UniFi networks keep being carried.
- A trunk without a native network carries the UniFi default network (VLAN 1)
  untagged.
- Unknown profiles, networks or forwarding values produce mode ``unknown`` with
  a note instead of a guess.

Only the fields read here leave the raw payloads; network secrets such as WAN
credentials are never copied into models, snapshots or exports.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

DISABLED = "disabled"
ACCESS = "access"
TAGGED = "tagged"
TAGGED_ALL = "tagged-all"
UNKNOWN = "unknown"

# Network purposes that can be carried on switch ports.
_PORT_PURPOSES = {"corporate", "guest", "vlan-only"}


@dataclass(frozen=True)
class InventoryPortConfig:
    """Effective configuration of one UniFi port (internal API, read-only).

    ``enabled`` is the configured state, not the link state: a disabled port is
    switched off in UniFi, a port that is only down is still enabled.
    """

    device_id: str
    idx: int
    name: str = ""
    enabled: bool | None = None
    mode: str = UNKNOWN
    native_vid: int | None = None
    tagged_vids: tuple[int, ...] = ()
    profile: str = ""
    lag_id: int | None = None
    notes: tuple[str, ...] = ()

    def summary(self) -> str:
        """Short text such as 'access 20' or 'tagged-all, native 1'."""
        if self.mode == DISABLED:
            return "disabled"
        if self.mode == UNKNOWN:
            return "unknown"
        native = "" if self.native_vid is None else str(self.native_vid)
        if self.mode == ACCESS:
            return f"access {native}".strip()
        text = (
            TAGGED_ALL
            if self.mode == TAGGED_ALL
            else "tagged " + ",".join(str(vid) for vid in self.tagged_vids)
        )
        if self.mode == TAGGED and not self.tagged_vids:
            text = "tagged none"
        return f"{text}, native {native}" if native else text


@dataclass(frozen=True)
class _Network:
    vid: int
    default: bool


def allowed_networks(rows: Iterable[object]) -> dict[str, _Network]:
    """VLAN IDs of port-capable networks; reads ``_id``, purpose and VLAN only."""
    networks: dict[str, _Network] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        network_id = row.get("_id")
        if not isinstance(network_id, str) or not network_id:
            continue
        if row.get("purpose") not in _PORT_PURPOSES:
            continue
        vlan = row.get("vlan")
        if row.get("vlan_enabled") is True and type(vlan) is int and 1 <= vlan <= 4094:
            networks[network_id] = _Network(vlan, False)
        elif row.get("vlan_enabled") is not True and row.get("purpose") == "corporate":
            networks[network_id] = _Network(1, True)
    return networks


def allowed_profiles(rows: Iterable[object]) -> dict[str, dict[str, object]]:
    """Port profiles reduced to the fields that decide VLAN membership."""
    profiles: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        profile_id = row.get("_id")
        if isinstance(profile_id, str) and profile_id:
            profiles[profile_id] = {key: row.get(key) for key in _VLAN_FIELDS} | {
                "name": row.get("name") if isinstance(row.get("name"), str) else ""
            }
    return profiles


_VLAN_FIELDS = (
    "forward",
    "native_networkconf_id",
    "tagged_vlan_mgmt",
    "excluded_networkconf_ids",
)


def resolve_port_configs(
    devices: Iterable[object],
    profiles: Mapping[str, Mapping[str, object]],
    networks: Mapping[str, _Network],
    device_ids_by_mac: Mapping[str, str],
) -> tuple[InventoryPortConfig, ...]:
    """Effective port configuration for internal devices known by MAC."""
    defaults = [network.vid for network in networks.values() if network.default]
    default_vid = defaults[0] if len(defaults) == 1 else None
    taggable = sorted({n.vid for n in networks.values() if not n.default})
    configs: list[InventoryPortConfig] = []
    for device in devices:
        if not isinstance(device, Mapping):
            continue
        device_id = device_ids_by_mac.get(_mac(device.get("mac")))
        table = device.get("port_table")
        if not device_id or not isinstance(table, list):
            continue
        entries = [p for p in table if isinstance(p, Mapping) and _idx(p) is not None]
        masters = {
            value
            for p in entries
            if type(value := p.get("aggregated_by")) is int and value > 0
        }
        for port in entries:
            configs.append(
                _resolve(
                    device_id,
                    port,
                    profiles,
                    networks,
                    default_vid,
                    taggable,
                    masters,
                )
            )
    return tuple(sorted(configs, key=lambda item: (item.device_id, item.idx)))


def _resolve(
    device_id: str,
    port: Mapping[str, object],
    profiles: Mapping[str, Mapping[str, object]],
    networks: Mapping[str, _Network],
    default_vid: int | None,
    taggable: list[int],
    masters: set[int],
) -> InventoryPortConfig:
    idx = _idx(port) or 0
    notes: list[str] = []
    name = port.get("name") if isinstance(port.get("name"), str) else ""
    enable = port.get("enable")
    enabled = enable if isinstance(enable, bool) else None
    aggregated = port.get("aggregated_by")
    lag_id = (
        aggregated
        if type(aggregated) is int and aggregated > 0
        else (idx if idx in masters else None)
    )

    source: Mapping[str, object] = port
    profile_name = ""
    profile_id = port.get("portconf_id")
    if isinstance(profile_id, str) and profile_id:
        profile = profiles.get(profile_id)
        if profile is None:
            notes.append("Assigned port profile is unknown.")
            return InventoryPortConfig(
                device_id,
                idx,
                name,
                enabled,
                UNKNOWN,
                None,
                (),
                "",
                lag_id,
                tuple(notes),
            )
        source = profile
        profile_name = str(profile.get("name") or "")

    forward = source.get("forward")
    native_id = source.get("native_networkconf_id")
    native_vid: int | None = None
    if isinstance(native_id, str) and native_id:
        network = networks.get(native_id)
        if network is None:
            notes.append("Native network is unknown.")
        else:
            native_vid = network.vid

    mode = UNKNOWN
    tagged: tuple[int, ...] = ()
    if forward == "disabled":
        mode, native_vid = DISABLED, None
        enabled = False
    elif forward == "native":
        mode = ACCESS
    elif forward == "all":
        mode = TAGGED_ALL
    elif forward == "customize":
        rule = source.get("tagged_vlan_mgmt")
        if rule == "auto":
            mode = TAGGED_ALL
        elif rule == "block_all":
            mode = ACCESS
        elif rule == "custom":
            excluded = source.get("excluded_networkconf_ids")
            if not isinstance(excluded, list):
                excluded = []
            unknown = [x for x in excluded if x not in networks]
            if unknown:
                notes.append(f"{len(unknown)} excluded networks are unknown.")
            skip = {networks[x].vid for x in excluded if x in networks}
            mode = TAGGED
            tagged = tuple(v for v in taggable if v not in skip and v != native_vid)
        else:
            notes.append(f"Unknown VLAN tagging rule '{rule}'.")
    else:
        notes.append(f"Unknown forwarding mode '{forward}'.")

    if mode in (TAGGED_ALL, TAGGED) and native_vid is None and not native_id:
        # UniFi carries the default network untagged when none is chosen.
        native_vid = default_vid
    if mode == ACCESS and native_vid is None and not native_id:
        notes.append("Access port without a native network.")
    return InventoryPortConfig(
        device_id,
        idx,
        name,
        enabled,
        mode,
        native_vid,
        tagged,
        profile_name,
        lag_id,
        tuple(notes),
    )


def _idx(port: Mapping[str, object]) -> int | None:
    value = port.get("port_idx")
    return value if type(value) is int and value > 0 else None


def _mac(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = "".join(ch for ch in value.lower() if ch in "0123456789abcdef")
    return text if len(text) == 12 else ""
