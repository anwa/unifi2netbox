"""Write selected interface configuration changes to NetBox.

Safeguards match device and network writes: UniFi is re-read and rows whose
port configuration changed since the preview are skipped; each NetBox interface
is re-read and skipped when a selected field no longer has its preview value;
dry runs run every check without writing; every write is read back.
Interfaces are only updated (PATCH), never created or deleted.
"""

from __future__ import annotations

from collections.abc import Mapping

from unifi2netbox.interface_plan import (
    ENABLED,
    MODE,
    TAGGED_VLANS,
    UNTAGGED,
    InterfacePlan,
    InterfacePlanRow,
)
from unifi2netbox.network_execute import NETWORK_ERRORS, IpamBackend, NetworkOutcome
from unifi2netbox.port_config import InventoryPortConfig

INTERFACES = "/api/dcim/interfaces/"
OPERATION = "update_interface"


def execute_interface_plan(
    plan: InterfacePlan | None,
    backend: IpamBackend,
    *,
    dry_run: bool = False,
    source_configs: Mapping[tuple[str, int], InventoryPortConfig] | None = None,
    source_error: str = "",
) -> tuple[NetworkOutcome, ...]:
    """Run the selected interface rows and return one outcome per interface."""
    if plan is None:
        return ()
    outcomes = []
    for row in plan.selected_rows():
        if source_error:
            outcomes.append(
                _outcome(
                    row,
                    "skipped",
                    f"UniFi could not be re-read before writing ({source_error}); "
                    "nothing was written.",
                )
            )
            continue
        outcomes.append(_execute_row(row, backend, dry_run, source_configs))
    return tuple(outcomes)


def _execute_row(
    row: InterfacePlanRow,
    backend: IpamBackend,
    dry_run: bool,
    source_configs: Mapping[tuple[str, int], InventoryPortConfig] | None,
) -> NetworkOutcome:
    if source_configs is not None:
        fresh = source_configs.get((row.unifi_device_id, row.port_idx))
        if fresh != row.config:
            return _outcome(
                row,
                "skipped",
                "UniFi port configuration changed since the preview; refresh.",
            )
    path = f"{INTERFACES}{row.interface_id}/"
    changes = row.selected_changes()
    try:
        current = backend.read_object(path)
    except NETWORK_ERRORS as error:
        return _outcome(row, "failed", str(error))
    if current is None:
        return _outcome(
            row, "skipped", "NetBox interface no longer exists; refresh before writing."
        )
    changed = [c.field for c in changes if read_field(current, c.field) != c.current]
    if changed:
        return _outcome(
            row,
            "skipped",
            f"NetBox interface changed since the preview ({', '.join(changed)}); "
            "refresh.",
        )
    if dry_run:
        return _outcome(row, "skipped", "Dry-run mode: not updated.")
    payload = {c.field: _payload_value(c.field, c.desired) for c in changes}
    try:
        backend.update_object(path, payload)
    except NETWORK_ERRORS as error:
        return _outcome(row, "failed", str(error))
    verification, detail = _verify(backend, path, changes)
    return NetworkOutcome(
        row.key,
        OPERATION,
        row.label,
        "success",
        f"Updated in NetBox ({', '.join(payload)}).",
        row.interface_id,
        verification,
        detail,
    )


def read_field(interface: Mapping[str, object], field: str) -> object:
    """Comparable value of one interface field from a NetBox API row."""
    if field == ENABLED:
        return interface.get("enabled") is not False
    if field == MODE:
        value = interface.get("mode")
        if isinstance(value, Mapping):
            value = value.get("value")
        return value if isinstance(value, str) else ""
    if field == UNTAGGED:
        return _related_id(interface.get("untagged_vlan"))
    if field == TAGGED_VLANS:
        values = interface.get("tagged_vlans")
        ids = {_related_id(item) for item in values} if isinstance(values, list) else ()
        return tuple(sorted((i for i in ids if i), key=_numeric))
    raise ValueError(field)


def _payload_value(field: str, value: object) -> object:
    if field == UNTAGGED:
        return int(str(value)) if value else None
    if field == TAGGED_VLANS:
        return [int(item) for item in value] if isinstance(value, tuple) else []
    if field == MODE:
        return value or None
    return value


def _verify(backend: IpamBackend, path: str, changes) -> tuple[str, str]:
    try:
        row = backend.read_object(path)
    except NETWORK_ERRORS as error:
        return "unverified", f"Read-back failed: {error}"
    if row is None:
        return "unverified", "The interface was not found after the write."
    mismatches = [
        f"{c.field}: expected {c.desired_label}"
        for c in changes
        if read_field(row, c.field) != c.desired
    ]
    if mismatches:
        return "mismatch", "; ".join(mismatches)
    return "verified", "NetBox matches the written values."


def _outcome(row: InterfacePlanRow, status: str, message: str) -> NetworkOutcome:
    return NetworkOutcome(row.key, OPERATION, row.label, status, message)


def _related_id(value: object) -> str:
    if isinstance(value, Mapping):
        value = value.get("id")
    if isinstance(value, bool) or value is None:
        return ""
    return str(value) if isinstance(value, int | str) else ""


def _numeric(value: str) -> tuple[int, str]:
    return (int(value), "") if value.isdigit() else (0, value)
