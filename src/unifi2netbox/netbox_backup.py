"""Back up a whole NetBox instance into one file (M15 slice 1, read-only).

The backup discovers the API apps and their endpoints, reads the writable
fields of each endpoint with OPTIONS, and reads every object with paginated
GET. Objects keep their ID and their writable fields only; references to
other objects become ``{"$ref": ["app/endpoint", id]}`` (taken from the
nested object's ``url``), generic relations (``assigned_object_type`` plus
``assigned_object_id``, cable terminations, ...) keep their type and point
to the referenced object the same way. Choice fields keep their value.

Never backed up: users, groups, tokens and permissions, the change log, jobs
and other ``core`` data, plugin endpoints, user-bound objects (bookmarks,
notifications, subscriptions, dashboards, table configs, saved filters),
journal entries, and secrets (fields like a webhook secret or a VPN
pre-shared key are left out and listed in ``omitted``). Images (device and
module type images, image attachments) are embedded base64 when asked.

The file is JSON (default) or YAML, chosen by the file extension, written
atomically, and marked incomplete when an endpoint could not be read.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from ruamel.yaml import YAML

from unifi2netbox.config import NetBoxConfig
from unifi2netbox.inventory import InventoryError, _netbox_json, _netbox_paginated_rows
from unifi2netbox.netbox import ReadOnlySession, RedirectError

FORMAT = "unifi2netbox-backup"
VERSION = 1
PAGE_SIZE = 1000
MAX_PAGES = 1000
INCLUDED_APPS = (
    "circuits",
    "dcim",
    "extras",
    "ipam",
    "tenancy",
    "virtualization",
    "vpn",
    "wireless",
    "users",
)
# Only these endpoints of the users app (owners are data, users are not).
USERS_ENDPOINTS = ("owner-groups", "owners")
EXCLUDED = {
    "dcim/cable-terminations",  # part of the cables
    "dcim/connected-device",
    "extras/scripts",
    "extras/reports",
    "extras/journal-entries",
    "extras/bookmarks",
    "extras/notifications",
    "extras/notification-groups",
    "extras/subscriptions",
    "extras/dashboard",
    "extras/table-configs",
    "extras/saved-filters",
    "extras/object-changes",
    "extras/content-types",
    "extras/object-types",
}
# Field names that hold secrets; left out of every backup.
SECRET = re.compile(
    r"(^|_)(secret|password|token|preshared_key|private_key|api_key|"
    r"additional_headers|psk)(_|$)"
)
# Read-derived fields that must not be written back.
DROP = {
    ("dcim/rear-ports", "front_ports"),
    ("dcim/rear-port-templates", "front_ports"),
}
# References inside list children that are plain IDs (no nested url).
CHILD_REFS = {
    ("dcim/front-ports", "rear_ports", "rear_port"): "dcim/rear-ports",
    (
        "dcim/front-port-templates",
        "rear_ports",
        "rear_port",
    ): "dcim/rear-port-templates",
}
FILE_TYPES = ("image upload", "file upload")
_API_PATH = re.compile(r"/api/([a-z0-9-]+)/([a-z0-9-]+(?:/[a-z0-9-]+)?)/(\d+)/?$")


class BackupError(RuntimeError):
    pass


class BackupCancelled(BackupError):
    pass


@dataclass
class Progress:
    done: int
    total: int
    endpoint: str
    objects: int


@dataclass
class Backup:
    """The backup document; ``data`` is what is written to the file."""

    data: dict = field(default_factory=dict)

    @property
    def endpoints(self) -> dict[str, list[dict]]:
        return self.data.get("objects", {})

    @property
    def complete(self) -> bool:
        return not self.data.get("errors")

    def counts(self) -> dict[str, int]:
        return {name: len(rows) for name, rows in self.endpoints.items() if rows}

    def total(self) -> int:
        return sum(self.counts().values())


def create_backup(
    config: NetBoxConfig,
    *,
    include_files: bool = True,
    progress: Callable[[Progress], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    session_factory: Callable[[NetBoxConfig], requests.Session] = ReadOnlySession,
) -> Backup:
    """Read every included endpoint of ``config``'s NetBox (GET and OPTIONS)."""
    errors: list[str] = []
    skipped: list[str] = []
    omitted: list[str] = []
    objects: dict[str, list[dict]] = {}
    fields_meta: dict[str, dict] = {}
    files: list[dict] = []
    with session_factory(config) as session:
        auth = {"Authorization": f"Token {config.token}", "Accept": "application/json"}
        try:
            status = _netbox_json(session, config, "/api/status/")
        except (InventoryError, RedirectError, requests.RequestException) as error:
            raise BackupError(f"NetBox is not reachable: {_text(error)}") from error
        endpoints = _discover(session, config, skipped)
        object_types = _object_types(session, config, endpoints)
        total = len(endpoints)
        for index, endpoint in enumerate(endpoints):
            if cancelled is not None and cancelled():
                raise BackupCancelled("The backup was cancelled.")
            try:
                meta = _options(session, config, auth, endpoint)
            except (InventoryError, RedirectError, requests.RequestException) as error:
                errors.append(f"{endpoint}: {_text(error)}")
                continue
            if meta is None:
                skipped.append(f"{endpoint} (read-only endpoint)")
                continue
            fields_meta[endpoint] = meta
            try:
                rows = _netbox_paginated_rows(
                    session,
                    config,
                    f"/api/{endpoint}/",
                    page_size=PAGE_SIZE,
                    max_pages=MAX_PAGES,
                    limit_error=f"Too many objects in {endpoint}.",
                )
            except (InventoryError, RedirectError, requests.RequestException) as error:
                errors.append(f"{endpoint}: {_text(error)}")
                continue
            converted = []
            for row in rows:
                item, secrets, wanted = serialize_row(endpoint, row, meta, object_types)
                converted.append(item)
                for name in secrets:
                    note = f"{endpoint}.{name}"
                    if note not in omitted:
                        omitted.append(note)
                if include_files:
                    for name, url in wanted:
                        try:
                            files.append(
                                _download(
                                    session, config, auth, endpoint, row, name, url
                                )
                            )
                        except (requests.RequestException, BackupError) as error:
                            errors.append(
                                f"{endpoint} {row.get('id')} {name}: {_text(error)}"
                            )
            objects[endpoint] = converted
            if progress is not None:
                progress(Progress(index + 1, total, endpoint, len(converted)))
    data = {
        "format": FORMAT,
        "version": VERSION,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "netbox_version": str(status.get("netbox-version") or ""),
        "source": urlparse(config.url).netloc,
        "complete": not errors,
        "errors": errors,
        "skipped": skipped,
        "omitted": omitted,
        "object_types": object_types,
        "fields": fields_meta,
        "objects": objects,
        "files": files,
    }
    return Backup(data)


