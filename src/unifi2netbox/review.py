"""Qt-free state behind the review window.

``ReviewState`` holds the current difference preview, the user's device and
field selection, per-row create choices (type, role, site, status) and the
latest write outcomes. It rebuilds the change preview and write plan whenever
the selection changes, so the GUI only renders what this class reports.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from unifi2netbox.cables import CablePlan, CablePlanRow, select_cable
from unifi2netbox.config import BehaviorConfig
from unifi2netbox.details import InventorySfp
from unifi2netbox.disks import DiskPlan, DiskPlanRow, select_disk
from unifi2netbox.interface_plan import (
    InterfacePlan,
    InterfacePlanRow,
    select_interface,
)
from unifi2netbox.inventory import InventoryDisk
from unifi2netbox.networks import NetworkPlan, NetworkPlanRow, select_network
from unifi2netbox.pipeline import (
    InventoryPreviewResult,
    InventoryPreviewRow,
    WriteExecutionReport,
    WriteOutcome,
    preview_rows,
)
from unifi2netbox.port_config import InventoryPortConfig
from unifi2netbox.ports import PortMatch, match_ports
from unifi2netbox.preview import (
    ChangePreview,
    DeviceAction,
    DevicePreview,
    DifferencePreview,
    FieldPreview,
    build_change_preview,
    select_device,
    select_field,
)
from unifi2netbox.write_plan import (
    OperationType,
    WritePlan,
    WritePlanSummary,
    build_write_plan,
)

CREATE = "create"
UPDATE = "update"
IN_SYNC = "in_sync"
NETBOX_ONLY = "netbox_only"
ATTENTION = "attention"
NETWORKS = "networks"
INTERFACES = "interfaces"
CABLES = "cables"
ALL = "all"

CATEGORY_LABELS = {
    ALL: "All",
    CREATE: "New",
    UPDATE: "Changed",
    IN_SYNC: "In sync",
    ATTENTION: "Needs attention",
    NETBOX_ONLY: "NetBox only",
    NETWORKS: "Networks",
    INTERFACES: "Interfaces",
    CABLES: "Cables",
}

FIELD_LABELS = {
    "name": "Name",
    "manufacturer": "Manufacturer",
    "model": "Model",
    "serial": "Serial number",
    "site": "Site",
    "mac_address": "MAC address",
}


@dataclass(frozen=True)
class ReviewRow:
    """One display row: the preview row plus review-specific facts."""

    row: InventoryPreviewRow
    device: DevicePreview
    category: str
    selected: bool
    attention: bool
    note: str
    outcome: WriteOutcome | None

    @property
    def key(self) -> str:
        return self.row.device_key

    @property
    def name(self) -> str:
        return self.row.source_label or self.row.target_label or self.row.device_key

    def field(self, name: str) -> FieldPreview | None:
        return next((f for f in self.device.fields if f.name == name), None)

    def source_value(self, name: str) -> str:
        field = self.field(name)
        return field.source_value if field else ""

    def target_value(self, name: str) -> str:
        field = self.field(name)
        return field.target_value if field else ""


class ReviewState:
    def __init__(
        self,
        result: InventoryPreviewResult | None = None,
        behavior: BehaviorConfig | None = None,
    ) -> None:
        self.result = result
        self.behavior = behavior or BehaviorConfig()
        self.diff: DifferencePreview | None = (
            result.difference_preview if result else None
        )
        self.netbox_sites = frozenset(result.netbox_sites) if result else frozenset()
        self.device_types: tuple[tuple[str, str, str], ...] = (
            result.netbox_device_types if result else ()
        )
        self.roles: tuple[str, ...] = result.netbox_device_roles if result else ()
        self.sites: tuple[str, ...] = result.netbox_sites if result else ()
        self.statuses: tuple[str, ...] = result.netbox_device_statuses if result else ()
        self.type_by_key: dict[str, str] = {}
        self.role_by_key: dict[str, str] = {}
        self.site_by_key: dict[str, str] = {}
        self.status_by_key: dict[str, str] = {}
        self.unifi_ports = result.unifi_ports if result else ()
        self.netbox_interfaces = result.netbox_interfaces if result else ()
        self.unifi_port_configs = result.unifi_port_configs if result else ()
        self.port_config_error = result.port_config_error if result else ""
        self.network_plan: NetworkPlan | None = result.network_plan if result else None
        self.network_outcomes: dict[str, list[WriteOutcome]] = {}
        self.interface_plan: InterfacePlan | None = (
            result.interface_plan if result else None
        )
        self.cable_plan: CablePlan | None = result.cable_plan if result else None
        self.disk_plan: DiskPlan | None = result.disk_plan if result else None
        self.protect_kinds: dict[str, str] = {
            device.source_id: device.kind
            for device in (result.protect_devices if result else ())
        }
        self.protect_states: dict[str, str] = {
            device.source_id: device.state
            for device in (result.protect_devices if result else ())
        }
        self.access_kinds: dict[str, str] = {
            device.source_id: device.kind
            for device in (result.access_devices if result else ())
        }
        self.access_states: dict[str, str] = {
            device.source_id: device.state
            for device in (result.access_devices if result else ())
        }
        self.drive_states: dict[str, str] = {
            device.source_id: device.state
            for device in (result.drive_devices if result else ())
        }
        self.drive_disks: tuple[InventoryDisk, ...] = (
            result.drive_disks if result else ()
        )
        self.outcomes: dict[str, WriteOutcome] = {}
        self.last_report: WriteExecutionReport | None = None
        self._suggestions = {
            row.device_key: (row.suggested_device_types, row.suggested_device_type_id)
            for row in (result.rows if result else ())
        }
        self._recompute()
        self._init_create_choices()

    # -- derived state -------------------------------------------------------

    @property
    def ready(self) -> bool:
        return self.diff is not None and self.plan is not None

    def _recompute(self) -> None:
        if self.diff is None:
            self.change: ChangePreview | None = None
            self.plan: WritePlan | None = (
                self.result.write_plan if self.result else None
            )
            self._rows = tuple(self.result.rows) if self.result else ()
            return
        catalog = self.netbox_sites or None
        self.change = build_change_preview(self.diff)
        self.plan = build_write_plan(self.diff, self.change, netbox_sites=catalog)
        rows = preview_rows(self.diff, self.change, self.plan)
        self._rows = tuple(
            replace(
                row,
                suggested_device_types=self._suggestions.get(row.device_key, ("", ""))[
                    0
                ],
                suggested_device_type_id=self._suggestions.get(
                    row.device_key, ("", "")
                )[1],
            )
            for row in rows
        )

    def _init_create_choices(self) -> None:
        default_role = self.behavior.default_device_role_name.strip()
        types_by_name: dict[tuple[str, str], list[str]] = {}
        for type_id, manufacturer, model in self.device_types:
            types_by_name.setdefault(
                (manufacturer.strip().lower(), model.strip().lower()), []
            ).append(type_id)
        for item in self.rows():
            if item.category != CREATE:
                continue
            key = item.key
            exact = types_by_name.get(
                (
                    item.source_value("manufacturer").lower(),
                    item.source_value("model").lower(),
                ),
                [],
            )
            if len(exact) == 1:
                self.type_by_key[key] = exact[0]
            elif item.row.suggested_device_type_id:
                self.type_by_key[key] = item.row.suggested_device_type_id
            if "active" in self.statuses:
                self.status_by_key[key] = "active"
            elif self.statuses:
                self.status_by_key[key] = self.statuses[0]
            source_site = item.source_value("site")
            if source_site and source_site in self.sites:
                self.site_by_key[key] = source_site
            elif self.sites:
                self.site_by_key[key] = self.sites[0]
            kind = self.source_kind(key)
            if kind:
                # Cameras, NVRs and Access hardware never inherit the default
                # (network) role; without a fitting role the choice stays open.
                kind_role = role_for_kind(kind, self.roles)
                if kind_role:
                    self.role_by_key[key] = kind_role
            elif default_role and default_role in self.roles:
                self.role_by_key[key] = default_role
            elif self.roles:
                self.role_by_key[key] = self.roles[0]

    def rows(self, category: str = ALL, text: str = "") -> tuple[ReviewRow, ...]:
        devices = {d.device_key: d for d in self.diff.devices} if self.diff else {}
        needle = text.strip().lower()
        result: list[ReviewRow] = []
        for row in self._rows:
            device = devices.get(row.device_key)
            if device is None:
                continue
            item = self._review_row(row, device)
            if category == ATTENTION:
                if not item.attention:
                    continue
            elif category != ALL and item.category != category:
                continue
            if needle and needle not in _search_text(item):
                continue
            result.append(item)
        return tuple(result)

    def _review_row(self, row: InventoryPreviewRow, device: DevicePreview) -> ReviewRow:
        category = _category(device)
        selected = device.selected
        executable = row.executable == "Yes"
        note = ""
        attention = False
        if category in (CREATE, UPDATE) and selected:
            if not executable:
                attention = True
                note = friendly_reason(row.blocked_reason)
            elif row.blocked_reason:
                attention = True
                note = row.blocked_reason
            elif category == CREATE and not self.type_by_key.get(row.device_key):
                note = "Choose a device type"
                attention = True
        if category == CREATE and selected and not self.role_by_key.get(row.device_key):
            attention = True
            note = note or "Choose a device role"
        outcome = self.outcomes.get(row.device_key)
        return ReviewRow(
            row=row,
            device=device,
            category=category,
            selected=selected,
            attention=attention,
            note=note,
            outcome=outcome,
        )

    def row(self, key: str) -> ReviewRow | None:
        return next((item for item in self.rows() if item.key == key), None)

    def counts(self) -> dict[str, int]:
        items = self.rows()
        counts = {name: 0 for name in CATEGORY_LABELS}
        counts[ALL] = len(items)
        for item in items:
            counts[item.category] += 1
            counts[ATTENTION] += int(item.attention)
        counts[NETWORKS] = len(self.network_rows())
        counts[INTERFACES] = len(self.interface_rows())
        counts[CABLES] = len(self.cable_rows())
        return counts

    # -- networks -----------------------------------------------------------

    def network_rows(self, text: str = "") -> tuple[NetworkPlanRow, ...]:
        if self.network_plan is None:
            return ()
        needle = text.strip().lower()
        return tuple(
            row
            for row in self.network_plan.rows
            if not needle or needle in f"{row.name} {row.vid} {row.subnet}".lower()
        )

    def network_row(self, key: str) -> NetworkPlanRow | None:
        return next((row for row in self.network_rows() if row.key == key), None)

    def network_changes(self) -> int:
        return sum(
            1
            for row in self.network_rows()
            if row.enabled and row.category != "in_sync"
        )

    def network_operation_count(self) -> int:
        return self.network_plan.operation_count if self.network_plan else 0

    def set_network_selected(self, key: str, part: str, selected: bool) -> None:
        if self.network_plan is not None:
            self.network_plan = select_network(self.network_plan, key, part, selected)

    # -- interfaces ---------------------------------------------------------

    def interface_rows(self, text: str = "") -> tuple[InterfacePlanRow, ...]:
        if self.interface_plan is None:
            return ()
        needle = text.strip().lower()
        return tuple(
            row
            for row in self.interface_plan.rows
            if not needle
            or needle
            in f"{row.device_name} {row.interface_name} {row.port_name} "
            f"{row.config.summary()}".lower()
        )

    def interface_row(self, key: str) -> InterfacePlanRow | None:
        return next((row for row in self.interface_rows() if row.key == key), None)

    def interface_changes(self) -> int:
        return sum(1 for row in self.interface_rows() if not row.in_sync)

    def interface_operation_count(self) -> int:
        return self.interface_plan.operation_count if self.interface_plan else 0

    def set_interface_selected(self, key: str, field: str, selected: bool) -> None:
        if self.interface_plan is not None:
            self.interface_plan = select_interface(
                self.interface_plan, key, field, selected
            )

    def protect_kind(self, key: str) -> str:
        """'camera' or 'nvr' for devices that come from UniFi Protect."""
        unifi_id, _ = _device_ids(key)
        if not unifi_id.startswith(PROTECT_PREFIX):
            return ""
        return self.protect_kinds.get(unifi_id[len(PROTECT_PREFIX) :], "") or "device"

    def protect_state(self, key: str) -> str:
        """Operational Protect state, e.g. 'CONNECTED'; display only."""
        unifi_id, _ = _device_ids(key)
        if not unifi_id.startswith(PROTECT_PREFIX):
            return ""
        return self.protect_states.get(unifi_id[len(PROTECT_PREFIX) :], "")

    def access_kind(self, key: str) -> str:
        """'hub', 'reader', 'intercom' or 'access' for UniFi Access devices."""
        unifi_id, _ = _device_ids(key)
        if not unifi_id.startswith(ACCESS_PREFIX):
            return ""
        return self.access_kinds.get(unifi_id[len(ACCESS_PREFIX) :], "") or "access"

    def access_state(self, key: str) -> str:
        """Operational Access state ('online'/'offline'); display only."""
        unifi_id, _ = _device_ids(key)
        if not unifi_id.startswith(ACCESS_PREFIX):
            return ""
        return self.access_states.get(unifi_id[len(ACCESS_PREFIX) :], "")

    def drive_id(self, key: str) -> str:
        """UNAS source ID for devices that come from UniFi Drive, else ''."""
        unifi_id, _ = _device_ids(key)
        if not unifi_id.startswith(DRIVE_PREFIX):
            return ""
        return unifi_id[len(DRIVE_PREFIX) :]

    def disks_for(self, key: str) -> tuple[InventoryDisk, ...]:
        """Drive bays of a UNAS row (display only), ordered by slot."""
        device_id = self.drive_id(key)
        if not device_id:
            return ()
        disks = [d for d in self.drive_disks if d.device_id == device_id]
        return tuple(sorted(disks, key=lambda d: (len(d.slot), d.slot)))

    def source_kind(self, key: str) -> str:
        """Kind of a device from an optional UniFi application, else ''."""
        return (
            self.access_kind(key)
            or self.protect_kind(key)
            or ("nas" if self.drive_id(key) else "")
        )

    def source_origin(self, key: str) -> tuple[str, str, str]:
        """(application, kind, state) for optional-source devices, else empty."""
        if kind := self.access_kind(key):
            return "UniFi Access", kind, self.access_state(key)
        if kind := self.protect_kind(key):
            return "UniFi Protect", kind, self.protect_state(key)
        if device_id := self.drive_id(key):
            return "UniFi Drive", "nas", self.drive_states.get(device_id, "")
        return "", "", ""

    # -- cables -------------------------------------------------------------

    def cable_rows(self, text: str = "") -> tuple[CablePlanRow, ...]:
        if self.cable_plan is None:
            return ()
        needle = text.strip().lower()
        return tuple(row for row in self.cable_plan.rows if needle in row.label.lower())

    def cable_row(self, key: str) -> CablePlanRow | None:
        return next((row for row in self.cable_rows() if row.key == key), None)

    def cable_changes(self) -> int:
        return sum(1 for row in self.cable_rows() if row.selectable)

    def cable_operation_count(self) -> int:
        return self.cable_plan.operation_count if self.cable_plan else 0

    def set_cable_selected(self, key: str, selected: bool) -> None:
        if self.cable_plan is not None:
            self.cable_plan = select_cable(self.cable_plan, key, selected)

    # -- drive inventory items ---------------------------------------------

    def disk_rows_for(self, key: str) -> tuple[DiskPlanRow, ...]:
        """Inventory-item rows of a UNAS device row."""
        device_id = self.drive_id(key)
        if not device_id or self.disk_plan is None:
            return ()
        return self.disk_plan.rows_for(f"{DRIVE_PREFIX}{device_id}")

    def disk_operation_count(self) -> int:
        return self.disk_plan.operation_count if self.disk_plan else 0

    def set_disk_selected(self, key: str, selected: bool) -> None:
        if self.disk_plan is not None:
            self.disk_plan = select_disk(self.disk_plan, key, selected)

    def selected_count(self) -> int:
        return sum(
            1
            for item in self.rows()
            if item.selected and item.category in (CREATE, UPDATE)
        )

    def selectable_count(self) -> int:
        return sum(1 for item in self.rows() if item.category in (CREATE, UPDATE))

    def ports_for(self, key: str) -> tuple[PortMatch, ...]:
        """UniFi ports and NetBox interfaces of one device, paired.

        New devices only show their UniFi ports: NetBox creates interfaces from
        the device-type template when the device is written.
        """
        unifi_id, netbox_id = _device_ids(key)
        ports = [p for p in self.unifi_ports if unifi_id and p.device_id == unifi_id]
        interfaces = [
            i for i in self.netbox_interfaces if netbox_id and i.device_id == netbox_id
        ]
        if not ports:
            # Access points and similar devices expose no ports officially.
            return ()
        if key.startswith("create:"):
            return tuple(
                PortMatch(port, None) for port in sorted(ports, key=lambda p: p.idx)
            )
        return match_ports(ports, interfaces)

    def port_configs_for(self, key: str) -> dict[int, InventoryPortConfig]:
        """Effective UniFi port configuration of one device, by port index."""
        unifi_id, _ = _device_ids(key)
        return {
            config.idx: config
            for config in self.unifi_port_configs
            if unifi_id and config.device_id == unifi_id
        }

    def sfps_for(self, key: str) -> dict[int, InventorySfp]:
        """Plugged SFP modules of one device, by port index (display only)."""
        unifi_id, _ = _device_ids(key)
        return {
            sfp.port_idx: sfp
            for sfp in (self.result.unifi_sfps if self.result else ())
            if unifi_id and sfp.device_id == unifi_id
        }

    def details_for(self, key: str) -> tuple[tuple[str, str, str], ...]:
        """(label, NetBox value, UniFi value) of management IP and firmware."""
        unifi_id, netbox_id = _device_ids(key)
        result = self.result
        unifi = next(
            (
                d
                for d in (result.unifi_device_records if result else ())
                if unifi_id and d.source_id == unifi_id
            ),
            None,
        )
        netbox = next(
            (
                d
                for d in (result.netbox_device_records if result else ())
                if netbox_id and d.source_id == netbox_id
            ),
            None,
        )
        rows = []
        for title, name in (("Management IP", "ip_address"), ("Firmware", "firmware")):
            target = getattr(netbox, name, "") if netbox else ""
            source = getattr(unifi, name, "") if unifi else ""
            if target or source:
                rows.append((title, target, source))
        return tuple(rows)

    # -- user actions --------------------------------------------------------

    def set_device_selected(self, key: str, selected: bool) -> None:
        if self.diff is None:
            return
        self.diff = select_device(self.diff, key, selected)
        self._recompute()

    def set_all_selected(self, keys: tuple[str, ...], selected: bool) -> None:
        if self.diff is None:
            return
        for key in keys:
            self.diff = select_device(self.diff, key, selected)
        self._recompute()

    def set_field_selected(self, key: str, field_name: str, selected: bool) -> None:
        if self.diff is None:
            return
        self.diff = select_field(self.diff, key, field_name, selected)
        self._recompute()

    def set_choice(self, kind: str, key: str, value: str) -> None:
        target = {
            "type": self.type_by_key,
            "role": self.role_by_key,
            "site": self.site_by_key,
            "status": self.status_by_key,
        }[kind]
        if value.strip():
            target[key] = value.strip()
        else:
            target.pop(key, None)

    def record_report(self, report: WriteExecutionReport) -> None:
        self.last_report = report
        network_keys = {
            outcome.device_key
            for outcome in report.outcomes
            if outcome.device_key.startswith("network")
        }
        for key in network_keys:
            self.network_outcomes[key] = []
        for outcome in report.outcomes:
            if outcome.device_key in network_keys:
                self.network_outcomes[outcome.device_key].append(outcome)
            else:
                self.outcomes[outcome.device_key] = outcome

    # -- write plans ---------------------------------------------------------

    def plan_for(self, key: str | None = None) -> WritePlan | None:
        """The full plan, or a one-operation plan for a single device."""
        if self.plan is None:
            return None
        if key is None:
            return self.plan
        return single_operation_plan(self.plan, key)

    def overrides(self, plan: WritePlan) -> dict[str, dict[str, str]]:
        create_keys = {
            op.device_key
            for op in plan.operations
            if op.operation_type == OperationType.CREATE_DEVICE
        }

        def limit(values: dict[str, str]) -> dict[str, str]:
            return {k: v for k, v in values.items() if k in create_keys and v.strip()}

        return {
            "role": limit(self.role_by_key),
            "site": limit(self.site_by_key),
            "status": limit(self.status_by_key),
            "type": limit(self.type_by_key),
        }

    def plan_blockers(self, plan: WritePlan) -> tuple[str, ...]:
        """Reasons that stop the plan, including missing create choices."""
        reasons = [
            f"{_label_for(self, issue.device_key)}: {issue.message}"
            for issue in plan.issues
            if issue.severity.value == "blocker"
        ]
        missing_role = [
            op.source_label
            for op in plan.operations
            if op.operation_type == OperationType.CREATE_DEVICE
            and not self.role_by_key.get(op.device_key)
        ]
        if missing_role:
            reasons.append(
                f"Choose a NetBox device role for {_count_names(missing_role)}."
            )
        return tuple(reasons)

    def plan_warnings(self, plan: WritePlan) -> tuple[str, ...]:
        warnings = [
            f"{_label_for(self, issue.device_key)}: {issue.message}"
            for issue in plan.issues
            if issue.severity.value == "warning"
        ]
        missing_type = [
            op.source_label
            for op in plan.operations
            if op.operation_type == OperationType.CREATE_DEVICE
            and not self.type_by_key.get(op.device_key)
        ]
        if missing_type:
            warnings.append(
                f"No device type chosen for {_count_names(missing_type)}. NetBox "
                "looks the type up by manufacturer and model, which may fail."
            )
        return tuple(warnings)


def single_operation_plan(write_plan: WritePlan, device_key: str) -> WritePlan | None:
    operation = next(
        (item for item in write_plan.operations if item.device_key == device_key), None
    )
    if operation is None:
        return None
    is_create = operation.operation_type == OperationType.CREATE_DEVICE
    summary = WritePlanSummary(
        total_operations=1,
        create_operations=1 if is_create else 0,
        update_operations=0 if is_create else 1,
        blocker_issues=0,
        warning_issues=0,
        blocked_device_keys=(),
        requires_confirmation=True,
        confirmation_message=f"Confirm execution of 1 operation ({device_key}).",
    )
    return WritePlan(
        operations=(operation,),
        issues=tuple(i for i in write_plan.issues if i.device_key == device_key),
        executable=True,
        summary=summary,
    )


def friendly_reason(reason: str) -> str:
    """Translate dependency codes from the preview into plain sentences."""
    text = reason.strip()
    if not text or text.startswith("selected_supported_fields"):
        return "Nothing selected to write"
    if text.startswith("create_required_identity"):
        missing = text.split("missing", 1)[-1].strip()
        return f"Missing {missing} for a new device" if missing else text
    if text.startswith("model_requires_manufacturer"):
        return "A model change also needs the manufacturer selected"
    if text.startswith("target_only_no_write"):
        return "Only in NetBox; nothing is written"
    return text


def humanize_timestamp(value: str, now: datetime | None = None) -> str:
    """Show ISO timestamps as 'today 10:05' or '14 Nov 10:05'."""
    if not value:
        return "never"
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value
    reference = now or datetime.now(moment.tzinfo)
    if moment.date() == reference.date():
        return f"today {moment:%H:%M}"
    return f"{moment:%d %b %H:%M}"


PROTECT_PREFIX = "protect:"
ACCESS_PREFIX = "access:"
DRIVE_PREFIX = "drive:"
# Access hints avoid a bare "access", which would also match "Access Point".
_ACCESS_HINTS = ("access control", "door", "zutritt")
_ROLE_HINTS = {
    "camera": ("camera", "kamera", "cctv", "surveillance"),
    "nvr": ("nvr", "recorder", "video storage"),
    "hub": _ACCESS_HINTS,
    "reader": (*_ACCESS_HINTS, "reader"),
    "intercom": ("intercom", "sprechanlage", *_ACCESS_HINTS),
    "access": _ACCESS_HINTS,
    "nas": ("nas", "storage", "speicher"),
}


def role_for_kind(kind: str, roles: tuple[str, ...]) -> str:
    """The single NetBox role whose name fits a Protect/Access kind, else ''."""
    hints = _ROLE_HINTS.get(kind, ())
    matches = [role for role in roles if any(h in role.lower() for h in hints)]
    return matches[0] if len(matches) == 1 else ""


def _device_ids(key: str) -> tuple[str, str]:
    """(UniFi device ID, NetBox device ID) from a preview device key."""
    value = key.strip()
    if value.startswith("create:"):
        value = value.split(":", 1)[1]
    unifi_part, _, netbox_part = value.partition("->")
    if value.startswith("target-only:"):
        unifi_part, netbox_part = "", value.split(":", 1)[1]
    unifi_id = unifi_part.split(":", 1)[1] if ":" in unifi_part else ""
    netbox_id = netbox_part.split(":", 1)[1] if ":" in netbox_part else ""
    return unifi_id, netbox_id


def _category(device: DevicePreview) -> str:
    if device.action == DeviceAction.CREATE:
        return CREATE
    if device.action == DeviceAction.TARGET_ONLY:
        return NETBOX_ONLY
    if any(field.selectable for field in device.fields):
        return UPDATE
    return IN_SYNC


def _search_text(item: ReviewRow) -> str:
    parts = [item.name, item.row.target_label, item.source_value("model")]
    return " ".join(parts).lower()


def _count_names(names: list[str], limit: int = 4) -> str:
    shown = ", ".join(names[:limit])
    rest = len(names) - limit
    noun = "device" if len(names) == 1 else "devices"
    extra = f" and {rest} more" if rest > 0 else ""
    return f"{len(names)} {noun} ({shown}{extra})"


def _label_for(state: ReviewState, key: str) -> str:
    item = state.row(key)
    return item.name if item else key
