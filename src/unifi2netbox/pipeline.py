"""Qt-free inventory preview and write-execution pipeline.

The GUI runs these functions inside worker jobs and only renders their results.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from unifi2netbox.cable_execute import execute_cable_plan
from unifi2netbox.cables import CablePlan, build_cable_plan
from unifi2netbox.config import (
    AccessConfig,
    BehaviorConfig,
    DriveConfig,
    NetBoxConfig,
    ProtectConfig,
    UniFiConfig,
)
from unifi2netbox.disk_execute import execute_disk_plan
from unifi2netbox.disks import DiskPlan, build_disk_plan
from unifi2netbox.interface_execute import execute_interface_plan
from unifi2netbox.interface_plan import (
    DevicePair,
    InterfacePlan,
    build_interface_plan,
)
from unifi2netbox.inventory import (
    InventoryDevice,
    InventoryDisk,
    InventoryError,
    InventoryInterface,
    InventoryPort,
    InventorySnapshot,
    InventorySource,
    read_unifi_inventory,
)
from unifi2netbox.journal_store import (
    JournalStore,
    JournalStoreError,
    StoredOutcome,
    StoredRun,
)
from unifi2netbox.matching import (
    DeduplicationResult,
    DeviceTypeSuggestion,
    confident_device_type_id,
    deduplicate_inventory,
    suggest_device_types_for_unmatched,
)
from unifi2netbox.network_execute import execute_network_plan
from unifi2netbox.networks import NetworkPlan, build_network_plan, group_name_for
from unifi2netbox.port_config import InventoryPortConfig
from unifi2netbox.preview import (
    ChangePreview,
    DifferencePreview,
    build_change_preview,
    build_difference_preview,
)
from unifi2netbox.refresh import refresh_snapshots
from unifi2netbox.snapshots import SnapshotStore
from unifi2netbox.write_execute import (
    RequestsNetBoxWriteBackend,
    execute_write_plan,
)
from unifi2netbox.write_journal import finalize_journal
from unifi2netbox.write_plan import WritePlan, build_write_plan

SNAPSHOT_FILENAME = "snapshots.sqlite3"


@dataclass(frozen=True)
class InventoryPreviewRow:
    device_key: str
    action: str
    source_label: str
    target_label: str
    selected_fields: str
    executable: str
    blocked_reason: str = ""
    suggested_device_types: str = ""
    suggested_device_type_id: str = ""


@dataclass(frozen=True)
class InventoryPreviewResult:
    status: str
    details: str
    netbox_devices: int = 0
    unifi_devices: int = 0
    matched_devices: int = 0
    unmatched_unifi: int = 0
    unmatched_netbox: int = 0
    conflicts: int = 0
    preview_rows: int = 0
    executable_operations: int = 0
    last_updated: str = ""
    detail_lines: tuple[str, ...] = ()
    rows: tuple[InventoryPreviewRow, ...] = ()
    unifi_captured_at: str = ""
    unifi_scope: str = ""
    unifi_version: str = ""
    unifi_api_feedback: tuple[dict[str, object], ...] = ()
    unifi_raw_devices: tuple[dict[str, object], ...] = ()
    unifi_ports: tuple[InventoryPort, ...] = ()
    netbox_interfaces: tuple[InventoryInterface, ...] = ()
    unifi_port_configs: tuple[InventoryPortConfig, ...] = ()
    port_config_error: str = ""
    interface_plan: InterfacePlan | None = None
    cable_plan: CablePlan | None = None
    disk_plan: DiskPlan | None = None
    protect_devices: tuple[InventoryDevice, ...] = ()
    protect_version: str = ""
    protect_status: str = ""
    access_devices: tuple[InventoryDevice, ...] = ()
    access_status: str = ""
    drive_devices: tuple[InventoryDevice, ...] = ()
    drive_disks: tuple[InventoryDisk, ...] = ()
    drive_status: str = ""
    network_plan: NetworkPlan | None = None
    netbox_device_types: tuple[tuple[str, str, str], ...] = ()
    netbox_device_roles: tuple[str, ...] = ()
    netbox_sites: tuple[str, ...] = ()
    netbox_device_statuses: tuple[str, ...] = ()
    difference_preview: DifferencePreview | None = None
    write_plan: WritePlan | None = None


@dataclass(frozen=True)
class WriteOutcome:
    device_key: str
    status: str
    message: str
    netbox_object_id: str = ""
    verification: str = ""
    verification_detail: str = ""


@dataclass(frozen=True)
class WriteExecutionReport:
    status: str
    details: str
    detail_lines: tuple[str, ...] = ()
    outcomes: tuple[WriteOutcome, ...] = ()
    dry_run: bool = False
    run_id: str = ""
    started_at: str = ""


def build_inventory_preview(
    config_path: Path,
    netbox_config: NetBoxConfig,
    unifi_config: UniFiConfig,
    *,
    include_all_netbox_delete_candidates: bool,
    netbox_site_name: str = "",
    protect_config: ProtectConfig | None = None,
    access_config: AccessConfig | None = None,
    drive_config: DriveConfig | None = None,
) -> InventoryPreviewResult:
    """Refresh snapshots, match, build the difference preview and write plan.

    A configured ``netbox_site_name`` replaces the UniFi site name of every UniFi
    device before matching, so previews and writes use the NetBox site.
    """
    store = SnapshotStore(config_path.with_name(SNAPSHOT_FILENAME))
    refresh = refresh_snapshots(
        netbox_config,
        unifi_config,
        store,
        protect_config,
        access_config,
        drive_config,
    )
    diagnostics = (*refresh.netbox.diagnostics, *refresh.unifi.diagnostics)
    protect_snapshot = refresh.protect.snapshot if refresh.protect else None
    protect_note = _protect_note(refresh.protect)
    access_snapshot = refresh.access.snapshot if refresh.access else None
    access_note = _optional_note(refresh.access, "Access")
    drive_snapshot = refresh.drive.snapshot if refresh.drive else None
    drive_note = _optional_note(refresh.drive, "Drive")
    if drive_snapshot is not None and drive_snapshot.disk_error:
        drive_note += f" {drive_snapshot.disk_error}"
    message = " ".join(item for item in diagnostics if item)
    last_updated = refresh.netbox.last_updated or refresh.unifi.last_updated

    if refresh.netbox.error or refresh.unifi.error:
        return InventoryPreviewResult(
            status="Partial",
            details=(
                message or "Inventory refresh completed with cached/failed sources."
            ),
            netbox_devices=_device_count(refresh.netbox.snapshot),
            unifi_devices=_device_count(refresh.unifi.snapshot),
            last_updated=last_updated,
            detail_lines=(
                message or "Inventory refresh is partial; check source diagnostics.",
            ),
        )

    netbox_snapshot = refresh.netbox.snapshot
    unifi_snapshot = refresh.unifi.snapshot
    if netbox_snapshot is None or unifi_snapshot is None:
        detail = message or "Inventory snapshots are not available for both sources."
        return InventoryPreviewResult(
            status="Unavailable",
            details=detail,
            last_updated=last_updated,
            detail_lines=(detail,),
        )

    # Only fresh Protect and Access reads may join the preview; a cached
    # snapshot after a failed refresh must not authorize writes.
    fresh_protect = (
        protect_snapshot
        if refresh.protect is not None and not refresh.protect.error
        else None
    )
    fresh_access = (
        access_snapshot
        if refresh.access is not None and not refresh.access.error
        else None
    )
    fresh_drive = (
        drive_snapshot
        if refresh.drive is not None and not refresh.drive.error
        else None
    )
    merged_unifi, dropped = merge_optional_devices(
        unifi_snapshot,
        (
            (ACCESS_PREFIX, fresh_access),
            (PROTECT_PREFIX, fresh_protect),
            (DRIVE_PREFIX, fresh_drive),
        ),
    )
    if dropped.get(ACCESS_PREFIX):
        access_note += (
            f" {dropped[ACCESS_PREFIX]} also seen in UniFi Network; "
            "Network data is used."
        )
    if dropped.get(PROTECT_PREFIX):
        protect_note += (
            f" {dropped[PROTECT_PREFIX]} also seen in UniFi Network or Access; "
            "that data is used."
        )
    mapped_unifi = map_unifi_site(merged_unifi, netbox_site_name)
    known_sites = frozenset(
        item.name.strip() for item in netbox_snapshot.sites if item.name.strip()
    )
    # An empty catalog (e.g. no read permission) disables the unknown-site guard.
    site_catalog = known_sites or None

    dedup = deduplicate_inventory(netbox_snapshot, mapped_unifi)
    dedup, hidden_unmatched_netbox = scope_unmatched_netbox_for_delete(
        dedup,
        netbox_snapshot,
        mapped_unifi,
        include_all_netbox_delete_candidates=include_all_netbox_delete_candidates,
    )
    suggestions = suggest_device_types_for_unmatched(
        dedup, netbox_snapshot, mapped_unifi
    )
    diff = build_difference_preview(
        netbox_snapshot, mapped_unifi, dedup, netbox_sites=site_catalog
    )
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change, netbox_sites=site_catalog)
    network_plan = build_network_plan(
        unifi_snapshot.networks,
        netbox_snapshot.sites,
        netbox_snapshot.vlan_groups,
        netbox_snapshot.vlans,
        netbox_snapshot.prefixes,
        site_name=netbox_site_name.strip(),
        ipam_error=netbox_snapshot.ipam_error,
    )

    return InventoryPreviewResult(
        status="Ready",
        details=message or "Inventory preview and write-plan summary updated.",
        netbox_devices=len(netbox_snapshot.devices),
        unifi_devices=len(mapped_unifi.devices),
        matched_devices=len(dedup.pairs),
        unmatched_unifi=len(dedup.unmatched_unifi),
        unmatched_netbox=len(dedup.unmatched_netbox),
        conflicts=len(dedup.conflicts),
        preview_rows=len(diff.devices),
        executable_operations=len(plan.operations) if plan.executable else 0,
        last_updated=last_updated,
        detail_lines=preview_detail_lines(
            dedup,
            plan,
            suggestions=suggestions,
            hidden_unmatched_netbox=hidden_unmatched_netbox,
            netbox_device_count=len(netbox_snapshot.devices),
            unifi_device_count=len(unifi_snapshot.devices),
        )
        + tuple(note for note in (protect_note, access_note, drive_note) if note),
        rows=preview_rows(diff, change, plan, suggestions=suggestions),
        unifi_captured_at=unifi_snapshot.captured_at,
        unifi_scope=unifi_snapshot.scope,
        unifi_version=unifi_snapshot.source_version,
        unifi_api_feedback=unifi_snapshot.unifi_api_feedback,
        unifi_raw_devices=unifi_snapshot.unifi_raw_devices,
        unifi_ports=unifi_snapshot.ports,
        netbox_interfaces=netbox_snapshot.interfaces,
        unifi_port_configs=unifi_snapshot.port_configs,
        port_config_error=unifi_snapshot.port_config_error,
        network_plan=network_plan,
        interface_plan=_interface_plan(
            dedup.pairs, netbox_snapshot, mapped_unifi, network_plan, netbox_site_name
        ),
        cable_plan=_cable_plan(dedup.pairs, netbox_snapshot, mapped_unifi),
        disk_plan=_disk_plan(dedup.pairs, netbox_snapshot, mapped_unifi),
        protect_devices=protect_snapshot.devices if protect_snapshot else (),
        protect_version=protect_snapshot.source_version if protect_snapshot else "",
        protect_status=protect_note,
        access_devices=access_snapshot.devices if access_snapshot else (),
        access_status=access_note,
        drive_devices=drive_snapshot.devices if drive_snapshot else (),
        drive_disks=drive_snapshot.disks if drive_snapshot else (),
        drive_status=drive_note,
        netbox_device_types=_device_type_catalog(netbox_snapshot),
        netbox_device_roles=_sorted_names(netbox_snapshot.device_roles),
        netbox_sites=_sorted_names(netbox_snapshot.sites),
        netbox_device_statuses=tuple(
            item.value.strip()
            for item in netbox_snapshot.device_statuses
            if item.value.strip()
        ),
        difference_preview=diff,
        write_plan=plan,
    )


def _interface_plan(
    pairs,
    netbox_snapshot: InventorySnapshot,
    unifi_snapshot: InventorySnapshot,
    network_plan: NetworkPlan,
    site_name: str,
) -> InterfacePlan:
    """Interface changes for matched devices against the site VLAN group."""
    names = {device.source_id: device.name for device in unifi_snapshot.devices}
    device_pairs = []
    for pair in pairs:
        unifi_id = pair.unifi_observation_id.split(":", 1)[-1]
        netbox_id = pair.netbox_observation_id.split(":", 1)[-1]
        device_pairs.append(
            DevicePair(
                f"{pair.unifi_observation_id}->{pair.netbox_observation_id}",
                names.get(unifi_id, unifi_id),
                unifi_id,
                netbox_id,
            )
        )
    group = network_plan.group
    group_id = group.netbox_id if group is not None else ""
    group_name = group.name if group is not None else group_name_for(site_name)
    return build_interface_plan(
        device_pairs,
        unifi_snapshot.ports,
        netbox_snapshot.interfaces,
        unifi_snapshot.port_configs,
        netbox_snapshot.vlans,
        vlan_group_id=group_id,
        vlan_group_name=group_name,
        port_config_error=unifi_snapshot.port_config_error,
    )


def _protect_note(status) -> str:
    return _optional_note(status, "Protect")


def _optional_note(status, label: str) -> str:
    """One line about an optional source: off, read, stale cache or failure."""
    if status is None:
        return ""
    if status.error:
        cached = f" Showing the last cached {label} snapshot." if status.cached else ""
        return f"{label} refresh failed: {status.error}{cached}"
    count = _device_count(status.snapshot)
    return f"{label}: {count} device{'s' if count != 1 else ''} read."


def _disk_plan(
    pairs, netbox_snapshot: InventorySnapshot, unifi_snapshot: InventorySnapshot
) -> DiskPlan:
    """Inventory items for the drive bays of matched UNAS devices."""
    return build_disk_plan(
        unifi_snapshot.disks,
        {
            pair.unifi_observation_id.split(":", 1)[-1]: (
                pair.netbox_observation_id.split(":", 1)[-1]
            )
            for pair in pairs
        },
        {device.source_id: device.name for device in unifi_snapshot.devices},
        netbox_snapshot.inventory_items,
        item_error=netbox_snapshot.inventory_item_error,
    )


def _cable_plan(
    pairs, netbox_snapshot: InventorySnapshot, unifi_snapshot: InventorySnapshot
) -> CablePlan:
    """Cable suggestions between matched devices from UniFi link evidence."""
    return build_cable_plan(
        unifi_snapshot.links,
        {device.source_id: device.name for device in unifi_snapshot.devices},
        {
            pair.unifi_observation_id.split(":", 1)[-1]: (
                pair.netbox_observation_id.split(":", 1)[-1]
            )
            for pair in pairs
        },
        unifi_snapshot.ports,
        netbox_snapshot.interfaces,
        port_config_error=unifi_snapshot.port_config_error,
    )


def run_write_execution(
    netbox_config: NetBoxConfig,
    behavior: BehaviorConfig,
    difference_preview: DifferencePreview,
    write_plan: WritePlan,
    *,
    role_overrides: dict[str, str],
    site_overrides: dict[str, str],
    status_overrides: dict[str, str],
    device_type_overrides: dict[str, str],
    dry_run: bool,
    unifi_config: UniFiConfig | None = None,
    journal_path: Path | None = None,
    network_plan: NetworkPlan | None = None,
    interface_plan: InterfacePlan | None = None,
    cable_plan: CablePlan | None = None,
    protect_config: ProtectConfig | None = None,
    access_config: AccessConfig | None = None,
    drive_config: DriveConfig | None = None,
    disk_plan: DiskPlan | None = None,
) -> WriteExecutionReport:
    """Execute approved network and device writes and summarize them.

    With ``unifi_config`` the UniFi inventory is re-read once first; devices and
    networks whose UniFi values changed since the preview are skipped. Network
    writes (VLAN group, VLANs, prefixes) run first, then interface
    configuration and cables of matched devices, then device writes, then
    drive inventory items of matched UNAS devices.
    """
    started = _now()
    snapshot, source_error = (
        reread_unifi_snapshot(
            unifi_config,
            behavior.netbox_site_name,
            protect_config,
            access_config,
            drive_config,
        )
        if unifi_config is not None
        else (None, "")
    )
    source_devices = (
        {_snapshot_observation_id(snapshot.source, d): d for d in snapshot.devices}
        if snapshot is not None
        else None
    )
    source_networks = (
        {f"network:{n.source_id}": n for n in snapshot.networks}
        if snapshot is not None
        else None
    )

    source_configs = (
        {(c.device_id, c.idx): c for c in snapshot.port_configs}
        if snapshot is not None
        else None
    )
    backend = RequestsNetBoxWriteBackend(netbox_config)
    network_outcomes = (
        execute_network_plan(
            network_plan,
            backend,
            dry_run=dry_run,
            source_networks=source_networks,
            source_error=source_error,
        )
        + execute_interface_plan(
            interface_plan,
            backend,
            dry_run=dry_run,
            source_configs=source_configs,
            source_error=source_error,
        )
        + execute_cable_plan(
            cable_plan,
            backend,
            dry_run=dry_run,
            source_links=snapshot.links if snapshot is not None else None,
            source_error=source_error,
        )
    )
    result = execute_write_plan(
        write_plan,
        difference_preview,
        netbox_config,
        behavior,
        run_id=str(uuid4()),
        started_at=started,
        finished_at=_now(),
        dry_run=dry_run,
        role_overrides=role_overrides,
        site_overrides=site_overrides,
        status_overrides=status_overrides,
        device_type_overrides=device_type_overrides,
        source_devices=source_devices,
        source_error=source_error,
    )
    network_outcomes += execute_disk_plan(
        disk_plan,
        backend,
        dry_run=dry_run,
        source_disks=(
            {(d.device_id, d.slot): d for d in snapshot.disks}
            if snapshot is not None
            else None
        ),
        source_error=source_error,
    )
    journal = finalize_journal(result.journal, _now())
    labels = {
        op.sequence: op.source_label or op.target_label or op.device_key
        for op in write_plan.operations
    }
    stored = [
        StoredOutcome(
            device_key=item.key,
            label=item.label,
            operation_type=item.operation,
            status=item.status,
            message=item.message,
            netbox_object_id=item.object_id,
            verification=item.verification,
            verification_detail=item.verification_detail,
        )
        for item in network_outcomes
    ] + [
        StoredOutcome(
            device_key=item.device_key,
            label=labels.get(item.sequence, item.device_key),
            operation_type=str(item.operation_type),
            status=str(item.status),
            message=item.message,
            netbox_object_id=item.netbox_object_id,
            verification=item.verification,
            verification_detail=item.verification_detail,
        )
        for item in journal.outcomes
    ]

    def count(status: str) -> int:
        return sum(item.status == status for item in stored)

    verified = sum(item.verification == "verified" for item in stored)
    mismatched = sum(item.verification == "mismatch" for item in stored)
    details = (
        "Write execution finished: "
        f"{count('success')} success, {count('failed')} failed, "
        f"{count('skipped')} skipped."
    )
    if count("success"):
        details += f" Read-back: {verified} verified"
        details += f", {mismatched} mismatch." if mismatched else "."

    if journal_path is not None:
        try:
            JournalStore(journal_path).save(
                StoredRun(
                    run_id=journal.run_id,
                    started_at=journal.started_at,
                    finished_at=journal.finished_at,
                    dry_run=dry_run,
                    outcomes=tuple(stored),
                )
            )
        except (JournalStoreError, sqlite3.Error, OSError) as error:
            details += f" Write history not saved: {error}"

    lines = tuple(
        f"{item.operation_type}: {item.label} {item.status} {item.message}".strip()
        for item in stored[:8]
    )
    return WriteExecutionReport(
        status="Dry run" if dry_run else "Applied",
        details=details,
        detail_lines=lines or (details,),
        outcomes=tuple(
            WriteOutcome(
                device_key=item.device_key,
                status=item.status,
                message=item.message,
                netbox_object_id=item.netbox_object_id,
                verification=item.verification,
                verification_detail=item.verification_detail,
            )
            for item in stored
        ),
        dry_run=dry_run,
        run_id=journal.run_id,
        started_at=journal.started_at,
    )


def reread_unifi_snapshot(
    unifi_config: UniFiConfig,
    netbox_site_name: str,
    protect_config: ProtectConfig | None = None,
    access_config: AccessConfig | None = None,
    drive_config: DriveConfig | None = None,
) -> tuple[InventorySnapshot | None, str]:
    """Fresh UniFi snapshot with the site mapping, or (None, error text).

    Configured Protect and Access devices are re-read and merged as in the
    preview. If only Protect or Access fails, its devices are missing from the
    result, so their writes are skipped while Network writes proceed.
    """
    try:
        network = read_unifi_inventory(unifi_config)
    except InventoryError as error:
        return None, str(error) or "UniFi read failed"
    protect = None
    if protect_config is not None and protect_config.configured:
        from unifi2netbox.protect import read_protect_inventory

        try:
            protect = read_protect_inventory(protect_config)
        except InventoryError:
            protect = None
    access = None
    if access_config is not None and access_config.configured:
        from unifi2netbox.access import read_access_inventory

        try:
            access = read_access_inventory(access_config)
        except InventoryError:
            access = None
    drive = None
    if drive_config is not None and drive_config.configured:
        from unifi2netbox.drive import read_drive_inventory

        try:
            drive = read_drive_inventory(drive_config)
        except InventoryError:
            drive = None
    merged, _ = merge_optional_devices(
        network,
        (
            (ACCESS_PREFIX, access),
            (PROTECT_PREFIX, protect),
            (DRIVE_PREFIX, drive),
        ),
    )
    return map_unifi_site(merged, netbox_site_name), ""


def reread_unifi_sources(
    unifi_config: UniFiConfig, netbox_site_name: str
) -> tuple[dict[str, InventoryDevice] | None, str]:
    """Fresh UniFi devices by observation ID, or (None, error text)."""
    snapshot, error = reread_unifi_snapshot(unifi_config, netbox_site_name)
    if snapshot is None:
        return None, error
    return {
        _snapshot_observation_id(snapshot.source, device): device
        for device in snapshot.devices
    }, ""


def preview_detail_lines(
    dedup: DeduplicationResult,
    plan: WritePlan,
    suggestions: tuple[DeviceTypeSuggestion, ...],
    hidden_unmatched_netbox: int,
    *,
    netbox_device_count: int,
    unifi_device_count: int,
) -> tuple[str, ...]:
    lines: list[str] = []

    if netbox_device_count == 0 and unifi_device_count > 0:
        lines.append(
            "NetBox inventory is empty; unmatched UniFi devices are expected "
            "until target records exist or create flow is executed."
        )

    if dedup.unmatched_unifi:
        lines.append(f"Unmatched UniFi observations: {len(dedup.unmatched_unifi)}")
    if dedup.unmatched_netbox:
        lines.append(f"Unmatched NetBox observations: {len(dedup.unmatched_netbox)}")
    if hidden_unmatched_netbox:
        lines.append(
            "Delete scope hides "
            f"{hidden_unmatched_netbox} NetBox-only observation(s). "
            "Enable the settings option to include all NetBox devices."
        )

    for pair in dedup.pairs[:3]:
        lines.append(
            "Match "
            f"{pair.unifi_observation_id} -> {pair.netbox_observation_id} "
            f"({pair.reason})"
        )
    for conflict in dedup.conflicts[:3]:
        lines.append(
            f"Conflict {conflict.reason}: {', '.join(conflict.observation_ids[:3])}"
        )
    for operation in plan.operations[:3]:
        lines.append(
            "Plan "
            f"#{operation.sequence} {operation.operation_type} "
            f"{operation.device_key}"
        )

    for suggestion in suggestions[:3]:
        if not suggestion.candidates:
            continue
        top = suggestion.candidates[0]
        lines.append(
            "Create template suggestion "
            f"{suggestion.unifi_observation_id}: "
            f"{top.manufacturer} {top.model} (score={top.score})"
        )

    if plan.issues:
        first_issue = plan.issues[0]
        lines.append(f"Plan issue ({first_issue.code}): {first_issue.message}")

    if not lines:
        lines.append("No preview detail entries are currently available.")
    return tuple(lines)


def preview_rows(
    diff: DifferencePreview,
    change: ChangePreview,
    plan: WritePlan,
    *,
    suggestions: tuple[DeviceTypeSuggestion, ...] = (),
) -> tuple[InventoryPreviewRow, ...]:
    change_by_key = {item.device_key: item for item in change.devices}
    executable_by_key = {item.device_key: item.executable for item in change.devices}
    issue_by_key = {item.device_key: item.message for item in plan.issues}
    suggestions_by_observation = {
        item.unifi_observation_id: item.candidates for item in suggestions
    }

    rows: list[InventoryPreviewRow] = []
    for device in diff.devices:
        selected_fields = ""
        blocked_reason = ""
        suggested_device_types = ""
        suggested_device_type_id = ""
        change_item = change_by_key.get(device.device_key)
        if change_item is not None and change_item.selected_fields:
            selected_fields = ", ".join(change_item.selected_fields)

        if device.action == "create" and device.device_key.startswith("create:"):
            observation_id = device.device_key.split(":", maxsplit=1)[1]
            candidates = suggestions_by_observation.get(observation_id, ())
            if candidates:
                suggested_device_types = "; ".join(
                    f"{candidate.manufacturer} {candidate.model} ({candidate.score})"
                    for candidate in candidates[:3]
                )
                suggested_device_type_id = confident_device_type_id(candidates)

        if not executable_by_key.get(device.device_key, False):
            if change_item is None:
                blocked_reason = "No change preview entry is available."
            else:
                unsatisfied = [
                    dependency
                    for dependency in change_item.dependencies
                    if not dependency.satisfied
                ]
                if unsatisfied:
                    top = unsatisfied[0]
                    if top.missing_fields:
                        blocked_reason = (
                            f"{top.name}: missing {', '.join(top.missing_fields)}"
                        )
                    else:
                        blocked_reason = top.description
                elif device.device_key in issue_by_key:
                    blocked_reason = issue_by_key[device.device_key]
        elif device.device_key in issue_by_key:
            blocked_reason = issue_by_key[device.device_key]

        rows.append(
            InventoryPreviewRow(
                device_key=device.device_key,
                action=str(device.action),
                source_label=device.source_label,
                target_label=device.target_label,
                selected_fields=selected_fields,
                executable=(
                    "Yes" if executable_by_key.get(device.device_key, False) else "No"
                ),
                blocked_reason=blocked_reason,
                suggested_device_types=suggested_device_types,
                suggested_device_type_id=suggested_device_type_id,
            )
        )
    return tuple(rows)


def scope_unmatched_netbox_for_delete(
    dedup: DeduplicationResult,
    netbox_snapshot: InventorySnapshot | None,
    unifi_snapshot: InventorySnapshot | None,
    *,
    include_all_netbox_delete_candidates: bool,
) -> tuple[DeduplicationResult, int]:
    """Limit NetBox-only delete proposals to sites present in UniFi by default."""
    if include_all_netbox_delete_candidates:
        return dedup, 0
    if netbox_snapshot is None or unifi_snapshot is None:
        return dedup, 0

    unifi_sites = {
        device.site.strip().lower()
        for device in unifi_snapshot.devices
        if device.site.strip()
    }
    by_observation_id = {
        _snapshot_observation_id(netbox_snapshot.source, device): device
        for device in netbox_snapshot.devices
    }

    scoped_unmatched = tuple(
        observation_id
        for observation_id in dedup.unmatched_netbox
        if observation_id in by_observation_id
        and by_observation_id[observation_id].site.strip().lower() in unifi_sites
    )
    hidden = len(dedup.unmatched_netbox) - len(scoped_unmatched)
    return (
        DeduplicationResult(
            pairs=dedup.pairs,
            conflicts=dedup.conflicts,
            unmatched_unifi=dedup.unmatched_unifi,
            unmatched_netbox=scoped_unmatched,
        ),
        hidden,
    )


PROTECT_PREFIX = "protect:"
ACCESS_PREFIX = "access:"
DRIVE_PREFIX = "drive:"


def merge_optional_devices(
    network: InventorySnapshot,
    sources: tuple[tuple[str, InventorySnapshot | None], ...],
) -> tuple[InventorySnapshot, dict[str, int]]:
    """Add devices of optional UniFi applications to the matching snapshot.

    ``sources`` are ``(prefix, snapshot)`` pairs in precedence order after
    Network (Access before Protect). IDs get the prefix so they never collide
    with Network IDs. A device whose MAC was already contributed by Network or
    an earlier source is dropped: the earlier record wins. Optional sources
    have no site, so the most common Network site is used (the NetBox site
    mapping still applies afterwards). Returns the merged snapshot and the
    number of dropped duplicates per prefix.
    """
    known = {d.mac_address for d in network.devices if d.mac_address}
    sites = Counter(d.site for d in network.devices if d.site)
    site = sites.most_common(1)[0][0] if sites else ""
    extra: list[InventoryDevice] = []
    disks: list[InventoryDisk] = []
    dropped: dict[str, int] = {}
    for prefix, snapshot in sources:
        if snapshot is None or not snapshot.devices:
            continue
        kept_ids = set()
        kept = [
            replace(device, source_id=f"{prefix}{device.source_id}", site=site)
            for device in snapshot.devices
            if not (device.mac_address and device.mac_address in known)
        ]
        known |= {d.mac_address for d in kept if d.mac_address}
        kept_ids = {d.source_id for d in kept}
        disks.extend(
            replace(disk, device_id=f"{prefix}{disk.device_id}")
            for disk in snapshot.disks
            if f"{prefix}{disk.device_id}" in kept_ids
        )
        dropped[prefix] = len(snapshot.devices) - len(kept)
        extra.extend(kept)
    if not extra:
        return network, dropped
    return (
        replace(
            network,
            devices=network.devices + tuple(extra),
            disks=network.disks + tuple(disks),
        ),
        dropped,
    )


def merge_protect_devices(
    network: InventorySnapshot, protect: InventorySnapshot | None
) -> tuple[InventorySnapshot, int]:
    """Protect-only merge; see ``merge_optional_devices``."""
    merged, dropped = merge_optional_devices(network, ((PROTECT_PREFIX, protect),))
    return merged, dropped.get(PROTECT_PREFIX, 0)


def map_unifi_site(
    snapshot: InventorySnapshot, netbox_site_name: str
) -> InventorySnapshot:
    """Replace UniFi site names with the configured NetBox site name."""
    site = netbox_site_name.strip()
    if not site:
        return snapshot
    return replace(
        snapshot,
        devices=tuple(replace(device, site=site) for device in snapshot.devices),
    )


def _snapshot_observation_id(source: InventorySource, device: InventoryDevice) -> str:
    key = device.source_id.strip() or device.name.strip() or "unnamed"
    return f"{source}:{key}"


def _device_count(snapshot: InventorySnapshot | None) -> int:
    return len(snapshot.devices) if snapshot else 0


def _sorted_names(items) -> tuple[str, ...]:
    return tuple(sorted({item.name.strip() for item in items if item.name.strip()}))


def _device_type_catalog(
    snapshot: InventorySnapshot,
) -> tuple[tuple[str, str, str], ...]:
    entries = {
        (item.source_id.strip(), item.manufacturer.strip(), item.model.strip())
        for item in snapshot.device_types
        if item.source_id.strip() and item.manufacturer.strip() and item.model.strip()
    }
    return tuple(
        sorted(entries, key=lambda item: (item[1].lower(), item[2].lower(), item[0]))
    )


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