# -- discovery and metadata --------------------------------------------------------


def _discover(session, config, skipped: list[str]) -> list[str]:
    root = _netbox_json(session, config, "/api/")
    endpoints = []
    for app in root:
        if app not in INCLUDED_APPS:
            skipped.append(f"{app} (not backed up)")
            continue
        names = _netbox_json(session, config, f"/api/{app}/")
        for name in names:
            endpoint = f"{app}/{name}"
            if app == "users" and name not in USERS_ENDPOINTS:
                continue
            if endpoint in EXCLUDED or "/" in name:
                continue  # sub-actions such as extras/scripts/upload
            endpoints.append(endpoint)
    return endpoints


def _object_types(session, config, endpoints: Iterable[str]) -> dict[str, str]:
    """Object type (``dcim.interface``) -> endpoint (``dcim/interfaces``)."""
    result: dict[str, str] = {}
    try:
        rows = _netbox_paginated_rows(
            session,
            config,
            "/api/core/object-types/",
            page_size=PAGE_SIZE,
            max_pages=10,
            limit_error="Too many object types.",
        )
    except InventoryError, RedirectError, requests.RequestException:
        rows = []
    known = set(endpoints)
    for row in rows:
        label = f"{row.get('app_label')}.{row.get('model')}"
        path = str(row.get("rest_api_endpoint") or "")
        match = re.fullmatch(r"/api/([a-z0-9-]+/[a-z0-9-]+)/", path)
        if match:
            result[label] = match.group(1)
    for endpoint in known:  # fallback: dcim/ip-addresses <- ipam.ipaddress
        app, name = endpoint.split("/", 1)
        for model in _models_for(name):
            result.setdefault(f"{app}.{model}", endpoint)
    return result


def _models_for(name: str) -> tuple[str, ...]:
    flat = name.replace("-", "")
    singular = []
    if flat.endswith("ies"):
        singular.append(flat[:-3] + "y")
    if flat.endswith("es"):
        singular.append(flat[:-2])
    if flat.endswith("s"):
        singular.append(flat[:-1])
    return tuple(singular) or (flat,)


def _options(session, config, auth, endpoint: str) -> dict | None:
    """Writable fields of an endpoint, or None when it cannot be written."""
    response = session.options(
        f"{config.url.rstrip('/')}/api/{endpoint}/", headers=auth
    )
    if response.status_code != 200:
        raise InventoryError(f"OPTIONS returned HTTP {response.status_code}.")
    post = (response.json().get("actions") or {}).get("POST")
    if not post:
        return None
    meta = {}
    for name, spec in post.items():
        if spec.get("read_only"):
            continue
        meta[name] = {
            "type": str(spec.get("type") or ""),
            "required": bool(spec.get("required")),
        }
    return meta


# -- rows --------------------------------------------------------------------------


