"""NetBox objects the device type editor offers as drop-downs (read-only).

Manufacturers, platforms, owners, owner groups, tags and inventory item roles
(name, slug, ID and a few display details) plus the custom fields defined for
device types. Read with GET only, paginated, through ``ReadOnlySession``; one
failing list only empties that list and is reported in ``errors``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import requests

from unifi2netbox.config import NetBoxConfig
from unifi2netbox.inventory import InventoryError, _netbox_paginated_rows
from unifi2netbox.netbox import ReadOnlySession, RedirectError

# Kind -> API path. The kinds are also the keys of ``NetBoxCatalog.objects``.
KINDS = {
    "manufacturers": "/api/dcim/manufacturers/",
    "platforms": "/api/dcim/platforms/",
    "owners": "/api/users/owners/",
    "owner_groups": "/api/users/owner-groups/",
    "tags": "/api/extras/tags/",
    "inventory_item_roles": "/api/dcim/inventory-item-roles/",
}
CUSTOM_FIELDS = "/api/extras/custom-fields/"
CHOICE_SETS = "/api/extras/custom-field-choice-sets/"
DEVICE_TYPE_OBJECT = "dcim.devicetype"
PAGE_SIZE = 500
MAX_PAGES = 40


@dataclass(frozen=True)
class CatalogObject:
    id: str
    name: str
    slug: str = ""
    detail: str = ""  # owner group of an owner, manufacturer of a platform
    color: str = ""


@dataclass(frozen=True)
class CustomFieldDef:
    name: str
    label: str
    type: str
    required: bool = False
    description: str = ""
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class NetBoxCatalog:
    objects: Mapping[str, tuple[CatalogObject, ...]] = field(default_factory=dict)
    custom_fields: tuple[CustomFieldDef, ...] = ()
    errors: tuple[str, ...] = ()
    loaded: bool = False

    def items(self, kind: str) -> tuple[CatalogObject, ...]:
        return tuple(self.objects.get(kind, ()))

    def names(self, kind: str) -> tuple[str, ...]:
        key = "slug" if kind == "tags" else "name"
        return tuple(getattr(item, key) for item in self.items(kind))

    def find(self, kind: str, value: str) -> CatalogObject | None:
        wanted = value.strip().lower()
        return next(
            (
                item
                for item in self.items(kind)
                if item.name.lower() == wanted or (item.slug and item.slug == wanted)
            ),
            None,
        )

    def with_object(self, kind: str, item: CatalogObject) -> NetBoxCatalog:
        """A copy that includes a just-created object."""
        objects = dict(self.objects)
        current = [o for o in objects.get(kind, ()) if o.id != item.id]
        objects[kind] = tuple(sorted([*current, item], key=lambda o: o.name.lower()))
        return NetBoxCatalog(objects, self.custom_fields, self.errors, self.loaded)


def read_catalog(
    config: NetBoxConfig,
    session_factory: Callable[[NetBoxConfig], requests.Session] = ReadOnlySession,
) -> NetBoxCatalog:
    """Read all drop-down lists; network errors end up in ``errors``."""
    objects: dict[str, tuple[CatalogObject, ...]] = {}
    errors: list[str] = []
    custom_fields: tuple[CustomFieldDef, ...] = ()
    with session_factory(config) as session:

        def rows(path: str) -> list[dict]:
            return _netbox_paginated_rows(
                session,
                config,
                path,
                page_size=PAGE_SIZE,
                max_pages=MAX_PAGES,
                limit_error=f"NetBox returned too many objects for {path}.",
            )

        for kind, path in KINDS.items():
            try:
                objects[kind] = tuple(
                    sorted(
                        (_object(row) for row in rows(path)),
                        key=lambda o: o.name.lower(),
                    )
                )
            except (InventoryError, RedirectError, requests.RequestException) as error:
                objects[kind] = ()
                errors.append(f"{kind.replace('_', ' ')}: {_message(error)}")
        try:
            choice_sets = {str(row.get("id")): row for row in rows(CHOICE_SETS)}
            custom_fields = tuple(
                _custom_field(row, choice_sets)
                for row in rows(CUSTOM_FIELDS)
                if DEVICE_TYPE_OBJECT in (row.get("object_types") or ())
            )
        except (InventoryError, RedirectError, requests.RequestException) as error:
            errors.append(f"custom fields: {_message(error)}")
    return NetBoxCatalog(objects, custom_fields, tuple(errors), True)


def _object(row: Mapping) -> CatalogObject:
    detail = ""
    for key in ("group", "manufacturer"):
        value = row.get(key)
        if isinstance(value, Mapping):
            detail = str(value.get("name") or value.get("display") or "")
    return CatalogObject(
        id=str(row.get("id", "")),
        name=str(row.get("name") or ""),
        slug=str(row.get("slug") or ""),
        detail=detail,
        color=str(row.get("color") or ""),
    )


def _custom_field(row: Mapping, choice_sets: Mapping[str, Mapping]) -> CustomFieldDef:
    kind = row.get("type")
    if isinstance(kind, Mapping):
        kind = kind.get("value")
    choices: tuple[str, ...] = ()
    choice_set = row.get("choice_set")
    if isinstance(choice_set, Mapping):
        found = choice_sets.get(str(choice_set.get("id")), {})
        choices = tuple(
            str(item[0])
            for item in found.get("extra_choices") or ()
            if isinstance(item, (list, tuple)) and item
        )
    return CustomFieldDef(
        name=str(row.get("name") or ""),
        label=str(row.get("label") or row.get("name") or ""),
        type=str(kind or "text"),
        required=row.get("required") is True,
        description=str(row.get("description") or ""),
        choices=choices,
    )


def _message(error: Exception) -> str:
    if isinstance(error, RedirectError):
        return "NetBox redirected the request."
    return str(error) or error.__class__.__name__


def reference_issues(doc: Mapping, catalog: NetBoxCatalog):
    """Warnings for references to NetBox objects the catalog does not know."""
    from unifi2netbox.devicetypes import Issue

    if not catalog.loaded:
        return ()
    issues = []

    def check(kind: str, value, where: str, label: str) -> None:
        if value and catalog.find(kind, str(value)) is None:
            issues.append(
                Issue("warning", where, f"{label} '{value}' is not in NetBox.")
            )

    check("manufacturers", doc.get("manufacturer"), "manufacturer", "Manufacturer")
    check("platforms", doc.get("default_platform"), "default_platform", "Platform")
    check("owners", doc.get("owner"), "owner", "Owner")
    for tag in doc.get("tags") or ():
        check("tags", tag, "tags", "Tag")
    for index, item in enumerate(doc.get("inventory-items") or ()):
        if isinstance(item, Mapping):
            where = f"inventory-items/{index}"
            check("inventory_item_roles", item.get("role"), where, "Role")
            check("manufacturers", item.get("manufacturer"), where, "Manufacturer")
    known = {definition.name for definition in catalog.custom_fields}
    custom = doc.get("custom_fields")
    if isinstance(custom, Mapping):
        for name in custom:
            if name not in known:
                issues.append(
                    Issue(
                        "warning",
                        "custom_fields",
                        f"Custom field '{name}' is not defined for device types "
                        "in NetBox.",
                    )
                )
    return tuple(issues)
