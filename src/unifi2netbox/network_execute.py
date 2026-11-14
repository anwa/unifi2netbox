"""Execute a network plan against NetBox IPAM with the same safeguards as devices.

Order: VLAN group, then VLANs, then prefixes, so a new prefix can link the VLAN
created in the same run. Before each write the UniFi network (optional) and
the NetBox object are re-read; objects that appeared or changed since the
preview are skipped. Interrupted creates are looked up instead of retried.
Every successful write is read back and marked verified, mismatch or
unverified. Dry runs perform all checks without writing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import requests

from unifi2netbox.inventory import InventoryNetwork
from unifi2netbox.networks import CREATE, NetworkPlan, NetworkPlanRow
from unifi2netbox.write_execute import AMBIGUOUS_CREATE_ERRORS, WriteExecutionError

GROUPS = "/api/ipam/vlan-groups/"
VLANS = "/api/ipam/vlans/"
PREFIXES = "/api/ipam/prefixes/"
NETWORK_ERRORS = (WriteExecutionError, requests.exceptions.RequestException)


class IpamBackend(Protocol):
    def find_ids(self, path: str, **filters: object) -> tuple[str, ...]: ...

    def read_object(self, path: str) -> dict[str, object] | None: ...

    def create_object(self, path: str, payload: dict[str, object]) -> str: ...

    def update_object(self, path: str, payload: dict[str, object]) -> None: ...


@dataclass(frozen=True)
class NetworkOutcome:
    key: str
    operation: str
    label: str
    status: str
    message: str
    object_id: str = ""
    verification: str = ""
    verification_detail: str = ""


class _Skip(Exception):  # noqa: N818 - control flow inside one operation
    pass


def execute_network_plan(
    plan: NetworkPlan | None,
    backend: IpamBackend,
    *,
    dry_run: bool = False,
    source_networks: Mapping[str, InventoryNetwork] | None = None,
    source_error: str = "",
) -> tuple[NetworkOutcome, ...]:
    """Run the selected parts of the plan and return one outcome per write."""
    if plan is None or plan.group is None or not plan.selected_rows():
        return ()
    outcomes: list[NetworkOutcome] = []
    rows = plan.selected_rows()
    if source_error:
        return tuple(
            NetworkOutcome(
                row.key,
                "network",
                row.name,
                "skipped",
                f"UniFi could not be re-read before writing ({source_error}); "
                "nothing was written.",
            )
            for row in rows
        )

    site_id = int(plan.group.site_id)
    group_id = plan.group.netbox_id
    group_label = plan.group.name
    if plan.group.action == CREATE:
        payload = {
            "name": plan.group.name,
            "slug": plan.group.slug,
            "scope_type": "dcim.site",
            "scope_id": site_id,
        }
        outcome, group_id = _create(
            backend,
            GROUPS,
            payload,
            lookup={"slug": plan.group.slug},
            key="network-group",
            operation="create_vlan_group",
            label=group_label,
            dry_run=dry_run,
            exists_status="success",
            exists_message="VLAN group already exists (ID {id}); it is used.",
        )
        outcomes.append(outcome)

    vlan_ids: dict[int, str] = {}
    for row in rows:
        if row.netbox_vlan_id:
            vlan_ids[row.vid] = row.netbox_vlan_id
    current = {row.key: _source_issue(row, source_networks) for row in rows}

    for row in rows:
        if not row.vlan_selected:
            continue
        label = f"VLAN {row.vid} {row.name}"
        if current[row.key]:
            outcomes.append(
                NetworkOutcome(
                    row.key, _vlan_op(row), label, "skipped", current[row.key]
                )
            )
            continue
        if row.vlan_action == CREATE:
            if not group_id:
                outcomes.append(
                    NetworkOutcome(
                        row.key,
                        "create_vlan",
                        label,
                        "skipped" if dry_run else "failed",
                        "Dry run: the VLAN group does not exist yet."
                        if dry_run
                        else "The VLAN group is not available; VLAN not created.",
                    )
                )
                continue
            payload = {
                "vid": row.vid,
                "name": row.name,
                "group": int(group_id),
                "status": "active",
            }
            outcome, vlan_id = _create(
                backend,
                VLANS,
                payload,
                lookup={"group_id": group_id, "vid": row.vid},
                key=row.key,
                operation="create_vlan",
                label=label,
                dry_run=dry_run,
            )
            outcomes.append(outcome)
            if vlan_id:
                vlan_ids[row.vid] = vlan_id
        else:
            outcomes.append(_update_vlan(backend, row, label, dry_run))

    for row in rows:
        if not row.prefix_selected:
            continue
        label = f"Prefix {row.subnet}"
        if current[row.key]:
            outcomes.append(
                NetworkOutcome(
                    row.key, _prefix_op(row), label, "skipped", current[row.key]
                )
            )
            continue
        vlan_id = vlan_ids.get(row.vid, "")
        if row.prefix_action == CREATE:
            payload: dict[str, object] = {
                "prefix": row.subnet,
                "status": "active",
                "scope_type": "dcim.site",
                "scope_id": site_id,
                "description": row.name,
            }
            if vlan_id:
                payload["vlan"] = int(vlan_id)
            outcome, _ = _create(
                backend,
                PREFIXES,
                payload,
                lookup={"prefix": row.subnet},
                key=row.key,
                operation="create_prefix",
                label=label,
                dry_run=dry_run,
            )
            outcomes.append(outcome)
        else:
            outcomes.append(_update_prefix(backend, row, label, vlan_id, dry_run))
    return tuple(outcomes)


def _source_issue(
    row: NetworkPlanRow, sources: Mapping[str, InventoryNetwork] | None
) -> str:
    if sources is None:
        return ""
    network = sources.get(row.key)
    if network is None:
        return "UniFi no longer reports this network; refresh before writing."
    changed = [
        name
        for name, before, now in (
            ("name", row.name, network.name),
            ("VLAN", row.vid, network.vlan_id),
            ("subnet", row.subnet, network.subnet),
            ("enabled", row.enabled, network.enabled),
        )
        if before != now
    ]
    if changed:
        return (
            f"UniFi network changed since the preview ({', '.join(changed)}); "
            "refresh and review before writing."
        )
    return ""


def _create(
    backend: IpamBackend,
    path: str,
    payload: dict[str, object],
    *,
    lookup: dict[str, object],
    key: str,
    operation: str,
    label: str,
    dry_run: bool,
    exists_status: str = "skipped",
    exists_message: str = "Already exists in NetBox (ID {id}); refresh the preview.",
) -> tuple[NetworkOutcome, str]:
    try:
        existing = backend.find_ids(path, **lookup)
    except NETWORK_ERRORS as error:
        return (
            NetworkOutcome(
                key, operation, label, "failed", f"NetBox lookup failed: {error}"
            ),
            "",
        )
    if len(existing) == 1:
        message = exists_message.format(id=existing[0])
        return NetworkOutcome(
            key, operation, label, exists_status, message, existing[0]
        ), existing[0]
    if existing:
        return (
            NetworkOutcome(
                key,
                operation,
                label,
                "skipped",
                f"NetBox already has several matches (IDs {', '.join(existing)}).",
            ),
            "",
        )
    if dry_run:
        return (
            NetworkOutcome(
                key, operation, label, "skipped", "Dry-run mode: not created."
            ),
            "",
        )
    try:
        object_id = backend.create_object(path, payload)
        message = "Created in NetBox."
    except AMBIGUOUS_CREATE_ERRORS as error:
        try:
            found = backend.find_ids(path, **lookup)
        except NETWORK_ERRORS as lookup_error:
            return (
                NetworkOutcome(
                    key,
                    operation,
                    label,
                    "failed",
                    f"Create was interrupted ({error}) and the lookup failed "
                    f"({lookup_error}). Check NetBox before retrying.",
                ),
                "",
            )
        if len(found) != 1:
            return (
                NetworkOutcome(
                    key,
                    operation,
                    label,
                    "failed",
                    f"Create was interrupted ({error}); NetBox has "
                    f"{len(found)} matches. Refresh and review.",
                ),
                "",
            )
        object_id = found[0]
        message = f"Create was interrupted ({error}), but NetBox now has it."
    except NETWORK_ERRORS as error:
        return NetworkOutcome(key, operation, label, "failed", str(error)), ""
    verification, detail = _verify(backend, f"{path}{object_id}/", payload)
    return (
        NetworkOutcome(
            key, operation, label, "success", message, object_id, verification, detail
        ),
        object_id,
    )


def _update_vlan(
    backend: IpamBackend, row: NetworkPlanRow, label: str, dry_run: bool
) -> NetworkOutcome:
    path = f"{VLANS}{row.netbox_vlan_id}/"
    try:
        current = backend.read_object(path)
        if current is None:
            raise _Skip("NetBox VLAN no longer exists; refresh before writing.")
        if str(current.get("name", "")).strip() != row.netbox_vlan_name:
            raise _Skip("NetBox VLAN changed since the preview (name); refresh.")
        if dry_run:
            raise _Skip("Dry-run mode: not updated.")
        payload = {"name": row.name}
        backend.update_object(path, payload)
    except _Skip as skip:
        return NetworkOutcome(row.key, "update_vlan", label, "skipped", str(skip))
    except NETWORK_ERRORS as error:
        return NetworkOutcome(row.key, "update_vlan", label, "failed", str(error))
    verification, detail = _verify(backend, path, payload)
    return NetworkOutcome(
        row.key,
        "update_vlan",
        label,
        "success",
        "Updated in NetBox.",
        row.netbox_vlan_id,
        verification,
        detail,
    )


def _update_prefix(
    backend: IpamBackend,
    row: NetworkPlanRow,
    label: str,
    vlan_id: str,
    dry_run: bool,
) -> NetworkOutcome:
    path = f"{PREFIXES}{row.netbox_prefix_id}/"
    try:
        if not vlan_id:
            raise _Skip("The VLAN is not in NetBox; the prefix cannot be linked.")
        current = backend.read_object(path)
        if current is None:
            raise _Skip("NetBox prefix no longer exists; refresh before writing.")
        if current.get("vlan"):
            raise _Skip("NetBox prefix got a VLAN since the preview; refresh.")
        if dry_run:
            raise _Skip("Dry-run mode: not updated.")
        payload = {"vlan": int(vlan_id)}
        backend.update_object(path, payload)
    except _Skip as skip:
        return NetworkOutcome(row.key, "update_prefix", label, "skipped", str(skip))
    except NETWORK_ERRORS as error:
        return NetworkOutcome(row.key, "update_prefix", label, "failed", str(error))
    verification, detail = _verify(backend, path, payload)
    return NetworkOutcome(
        row.key,
        "update_prefix",
        label,
        "success",
        "Linked to its VLAN in NetBox.",
        row.netbox_prefix_id,
        verification,
        detail,
    )


def _verify(
    backend: IpamBackend, path: str, payload: dict[str, object]
) -> tuple[str, str]:
    try:
        row = backend.read_object(path)
    except NETWORK_ERRORS as error:
        return "unverified", f"Read-back failed: {error}"
    if row is None:
        return "unverified", "The object was not found after the write."
    mismatches = [
        f"{key}: expected {value}, NetBox has {_value(row, key) or '-'}"
        for key, value in payload.items()
        if _value(row, key) != str(value)
    ]
    if mismatches:
        return "mismatch", "; ".join(mismatches)
    return "verified", "NetBox matches the written values."


def _value(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if isinstance(value, Mapping):
        nested = value.get("value") if key == "status" else value.get("id")
        return "" if nested is None else str(nested)
    return "" if value is None else str(value)


def _vlan_op(row: NetworkPlanRow) -> str:
    return "create_vlan" if row.vlan_action == CREATE else "update_vlan"


def _prefix_op(row: NetworkPlanRow) -> str:
    return "create_prefix" if row.prefix_action == CREATE else "update_prefix"
