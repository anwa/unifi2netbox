"""Shared create/update/read-back of single NetBox objects.

Used for inventory items (drive bays, SFP modules), wireless LANs, IP ranges
and reserved IP addresses. Creates look the object up first and never
duplicate it; an interrupted create is looked up again instead of retried.
Updates re-read the object, skip it when a planned field changed since the
preview and PATCH only the changed fields. Every write is read back. Dry runs
run all checks. Nothing is ever deleted.

Values are compared as text: related objects and choices by their ``id`` or
``value``, integers as digits. Fields listed in ``ObjectKind.id_fields`` are
sent as integers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from unifi2netbox.network_execute import NETWORK_ERRORS, IpamBackend, NetworkOutcome
from unifi2netbox.write_execute import AMBIGUOUS_CREATE_ERRORS


@dataclass(frozen=True)
class ObjectKind:
    path: str
    noun: str
    create_operation: str
    update_operation: str
    id_fields: frozenset[str] = frozenset()


class PlannedRow(Protocol):
    key: str
    label: str
    action: str


def object_value(obj: Mapping[str, object], field: str) -> str:
    """Comparable text of one NetBox field."""
    value = obj.get(field)
    if isinstance(value, Mapping):
        value = value.get("id", value.get("value"))
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    return value.strip() if isinstance(value, str) else ""


def payload_value(kind: ObjectKind, field: str, value: str) -> object:
    return int(value) if field in kind.id_fields and value.isdigit() else value


def create_object(
    row: PlannedRow,
    kind: ObjectKind,
    backend: IpamBackend,
    dry_run: bool,
    *,
    lookup: Mapping[str, object],
    name: str,
    payload: Mapping[str, str],
    extra: Mapping[str, object] | None = None,
) -> NetworkOutcome:
    """Create ``payload`` (plus ``extra``) unless ``lookup`` finds an object."""
    try:
        existing = backend.find_ids(kind.path, **lookup)
    except NETWORK_ERRORS as error:
        return outcome(row, kind, "failed", f"NetBox lookup failed: {error}")
    if existing:
        return outcome(
            row,
            kind,
            "skipped",
            f"NetBox got the {kind.noun} {name} since the preview; refresh.",
        )
    if dry_run:
        return outcome(row, kind, "skipped", "Dry-run mode: not created.")
    fields = {field: value for field, value in payload.items() if value}
    body: dict[str, object] = dict(extra or {})
    body.update({f: payload_value(kind, f, v) for f, v in fields.items()})
    try:
        object_id = backend.create_object(kind.path, body)
        message = "Created in NetBox."
    except AMBIGUOUS_CREATE_ERRORS as error:
        try:
            found = backend.find_ids(kind.path, **lookup)
        except NETWORK_ERRORS as lookup_error:
            return outcome(
                row,
                kind,
                "failed",
                f"Create was interrupted ({error}) and the lookup failed "
                f"({lookup_error}). Check NetBox before retrying.",
            )
        if len(found) != 1:
            return outcome(
                row,
                kind,
                "failed",
                f"Create was interrupted ({error}); NetBox shows no single "
                f"{kind.noun}. Refresh and review before retrying.",
            )
        object_id, message = (
            found[0],
            f"Create was interrupted ({error}), but NetBox now has it.",
        )
    except NETWORK_ERRORS as error:
        return outcome(row, kind, "failed", str(error))
    verification, detail = verify(backend, kind, object_id, fields)
    return NetworkOutcome(
        row.key,
        kind.create_operation,
        row.label,
        "success",
        message,
        str(object_id),
        verification,
        detail,
    )


def update_object(
    row: PlannedRow,
    kind: ObjectKind,
    backend: IpamBackend,
    dry_run: bool,
    *,
    object_id: str,
    changes: tuple[tuple[str, str, str], ...],
) -> NetworkOutcome:
    """PATCH ``changes`` (field, planned current, desired) after a drift check."""
    path = f"{kind.path}{object_id}/"
    try:
        current = backend.read_object(path)
    except NETWORK_ERRORS as error:
        return outcome(row, kind, "failed", str(error))
    if current is None:
        return outcome(
            row, kind, "skipped", f"The NetBox {kind.noun} no longer exists; refresh."
        )
    drifted = [f for f, before, _ in changes if object_value(current, f) != before]
    if drifted:
        return outcome(
            row,
            kind,
            "skipped",
            f"NetBox {kind.noun} changed since the preview ({', '.join(drifted)}); "
            "refresh.",
        )
    if dry_run:
        return outcome(row, kind, "skipped", "Dry-run mode: not updated.")
    desired = {field: value for field, _, value in changes}
    body = {f: payload_value(kind, f, v) for f, v in desired.items()}
    try:
        backend.update_object(path, body)
    except NETWORK_ERRORS as error:
        return outcome(row, kind, "failed", str(error))
    verification, detail = verify(backend, kind, object_id, desired)
    return NetworkOutcome(
        row.key,
        kind.update_operation,
        row.label,
        "success",
        f"Updated in NetBox ({', '.join(body)}).",
        object_id,
        verification,
        detail,
    )


def verify(
    backend: IpamBackend, kind: ObjectKind, object_id: str, expected: Mapping[str, str]
) -> tuple[str, str]:
    try:
        obj = backend.read_object(f"{kind.path}{object_id}/")
    except NETWORK_ERRORS as error:
        return "unverified", f"Read-back failed: {error}"
    if obj is None:
        return "unverified", f"The {kind.noun} was not found after the write."
    mismatches = [f for f, value in expected.items() if object_value(obj, f) != value]
    if mismatches:
        return "mismatch", f"NetBox differs in {', '.join(mismatches)}."
    return "verified", "NetBox matches the written values."


def outcome(
    row: PlannedRow, kind: ObjectKind, status: str, message: str
) -> NetworkOutcome:
    operation = (
        kind.create_operation if row.action == "create" else kind.update_operation
    )
    return NetworkOutcome(row.key, operation, row.label, status, message)
