"""Create NetBox objects from the "New" dialogs of the device type editor.

Kinds: manufacturers, platforms, owners, owner groups, tags and inventory
item roles. Each create is an explicit user action (the dialog's Create
button): NetBox is looked up first so nothing is duplicated (an existing
object with the same name or slug is returned instead), an interrupted create
is looked up instead of retried, the object is read back, and the run is
saved to the write history.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from unifi2netbox.devicetypes import slugify
from unifi2netbox.journal_store import (
    JournalStore,
    JournalStoreError,
    StoredOutcome,
    StoredRun,
)
from unifi2netbox.netbox_catalog import KINDS, CatalogObject, NetBoxCatalog
from unifi2netbox.network_execute import NETWORK_ERRORS, IpamBackend
from unifi2netbox.write_execute import AMBIGUOUS_CREATE_ERRORS


@dataclass(frozen=True)
class FieldDef:
    name: str
    label: str
    required: bool = False
    kind: str = "text"  # text, slug, color, reference
    reference: str = ""  # catalog kind for references


SPECS: dict[str, tuple[FieldDef, ...]] = {
    "manufacturers": (
        FieldDef("name", "Name", True),
        FieldDef("slug", "Slug", True, "slug"),
        FieldDef("description", "Description"),
    ),
    "platforms": (
        FieldDef("name", "Name", True),
        FieldDef("slug", "Slug", True, "slug"),
        FieldDef("manufacturer", "Manufacturer", False, "reference", "manufacturers"),
        FieldDef("description", "Description"),
    ),
    "owner_groups": (
        FieldDef("name", "Name", True),
        FieldDef("description", "Description"),
    ),
    "owners": (
        FieldDef("name", "Name", True),
        FieldDef("group", "Owner group", True, "reference", "owner_groups"),
        FieldDef("description", "Description"),
    ),
    "tags": (
        FieldDef("name", "Name", True),
        FieldDef("slug", "Slug", True, "slug"),
        FieldDef("color", "Color", False, "color"),
        FieldDef("description", "Description"),
    ),
    "inventory_item_roles": (
        FieldDef("name", "Name", True),
        FieldDef("slug", "Slug", True, "slug"),
        FieldDef("color", "Color", False, "color"),
        FieldDef("description", "Description"),
    ),
}
TITLES = {
    "manufacturers": "manufacturer",
    "platforms": "platform",
    "owner_groups": "owner group",
    "owners": "owner",
    "tags": "tag",
    "inventory_item_roles": "inventory item role",
}
OPERATION = "create_netbox_object"


class ObjectCreateError(ValueError):
    pass


@dataclass(frozen=True)
class CreateResult:
    item: CatalogObject | None
    status: str  # success, existing, failed
    message: str
    verification: str = ""


def payload_for(
    kind: str, values: Mapping[str, str], catalog: NetBoxCatalog
) -> dict[str, object]:
    """Validate dialog values and build the API payload (references by ID)."""
    payload: dict[str, object] = {}
    for spec in SPECS[kind]:
        value = str(values.get(spec.name, "")).strip()
        if spec.kind == "slug" and not value:
            value = slugify(str(values.get("name", "")))
        if spec.required and not value:
            raise ObjectCreateError(f"{spec.label} is required.")
        if not value:
            continue
        if spec.kind == "slug" and value != slugify(value):
            raise ObjectCreateError(
                "The slug may contain lowercase letters, digits and hyphens only."
            )
        if spec.kind == "color":
            value = value.lstrip("#").lower()
            if len(value) != 6 or any(c not in "0123456789abcdef" for c in value):
                raise ObjectCreateError("The color must be six hex digits.")
        if spec.kind == "reference":
            found = catalog.find(spec.reference, value)
            if found is None:
                raise ObjectCreateError(
                    f"{spec.label} '{value}' is not in NetBox; choose or create it."
                )
            payload[spec.name] = int(found.id)
            continue
        payload[spec.name] = value
    return payload


def create_object(
    kind: str,
    values: Mapping[str, str],
    catalog: NetBoxCatalog,
    backend: IpamBackend,
    journal_path: Path | None = None,
) -> CreateResult:
    """Create one object right away (the dialog's confirmation is the approval)."""
    payload = payload_for(kind, values, catalog)
    path = KINDS[kind]
    label = f"{TITLES[kind].capitalize()} {payload['name']}"
    started = _now()
    result = _create(kind, path, payload, backend)
    if journal_path is not None:
        _journal(journal_path, kind, label, started, result)
    return result


def _create(kind: str, path: str, payload: dict, backend: IpamBackend) -> CreateResult:
    lookups = [{"name": payload["name"]}]
    if "slug" in payload:
        lookups.append({"slug": payload["slug"]})
    try:
        for lookup in lookups:
            existing = backend.find_ids(path, **lookup)
            if existing:
                item = _read(backend, path, existing[0], kind)
                return CreateResult(
                    item,
                    "existing",
                    f"NetBox already has this {TITLES[kind]}; it is selected.",
                    "verified" if item else "",
                )
    except NETWORK_ERRORS as error:
        return CreateResult(None, "failed", f"NetBox lookup failed: {error}")
    try:
        object_id = backend.create_object(path, payload)
        message = f"Created the {TITLES[kind]} in NetBox."
    except AMBIGUOUS_CREATE_ERRORS as error:
        try:
            found = backend.find_ids(path, name=payload["name"])
        except NETWORK_ERRORS as lookup_error:
            return CreateResult(
                None,
                "failed",
                f"Create was interrupted ({error}) and the lookup failed "
                f"({lookup_error}). Check NetBox before trying again.",
            )
        if len(found) != 1:
            return CreateResult(
                None,
                "failed",
                f"Create was interrupted ({error}); NetBox shows no single object.",
            )
        object_id = found[0]
        message = f"Create was interrupted ({error}), but NetBox has it."
    except NETWORK_ERRORS as error:
        return CreateResult(None, "failed", str(error))
    item = _read(backend, path, str(object_id), kind)
    if item is None:
        return CreateResult(
            CatalogObject(
                str(object_id), str(payload["name"]), str(payload.get("slug", ""))
            ),
            "success",
            message,
            "unverified",
        )
    verified = item.name == payload["name"] and item.slug == payload.get(
        "slug", item.slug
    )
    return CreateResult(
        item, "success", message, "verified" if verified else "mismatch"
    )


def _read(backend: IpamBackend, path: str, object_id: str, kind: str):
    try:
        row = backend.read_object(f"{path}{object_id}/")
    except NETWORK_ERRORS:
        return None
    if row is None:
        return None
    detail = ""
    for key in ("group", "manufacturer"):
        value = row.get(key)
        if isinstance(value, Mapping):
            detail = str(value.get("name") or value.get("display") or "")
    return CatalogObject(
        str(row.get("id", object_id)),
        str(row.get("name") or ""),
        str(row.get("slug") or ""),
        detail,
        str(row.get("color") or ""),
    )


def _journal(
    path: Path, kind: str, label: str, started: str, result: CreateResult
) -> None:
    status = "success" if result.status in ("success", "existing") else "failed"
    try:
        JournalStore(path).save(
            StoredRun(
                run_id=str(uuid.uuid4()),
                started_at=started,
                finished_at=_now(),
                dry_run=False,
                outcomes=(
                    StoredOutcome(
                        device_key=f"{kind}:{result.item.id if result.item else ''}",
                        label=label,
                        operation_type=OPERATION,
                        status=status,
                        message=result.message,
                        netbox_object_id=result.item.id if result.item else "",
                        verification=result.verification,
                    ),
                ),
            )
        )
    except JournalStoreError, sqlite3.Error, OSError:
        pass  # the object exists either way; history is best effort here


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