def serialize_row(endpoint: str, row: Mapping, meta: Mapping, object_types=None):
    """(item, omitted secret fields, [(file field, url)]) for one API row."""
    object_types = object_types or {}
    item: dict = {"id": row.get("id")}
    secrets, wanted = [], []
    for name, spec in meta.items():
        if name not in row or (endpoint, name) in DROP:
            continue
        if SECRET.search(name):
            secrets.append(name)
            continue
        value = row[name]
        if spec.get("type") in FILE_TYPES:
            if value:
                wanted.append((name, str(value)))
            continue
        item[name] = _convert(value)
        if name.endswith("_id") and f"{name[:-3]}_type" in row:
            ref = _generic_ref(row, name[:-3], object_types)
            if ref is not None:
                item[name] = ref
        if isinstance(item[name], list):
            for child in item[name]:
                if isinstance(child, dict):
                    _child_refs(endpoint, name, child)
    if (
        endpoint == "extras/image-attachments"
        and row.get("image")
        and not any(name == "image" for name, _url in wanted)
    ):
        wanted.append(("image", str(row["image"])))
    return item, secrets, wanted


def _convert(value):
    if isinstance(value, Mapping):
        url = value.get("url")
        if isinstance(url, str) and "id" in value:
            ref = _ref_from_url(url, value.get("id"))
            if ref is not None:
                return ref
        if set(value) >= {"value", "label"} and len(value) <= 3:
            return value.get("value")
        converted = {str(k): _convert(v) for k, v in value.items()}
        for key in list(converted):  # {"object": ref, "object_id": 5}
            if f"{key}_id" in converted and _is_ref(converted[key]):
                converted[f"{key}_id"] = converted.pop(key)
        return converted
    if isinstance(value, list):
        return [_convert(v) for v in value]
    return value


def _child_refs(endpoint: str, field_name: str, child: dict) -> None:
    for (ep, name, key), target in CHILD_REFS.items():
        if ep == endpoint and name == field_name and isinstance(child.get(key), int):
            child[key] = {"$ref": [target, child[key]]}


def _generic_ref(row: Mapping, prefix: str, object_types: Mapping):
    nested = row.get(prefix)
    if isinstance(nested, Mapping) and isinstance(nested.get("url"), str):
        ref = _ref_from_url(nested["url"], nested.get("id"))
        if ref is not None:
            return ref
    kind = row.get(f"{prefix}_type")
    target = object_types.get(str(kind)) if kind else None
    object_id = row.get(f"{prefix}_id")
    if target and isinstance(object_id, int):
        return {"$ref": [target, object_id]}
    return None


def _ref_from_url(url: str, object_id) -> dict | None:
    match = _API_PATH.search(urlparse(url).path)
    if not match:
        return None
    return {"$ref": [f"{match.group(1)}/{match.group(2)}", int(match.group(3))]}


def _is_ref(value) -> bool:
    return isinstance(value, dict) and set(value) == {"$ref"}


def _download(session, config, auth, endpoint, row, name, url) -> dict:
    absolute = url if url.startswith("http") else f"{config.url.rstrip('/')}{url}"
    response = session.get(absolute, headers=auth)
    if response.status_code != 200:
        raise BackupError(f"download returned HTTP {response.status_code}")
    return {
        "endpoint": endpoint,
        "id": row.get("id"),
        "field": name,
        "name": Path(urlparse(absolute).path).name,
        "data": base64.b64encode(response.content).decode("ascii"),
    }


def _text(error: Exception) -> str:
    if isinstance(error, RedirectError):
        return "NetBox redirected the request."
    return str(error) or error.__class__.__name__


# -- files -------------------------------------------------------------------------


def write_backup(backup: Backup, path: Path) -> None:
    """Write atomically; ``.yaml``/``.yml`` as YAML, everything else as JSON."""
    path = Path(path)
    if path.suffix.lower() in (".yaml", ".yml"):
        stream = io.StringIO()
        yaml = YAML(typ="safe", pure=True)
        yaml.default_flow_style = False
        yaml.dump(backup.data, stream)
        text = stream.getvalue()
    else:
        text = json.dumps(backup.data, ensure_ascii=False, indent=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def read_backup(path: Path) -> Backup:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    try:
        if path.suffix.lower() in (".yaml", ".yml"):
            data = YAML(typ="safe", pure=True).load(text)
        else:
            data = json.loads(text)
    except Exception as error:  # noqa: BLE001 - shown to the user
        raise BackupError(f"The file is not a readable backup: {error}") from error
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise BackupError("The file is not a unifi2netbox backup.")
    if data.get("version") != VERSION:
        raise BackupError(f"Unsupported backup version {data.get('version')}.")
    return Backup(data)


def default_name(config: NetBoxConfig, when: datetime | None = None) -> str:
    host = re.sub(r"[^A-Za-z0-9.-]+", "-", urlparse(config.url).hostname or "netbox")
    day = (when or datetime.now()).strftime("%Y-%m-%d")
    return f"netbox-backup-{host}-{day}.json"
