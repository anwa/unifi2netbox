"""Plan and create the NetBox Custom Field ``firmware`` (M11).

This is the only Custom Field the app may create, and never silently: when it
is missing, the plan proposes its creation as a visible, selectable first
operation. A field with the same name but another type or without the device
object type is a conflict; the app then neither changes it nor writes
firmware values.

Creation looks the name up first, never duplicates the field, reconciles an
interrupted create by name instead of retrying it, and reads the result back.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from unifi2netbox.inventory import FIRMWARE_FIELD, InventoryCustomField
from unifi2netbox.network_execute import NETWORK_ERRORS, IpamBackend, NetworkOutcome
from unifi2netbox.write_execute import AMBIGUOUS_CREATE_ERRORS

CUSTOM_FIELDS = "/api/extras/custom-fields/"
CREATE_OPERATION = "create_custom_field"
KEY = f"custom-field:{FIRMWARE_FIELD}"
LABEL = f"Custom Field {FIRMWARE_FIELD}"
OBJECT_TYPE = "dcim.device"
PAYLOAD: dict[str, object] = {
    "name": FIRMWARE_FIELD,
    "label": "Firmware",
    "type": "text",
    "object_types": [OBJECT_TYPE],
    "description": "Firmware version reported by UniFi (written by unifi2netbox).",
    "required": False,
}

PRESENT = "present"
CREATE = "create"
CONFLICT = "conflict"
UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class CustomFieldPlan:
    action: str
    netbox_id: str = ""
    selected: bool = False
    message: str = ""

    @property
    def selectable(self) -> bool:
        return self.action == CREATE

    @property
    def operation_count(self) -> int:
        return 1 if self.selectable and self.selected else 0

    @property
    def firmware_writable(self) -> bool:
        """Firmware values can be written in this run (field exists or is planned)."""
        return self.action == PRESENT or (self.action == CREATE and self.selected)


def build_custom_field_plan(
    custom_fields: Iterable[InventoryCustomField], read_error: str = ""
) -> CustomFieldPlan:
    if read_error:
        return CustomFieldPlan(
            UNAVAILABLE,
            message=(
                f"{read_error} Firmware is not written; give the token read "
                "access to Custom Fields and refresh."
            ),
        )
    matches = [field for field in custom_fields if field.name == FIRMWARE_FIELD]
    if not matches:
        return CustomFieldPlan(
            CREATE,
            selected=True,
            message=(
                "NetBox has no Custom Field 'firmware'; it is created (text, for "
                "devices) before firmware values are written."
            ),
        )
    field = matches[0]
    if field.type != "text" or OBJECT_TYPE not in field.object_types:
        return CustomFieldPlan(
            CONFLICT,
            netbox_id=field.source_id,
            message=(
                "NetBox already has a Custom Field 'firmware' that is not a text "
                "field for devices; it is not changed and firmware is not written."
            ),
        )
    return CustomFieldPlan(
        PRESENT,
        netbox_id=field.source_id,
        message="NetBox has the Custom Field 'firmware'.",
    )


def select_custom_field(plan: CustomFieldPlan, selected: bool) -> CustomFieldPlan:
    return replace(plan, selected=selected) if plan.selectable else plan


def execute_custom_field_plan(
    plan: CustomFieldPlan | None, backend: IpamBackend, *, dry_run: bool = False
) -> tuple[tuple[NetworkOutcome, ...], bool]:
    """Create the field when planned; returns (outcomes, firmware writable).

    In a dry run the field counts as writable when its creation would run, so
    the device dry run checks the firmware values too.
    """
    if plan is None:
        return (), False
    if plan.action == PRESENT:
        return (), True
    if not plan.operation_count:
        return (), False
    try:
        existing = backend.find_ids(CUSTOM_FIELDS, name=FIRMWARE_FIELD)
    except NETWORK_ERRORS as error:
        return (_outcome("failed", f"NetBox lookup failed: {error}"),), False
    if existing:
        return (
            _outcome(
                "skipped",
                "NetBox got a Custom Field 'firmware' since the preview; refresh "
                "and review it before writing firmware.",
            ),
        ), False
    if dry_run:
        return (_outcome("skipped", "Dry-run mode: not created."),), True
    try:
        field_id = backend.create_object(CUSTOM_FIELDS, dict(PAYLOAD))
        message = "Created in NetBox."
    except AMBIGUOUS_CREATE_ERRORS as error:
        try:
            found = backend.find_ids(CUSTOM_FIELDS, name=FIRMWARE_FIELD)
        except NETWORK_ERRORS as lookup_error:
            return (
                _outcome(
                    "failed",
                    f"Create was interrupted ({error}) and the lookup failed "
                    f"({lookup_error}). Check NetBox before retrying.",
                ),
            ), False
        if len(found) != 1:
            return (
                _outcome(
                    "failed",
                    f"Create was interrupted ({error}); NetBox shows no single "
                    "field. Refresh and review before retrying.",
                ),
            ), False
        field_id = found[0]
        message = f"Create was interrupted ({error}), but NetBox now has it."
    except NETWORK_ERRORS as error:
        text = str(error)
        if "permission" in text.lower():
            text += " The token needs permission to add Custom Fields."
        return (_outcome("failed", text),), False
    verification, detail = _verify(backend, field_id)
    outcome = NetworkOutcome(
        KEY,
        CREATE_OPERATION,
        LABEL,
        "success",
        message,
        str(field_id),
        verification,
        detail,
    )
    return (outcome,), verification != "mismatch"


def _verify(backend: IpamBackend, field_id: str) -> tuple[str, str]:
    try:
        row = backend.read_object(f"{CUSTOM_FIELDS}{field_id}/")
    except NETWORK_ERRORS as error:
        return "unverified", f"Read-back failed: {error}"
    if row is None:
        return "unverified", "The field was not found after the write."
    kind = row.get("type")
    kind = kind.get("value") if isinstance(kind, dict) else kind
    types = row.get("object_types")
    if (
        row.get("name") != FIRMWARE_FIELD
        or kind != "text"
        or not isinstance(types, list)
        or OBJECT_TYPE not in types
    ):
        return "mismatch", "NetBox differs in name, type or object types."
    return "verified", "NetBox matches the written values."


def _outcome(status: str, message: str) -> NetworkOutcome:
    return NetworkOutcome(KEY, CREATE_OPERATION, LABEL, status, message)
