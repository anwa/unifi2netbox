"""Plan NetBox interface configuration from the effective UniFi port config.

For each matched device, UniFi ports are paired with NetBox interfaces (see
``ports.py``) and compared field by field:

- ``enabled``: the configured UniFi state (never the link state),
- ``mode``: ``access``, ``tagged`` or ``tagged-all``,
- ``untagged_vlan``: the native VLAN,
- ``tagged_vlans``: the explicit list for ``tagged`` ports; ``tagged-all``
  ports carry no list, and leftovers are cleared for non-``tagged`` modes.

VLANs are looked up in the site's "UniFi <site>" VLAN group, so networks must
be written to NetBox first. Missing source values never clear NetBox values,
unknown configurations only produce notes, and LAG membership is shown but not
written (NetBox LAG interfaces are not created automatically).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace

from unifi2netbox.inventory import InventoryInterface, InventoryPort, InventoryVlan
from unifi2netbox.port_config import (
    ACCESS,
    DISABLED,
    TAGGED,
    TAGGED_ALL,
    InventoryPortConfig,
)
from unifi2netbox.ports import match_ports

ENABLED = "enabled"
MODE = "mode"
UNTAGGED = "untagged_vlan"
TAGGED_VLANS = "tagged_vlans"
DESCRIPTION = "description"
SPEED = "speed"
DUPLEX = "duplex"
POE_MODE = "poe_mode"
POE_TYPE = "poe_type"
FIELDS = (
    ENABLED,
    MODE,
    UNTAGGED,
    TAGGED_VLANS,
    DESCRIPTION,
    SPEED,
    DUPLEX,
    POE_MODE,
    POE_TYPE,
)
FIELD_LABELS = {
    ENABLED: "Enabled",
    MODE: "802.1Q mode",
    UNTAGGED: "Untagged VLAN",
    TAGGED_VLANS: "Tagged VLANs",
    DESCRIPTION: "Description",
    SPEED: "Speed",
    DUPLEX: "Duplex",
    POE_MODE: "PoE mode",
    POE_TYPE: "PoE type",
}
# Fields that need another field written with them: VLANs need the 802.1Q
# mode, a PoE type needs the PoE mode (NetBox validation).
_REQUIRES = {UNTAGGED: MODE, TAGGED_VLANS: MODE, POE_TYPE: POE_MODE}
_NEEDS_MODE = (UNTAGGED, TAGGED_VLANS)
# Official UniFi PoE type (1-4) to the NetBox PoE type choice.
POE_TYPES = {
    1: "type1-ieee802.3af",
    2: "type2-ieee802.3at",
    3: "type3-ieee802.3bt",
    4: "type4-ieee802.3bt",
}
_DEFAULT_NAME = re.compile(r"(Port|SFP\+?|SFP28) ?\d+", re.IGNORECASE)


@dataclass(frozen=True)
class DevicePair:
    device_key: str
    device_name: str
    unifi_id: str
    netbox_id: str


@dataclass(frozen=True)
class FieldChange:
    field: str
    current: object
    desired: object
    current_label: str
    desired_label: str


@dataclass(frozen=True)
class InterfacePlanRow:
    key: str
    device_key: str
    device_name: str
    unifi_device_id: str
    port_idx: int
    port_name: str
    interface_id: str
    interface_name: str
    config: InventoryPortConfig
    changes: tuple[FieldChange, ...] = ()
    selected_fields: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return f"{self.device_name} {self.interface_name}"

    @property
    def in_sync(self) -> bool:
        return not self.changes

    def change(self, field: str) -> FieldChange | None:
        return next((c for c in self.changes if c.field == field), None)

    def selected_changes(self) -> tuple[FieldChange, ...]:
        return tuple(c for c in self.changes if c.field in self.selected_fields)


@dataclass(frozen=True)
class InterfacePlan:
    rows: tuple[InterfacePlanRow, ...] = ()
    blocker: str = ""

    def selected_rows(self) -> tuple[InterfacePlanRow, ...]:
        return tuple(row for row in self.rows if row.selected_fields)

    @property
    def operation_count(self) -> int:
        return len(self.selected_rows())


def build_interface_plan(
    pairs: Iterable[DevicePair],
    ports: Iterable[InventoryPort],
    interfaces: Iterable[InventoryInterface],
    configs: Iterable[InventoryPortConfig],
    vlans: Iterable[InventoryVlan],
    *,
    vlan_group_id: str,
    vlan_group_name: str,
    port_config_error: str = "",
) -> InterfacePlan:
    configs = tuple(configs)
    if not configs:
        return InterfacePlan(
            blocker=port_config_error or "No UniFi port configuration was read."
        )
    ports = tuple(ports)
    interfaces = tuple(interfaces)
    config_by_port = {(c.device_id, c.idx): c for c in configs}
    group_vlans = [v for v in vlans if vlan_group_id and v.group_id == vlan_group_id]
    vlan_by_vid = {v.vid: v for v in group_vlans}
    vlan_names = {v.source_id: f"VLAN {v.vid} {v.name}".strip() for v in vlans}
    missing_group = (
        ""
        if vlan_group_id
        else f"VLAN group '{vlan_group_name}' is not in NetBox yet; write the "
        "networks first and refresh."
    )
    rows: list[InterfacePlanRow] = []
    for pair in pairs:
        device_ports = [p for p in ports if p.device_id == pair.unifi_id]
        device_interfaces = [i for i in interfaces if i.device_id == pair.netbox_id]
        if not device_ports or not device_interfaces:
            continue
        for match in match_ports(device_ports, device_interfaces):
            if match.port is None or match.interface is None:
                continue
            config = config_by_port.get((pair.unifi_id, match.port.idx))
            if config is None:
                continue
            rows.append(
                _plan_row(
                    pair,
                    match.interface,
                    config,
                    vlan_by_vid,
                    vlan_names,
                    missing_group,
                    match.port,
                )
            )
    return InterfacePlan(rows=tuple(rows))


def _plan_row(
    pair: DevicePair,
    interface: InventoryInterface,
    config: InventoryPortConfig,
    vlan_by_vid: dict[int, InventoryVlan],
    vlan_names: dict[str, str],
    missing_group: str,
    port: InventoryPort | None = None,
) -> InterfacePlanRow:
    changes: list[FieldChange] = []
    notes = list(config.notes)
    # Fields whose NetBox value is set but differs: shown, not preselected.
    keep: set[str] = set()

    def add(field: str, current: object, desired: object) -> None:
        if current != desired:
            changes.append(
                FieldChange(
                    field,
                    current,
                    desired,
                    _label(field, current, vlan_names),
                    _label(field, desired, vlan_names),
                )
            )

    if config.enabled is not None:
        add(ENABLED, interface.enabled, config.enabled)
    if config.lag_id is not None:
        notes.append(
            f"LAG {config.lag_id} is shown only; NetBox LAG interfaces are not "
            "created or assigned."
        )
    if config.mode in (ACCESS, TAGGED, TAGGED_ALL):
        add(MODE, interface.mode, config.mode)
        vlan_note = missing_group
        if config.native_vid is not None and not missing_group:
            vlan = vlan_by_vid.get(config.native_vid)
            if vlan is None:
                vlan_note = f"VLAN {config.native_vid} is not in NetBox yet."
            else:
                add(UNTAGGED, interface.untagged_vlan_id, vlan.source_id)
        if config.mode == TAGGED and not missing_group:
            missing = [v for v in config.tagged_vids if v not in vlan_by_vid]
            if missing:
                vlan_note = (
                    f"Tagged VLANs {', '.join(map(str, missing))} are not in "
                    "NetBox yet; the tagged list is not written."
                )
            else:
                desired = tuple(
                    sorted(
                        (vlan_by_vid[v].source_id for v in config.tagged_vids),
                        key=_numeric,
                    )
                )
                add(TAGGED_VLANS, interface.tagged_vlan_ids, desired)
        elif interface.tagged_vlan_ids:
            # NetBox drops tagged VLANs outside "tagged" mode; show it.
            add(TAGGED_VLANS, interface.tagged_vlan_ids, ())
        if vlan_note:
            notes.append(vlan_note)
    elif config.mode != DISABLED:
        notes.append("Port configuration is unknown; only the enable state is used.")

    name = config.name.strip()
    if name and not _DEFAULT_NAME.fullmatch(name):
        add(DESCRIPTION, interface.description, name)
        if interface.description and interface.description != name:
            keep.add(DESCRIPTION)
            notes.append(
                "NetBox has another description; it is replaced only when checked."
            )
    if config.speed_mbps is not None:
        add(SPEED, interface.speed_kbps, config.speed_mbps * 1000)
        if config.full_duplex is not None:
            add(DUPLEX, interface.duplex, "full" if config.full_duplex else "half")
    if port is not None and port.poe_standard:
        poe_type = POE_TYPES.get(port.poe_type, "")
        add(POE_MODE, interface.poe_mode, "pse")
        if poe_type:
            add(POE_TYPE, interface.poe_type, poe_type)
        for field, current in (
            (POE_MODE, interface.poe_mode),
            (POE_TYPE, interface.poe_type),
        ):
            if current and any(c.field == field for c in changes):
                keep.add(field)
        if keep & {POE_MODE, POE_TYPE}:
            notes.append(
                "NetBox has other PoE values (often from the device type); they "
                "are replaced only when checked."
            )

    return InterfacePlanRow(
        key=f"interface:{interface.source_id}",
        device_key=pair.device_key,
        device_name=pair.device_name,
        unifi_device_id=pair.unifi_id,
        port_idx=config.idx,
        port_name=config.name,
        interface_id=interface.source_id,
        interface_name=interface.name,
        config=config,
        changes=tuple(changes),
        selected_fields=tuple(c.field for c in changes if c.field not in keep),
        notes=tuple(notes),
    )


def select_interface(
    plan: InterfacePlan, key: str, field: str, selected: bool
) -> InterfacePlan:
    """Select or clear one field (or "all") of one interface row.

    VLAN fields depend on the mode change and the PoE type on the PoE mode:
    clearing the required field clears its dependents, and selecting a
    dependent selects the required change too.
    """
    rows = []
    for row in plan.rows:
        if row.key == key:
            available = [c.field for c in row.changes]
            chosen = set(row.selected_fields)
            targets = available if field == "all" else [field]
            for name in targets:
                if name not in available:
                    continue
                if selected:
                    chosen.add(name)
                    required = _REQUIRES.get(name)
                    if required in available:
                        chosen.add(required)
                else:
                    chosen.discard(name)
                    chosen.difference_update(
                        f for f, needed in _REQUIRES.items() if needed == name
                    )
            row = replace(row, selected_fields=tuple(f for f in FIELDS if f in chosen))
        rows.append(row)
    return replace(plan, rows=tuple(rows))


def _label(field: str, value: object, vlan_names: dict[str, str]) -> str:
    if field == ENABLED:
        return "enabled" if value else "disabled"
    if field == MODE:
        return str(value) or "-"
    if field == UNTAGGED:
        return _vlan_label(str(value), vlan_names) if value else "-"
    if field == TAGGED_VLANS:
        values = tuple(value) if isinstance(value, tuple) else ()
        return ", ".join(_vlan_label(v, vlan_names) for v in values) or "-"
    if field == SPEED:
        if not value:
            return "-"
        mbps = int(str(value)) // 1000
        return f"{mbps // 1000} Gbps" if mbps >= 1000 else f"{mbps} Mbps"
    return str(value) or "-"


def _vlan_label(vlan_id: str, names: dict[str, str]) -> str:
    return names.get(vlan_id) or f"NetBox VLAN ID {vlan_id}"


def _numeric(value: str) -> tuple[int, str]:
    return (int(value), "") if value.isdigit() else (0, value)
