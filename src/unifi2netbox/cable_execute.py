"""Create selected cable suggestions in NetBox with the usual safeguards.

Before each create the UniFi link evidence (optional) must still report the
link, and both NetBox interfaces are re-read: a cable that already joins them
counts as done, any other cable skips the row (cables are never replaced).
Interrupted creates are looked up on the interface instead of retried. Every
created cable is read back through its A interface. Dry runs run all checks.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from unifi2netbox.cables import CablePlan, CablePlanRow
from unifi2netbox.links import InventoryLink
from unifi2netbox.network_execute import NETWORK_ERRORS, IpamBackend, NetworkOutcome
from unifi2netbox.write_execute import AMBIGUOUS_CREATE_ERRORS

CABLES = "/api/dcim/cables/"
INTERFACES = "/api/dcim/interfaces/"
OPERATION = "create_cable"


def execute_cable_plan(
    plan: CablePlan | None,
    backend: IpamBackend,
    *,
    dry_run: bool = False,
    source_links: Iterable[InventoryLink] | None = None,
    source_error: str = "",
) -> tuple[NetworkOutcome, ...]:
    if plan is None:
        return ()
    links = tuple(source_links) if source_links is not None else None
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
        elif links is not None and not still_reported(row, links):
            outcomes.append(
                _outcome(row, "skipped", "UniFi no longer reports this link; refresh.")
            )
        else:
            outcomes.append(_create(row, backend, dry_run))
    return tuple(outcomes)


def still_reported(row: CablePlanRow, links: Iterable[InventoryLink]) -> bool:
    """True when a fresh observation joins both devices on compatible ports."""

    def fits(observed: int | None, planned: int | None) -> bool:
        return observed is None or planned is None or observed == planned

    for link in links:
        for near, far in ((row.a, row.b), (row.b, row.a)):
            if (
                link.device_id == near.unifi_device_id
                and link.peer_device_id == far.unifi_device_id
                and fits(link.port_idx, near.port_idx)
                and fits(link.peer_port_idx, far.port_idx)
            ):
                return True
    return False


def _create(row: CablePlanRow, backend: IpamBackend, dry_run: bool) -> NetworkOutcome:
    a_path = f"{INTERFACES}{row.a.interface_id}/"
    b_path = f"{INTERFACES}{row.b.interface_id}/"
    try:
        a_now, b_now = backend.read_object(a_path), backend.read_object(b_path)
    except NETWORK_ERRORS as error:
        return _outcome(row, "failed", f"NetBox lookup failed: {error}")
    if a_now is None or b_now is None:
        return _outcome(row, "skipped", "A NetBox interface no longer exists; refresh.")
    existing = _cable_between(a_now, row.b.interface_id)
    if existing:
        return NetworkOutcome(
            row.key,
            OPERATION,
            row.label,
            "success",
            f"Cable already exists in NetBox (ID {existing}); nothing written.",
            existing,
        )
    busy = [
        end.label
        for end, now in ((row.a, a_now), (row.b, b_now))
        if _related_id(now.get("cable"))
    ]
    if busy:
        return _outcome(
            row,
            "skipped",
            f"{', '.join(busy)} got another cable since the preview; never replaced.",
        )
    if dry_run:
        return _outcome(row, "skipped", "Dry-run mode: not created.")
    payload = {
        "a_terminations": [
            {"object_type": "dcim.interface", "object_id": int(row.a.interface_id)}
        ],
        "b_terminations": [
            {"object_type": "dcim.interface", "object_id": int(row.b.interface_id)}
        ],
        "status": "connected",
    }
    try:
        cable_id = backend.create_object(CABLES, payload)
        message = "Created in NetBox."
    except AMBIGUOUS_CREATE_ERRORS as error:
        try:
            found = _cable_between(
                backend.read_object(a_path) or {}, row.b.interface_id
            )
        except NETWORK_ERRORS as lookup_error:
            return _outcome(
                row,
                "failed",
                f"Create was interrupted ({error}) and the lookup failed "
                f"({lookup_error}). Check NetBox before retrying.",
            )
        if not found:
            return _outcome(
                row,
                "failed",
                f"Create was interrupted ({error}); NetBox shows no cable. "
                "Refresh and review before retrying.",
            )
        cable_id, message = (
            found,
            f"Create was interrupted ({error}), but NetBox now has it.",
        )
    except NETWORK_ERRORS as error:
        return _outcome(row, "failed", str(error))
    verification, detail = _verify(backend, a_path, row.b.interface_id, cable_id)
    return NetworkOutcome(
        row.key,
        OPERATION,
        row.label,
        "success",
        message,
        cable_id,
        verification,
        detail,
    )


def _verify(
    backend: IpamBackend, a_path: str, b_interface_id: str, cable_id: str
) -> tuple[str, str]:
    try:
        row = backend.read_object(a_path)
    except NETWORK_ERRORS as error:
        return "unverified", f"Read-back failed: {error}"
    if row is None:
        return "unverified", "The interface was not found after the write."
    if _cable_between(row, b_interface_id) == str(cable_id):
        return "verified", "NetBox connects both interfaces with this cable."
    return "mismatch", "NetBox does not show the cable between both interfaces."


def _cable_between(interface: Mapping[str, object], peer_id: str) -> str:
    cable = _related_id(interface.get("cable"))
    peers = interface.get("link_peers")
    if not cable or interface.get("link_peers_type") != "dcim.interface":
        return ""
    if isinstance(peers, list) and peer_id in {_related_id(p) for p in peers}:
        return cable
    return ""


def _related_id(value: object) -> str:
    if isinstance(value, Mapping):
        value = value.get("id")
    if isinstance(value, bool) or value is None:
        return ""
    return str(value) if isinstance(value, int | str) else ""


def _outcome(row: CablePlanRow, status: str, message: str) -> NetworkOutcome:
    return NetworkOutcome(row.key, OPERATION, row.label, status, message)
