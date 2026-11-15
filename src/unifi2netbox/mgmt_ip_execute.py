"""Write selected management IPs to NetBox with the usual safeguards.

Before writing, UniFi is re-read (the device must still report the same IP)
and NetBox is re-read: the device's primary IPv4 must be unchanged, a planned
interface or IP must still be missing, and an IP to assign must still be
unassigned; otherwise the row is skipped. Steps run in order (interface, IP,
primary IPv4); an interrupted create is looked up instead of retried, and the
result is read back. Dry runs run all checks. Nothing is deleted.
"""

from __future__ import annotations

from collections.abc import Mapping

from unifi2netbox.inventory import InventoryDevice
from unifi2netbox.mgmt_ip import INTERFACE_NAME, MgmtIpPlan, MgmtIpRow
from unifi2netbox.network_execute import NETWORK_ERRORS, IpamBackend, NetworkOutcome
from unifi2netbox.write_execute import AMBIGUOUS_CREATE_ERRORS

DEVICES = "/api/dcim/devices/"
INTERFACES = "/api/dcim/interfaces/"
ADDRESSES = "/api/ipam/ip-addresses/"
OPERATION = "set_management_ip"


class _Stop(Exception):  # noqa: N818 - ends one row with an outcome
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def execute_mgmt_ip_plan(
    plan: MgmtIpPlan | None,
    backend: IpamBackend,
    *,
    dry_run: bool = False,
    source_devices: Mapping[str, InventoryDevice] | None = None,
    source_error: str = "",
) -> tuple[NetworkOutcome, ...]:
    """``source_devices`` maps UniFi device IDs to freshly read devices."""
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
        fresh = source_devices.get(row.unifi_device_id) if source_devices else None
        if source_devices is not None and (fresh is None or fresh.ip_address != row.ip):
            outcomes.append(
                _outcome(row, "skipped", "UniFi reports another IP now; refresh.")
            )
            continue
        outcomes.append(_execute(row, backend, dry_run))
    return tuple(outcomes)


def _execute(row: MgmtIpRow, backend: IpamBackend, dry_run: bool) -> NetworkOutcome:
    done: list[str] = []
    try:
        _check(row, backend)
        if dry_run:
            return _outcome(
                row, "skipped", f"Dry-run mode: not written ({row.describe()})."
            )
        interface_id = row.interface_id
        if "create_interface" in row.steps:
            interface_id = _create(
                backend,
                INTERFACES,
                {
                    "device": int(row.netbox_device_id),
                    "name": INTERFACE_NAME,
                    "type": "virtual",
                    "mgmt_only": True,
                    "description": "Management interface (unifi2netbox)",
                },
                {"device_id": row.netbox_device_id, "name": INTERFACE_NAME},
            )
            done.append(f"created interface {INTERFACE_NAME}")
        ip_id = row.ip_id
        assignment = {
            "assigned_object_type": "dcim.interface",
            "assigned_object_id": int(interface_id),
        }
        if "create_ip" in row.steps:
            ip_id = _create(
                backend,
                ADDRESSES,
                {
                    "address": row.address,
                    "status": "active",
                    "description": "Management IP from UniFi",
                    **assignment,
                },
                {"address": row.ip},
            )
            done.append(f"created {row.address}")
        elif "assign_ip" in row.steps:
            backend.update_object(f"{ADDRESSES}{ip_id}/", assignment)
            done.append(f"assigned {row.ip}")
        backend.update_object(
            f"{DEVICES}{row.netbox_device_id}/", {"primary_ip4": int(ip_id)}
        )
        done.append("set the primary IPv4")
    except _Stop as stop:
        return _outcome(row, stop.status, _with_done(stop.message, done))
    except NETWORK_ERRORS as error:
        return _outcome(row, "failed", _with_done(str(error), done))
    verification, detail = _verify(backend, row, interface_id, ip_id)
    return NetworkOutcome(
        row.key,
        OPERATION,
        row.label,
        "success",
        "Written to NetBox: " + ", ".join(done) + ".",
        str(ip_id),
        verification,
        detail,
    )


def _check(row: MgmtIpRow, backend: IpamBackend) -> None:
    device = backend.read_object(f"{DEVICES}{row.netbox_device_id}/")
    if device is None:
        raise _Stop("skipped", "The NetBox device no longer exists; refresh.")
    if _related_id(device.get("primary_ip4")) != row.current_primary_id:
        raise _Stop(
            "skipped", "The NetBox primary IPv4 changed since the preview; refresh."
        )
    if "create_interface" in row.steps:
        if backend.find_ids(
            INTERFACES, device_id=row.netbox_device_id, name=INTERFACE_NAME
        ):
            raise _Stop(
                "skipped",
                f"NetBox got an interface {INTERFACE_NAME} since the preview; refresh.",
            )
    elif backend.read_object(f"{INTERFACES}{row.interface_id}/") is None:
        raise _Stop("skipped", "The NetBox interface no longer exists; refresh.")
    if "create_ip" in row.steps:
        if backend.find_ids(ADDRESSES, address=row.ip):
            raise _Stop(
                "skipped", f"NetBox got the IP {row.ip} since the preview; refresh."
            )
    else:
        current = backend.read_object(f"{ADDRESSES}{row.ip_id}/")
        if current is None:
            raise _Stop("skipped", "The NetBox IP address no longer exists; refresh.")
        if "assign_ip" in row.steps and current.get("assigned_object_id"):
            raise _Stop(
                "skipped", "The NetBox IP was assigned since the preview; refresh."
            )


def _create(
    backend: IpamBackend,
    path: str,
    payload: dict[str, object],
    lookup: dict[str, object],
) -> str:
    try:
        return backend.create_object(path, payload)
    except AMBIGUOUS_CREATE_ERRORS as error:
        try:
            found = backend.find_ids(path, **lookup)
        except NETWORK_ERRORS as lookup_error:
            raise _Stop(
                "failed",
                f"Create was interrupted ({error}) and the lookup failed "
                f"({lookup_error}). Check NetBox before retrying.",
            ) from error
        if len(found) != 1:
            raise _Stop(
                "failed",
                f"Create was interrupted ({error}); NetBox shows no single result. "
                "Refresh and review before retrying.",
            ) from error
        return found[0]


def _verify(
    backend: IpamBackend, row: MgmtIpRow, interface_id: str, ip_id: str
) -> tuple[str, str]:
    try:
        device = backend.read_object(f"{DEVICES}{row.netbox_device_id}/")
        address = backend.read_object(f"{ADDRESSES}{ip_id}/")
    except NETWORK_ERRORS as error:
        return "unverified", f"Read-back failed: {error}"
    if device is None or address is None:
        return "unverified", "The device or IP was not found after the write."
    problems = []
    if _related_id(device.get("primary_ip4")) != str(ip_id):
        problems.append("primary IPv4")
    if str(address.get("assigned_object_id", "")) != str(interface_id):
        problems.append("interface assignment")
    if problems:
        return "mismatch", f"NetBox differs in {', '.join(problems)}."
    return "verified", "NetBox matches the written values."


def _related_id(value: object) -> str:
    if isinstance(value, Mapping):
        value = value.get("id")
    return "" if value is None else str(value).strip()


def _with_done(message: str, done: list[str]) -> str:
    if not done:
        return message
    return f"{message} Already done: {', '.join(done)}; a refresh shows the state."


def _outcome(row: MgmtIpRow, status: str, message: str) -> NetworkOutcome:
    return NetworkOutcome(row.key, OPERATION, row.label, status, message)
