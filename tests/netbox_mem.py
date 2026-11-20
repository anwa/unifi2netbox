"""An in-memory NetBox: API source for backups and target for restores.

It answers the GET and OPTIONS requests the backup makes and offers the
backend methods the restore uses, stores objects with plain IDs and returns
them like the API (nested references with ``url``, choices as value/label).
Creating a device creates its interfaces from the device type's interface
templates, like NetBox does.
"""

from __future__ import annotations

import copy
from urllib.parse import parse_qs, urlparse

import requests

from unifi2netbox.write_execute import WriteExecutionError

B = "https://mem.example.com"
R = "ref"
SCHEMA = {
    "extras/tags": {"name": ("string", True), "slug": ("slug", True)},
    "dcim/manufacturers": {"name": ("string", True), "slug": ("slug", True)},
    "dcim/sites": {
        "name": ("string", True),
        "slug": ("slug", True),
        "status": ("choice", False),
        "tags": ("tags", False),
    },
    "dcim/device-types": {
        "manufacturer": (R, True, "dcim/manufacturers"),
        "model": ("string", True),
        "slug": ("slug", True),
        "front_image": ("image", False),
    },
    "dcim/interface-templates": {
        "device_type": (R, True, "dcim/device-types"),
        "name": ("string", True),
        "type": ("choice", True),
    },
    "dcim/devices": {
        "name": ("string", False),
        "site": (R, True, "dcim/sites"),
        "device_type": (R, True, "dcim/device-types"),
        "primary_ip4": (R, False, "ipam/ip-addresses"),
    },
    "dcim/interfaces": {
        "device": (R, True, "dcim/devices"),
        "name": ("string", True),
        "type": ("choice", True),
        "parent": (R, False, "dcim/interfaces"),
    },
    "ipam/ip-addresses": {
        "address": ("string", True),
        "assigned_object_type": ("string", False),
        "assigned_object_id": ("generic", False, "assigned_object"),
    },
    "dcim/cables": {
        "a_terminations": ("terminations", True),
        "b_terminations": ("terminations", True),
        "status": ("choice", False),
    },
    "extras/image-attachments": {
        "object_type": ("string", True),
        "object_id": ("generic", True, None),
        "name": ("string", False),
        "image": ("image", True),
    },
}
TYPES = {
    "dcim.interface": "dcim/interfaces",
    "dcim.device": "dcim/devices",
}
UNIQUE = {"slug", "address"}


class MemNetBox:
    def __init__(self):
        self.data: dict[str, dict[int, dict]] = {e: {} for e in SCHEMA}
        self.media: dict[str, bytes] = {}
        self.next_id = 100
        self.writes: list[tuple[str, str]] = []
        self.fail_next_create: str | None = None

    # -- helpers ---------------------------------------------------------------

    def add(self, endpoint, **values) -> int:
        return self._store(endpoint, values)

    def _store(self, endpoint, values) -> int:
        spec = SCHEMA[endpoint]
        for name, (kind, required, *rest) in spec.items():
            value = values.get(name)
            if required and value in (None, "", []):
                raise WriteExecutionError(f"{endpoint}: {name} is required.")
            if kind == R and value is not None and value not in self.data[rest[0]]:
                raise WriteExecutionError(f"{endpoint}: unknown {name} {value}.")
            if (
                name in UNIQUE
                and value
                and any(row.get(name) == value for row in self.data[endpoint].values())
            ):
                raise WriteExecutionError(f"{endpoint}: duplicate {name} {value}.")
        object_id = self.next_id
        self.next_id += 1
        self.data[endpoint][object_id] = {k: v for k, v in values.items() if k in spec}
        if endpoint == "dcim/devices":  # components from templates, like NetBox
            for template in self.data["dcim/interface-templates"].values():
                if template["device_type"] == values["device_type"]:
                    self._store(
                        "dcim/interfaces",
                        {
                            "device": object_id,
                            "name": template["name"],
                            "type": template["type"],
                        },
                    )
        return object_id

    def api_row(self, endpoint, object_id) -> dict:
        row = {"id": object_id, "url": f"{B}/api/{endpoint}/{object_id}/"}
        stored = self.data[endpoint][object_id]
        for name, (kind, _required, *rest) in SCHEMA[endpoint].items():
            value = stored.get(name)
            if kind == R:
                row[name] = self._nested(rest[0], value) if value else None
            elif kind == "tags":
                row[name] = [self._nested("extras/tags", v) for v in value or ()]
            elif kind == "choice":
                row[name] = (
                    {"value": value, "label": str(value).title()} if value else None
                )
            elif kind == "terminations":
                row[name] = [
                    {
                        **t,
                        "object": self._nested(TYPES[t["object_type"]], t["object_id"]),
                    }
                    for t in value or ()
                ]
            elif kind == "generic":
                row[name] = value
                if rest[0]:
                    kind_name = stored.get(f"{rest[0]}_type")
                    row[rest[0]] = (
                        self._nested(TYPES[kind_name], value) if value else None
                    )
            elif kind == "image":
                row[name] = f"{B}{value}" if value else None
            else:
                row[name] = value
        return row

    def _nested(self, endpoint, object_id):
        return {"id": object_id, "url": f"{B}/api/{endpoint}/{object_id}/"}

    def canon(self) -> dict:
        """Endpoint -> sorted rows with references replaced by labels."""

        def label(endpoint, object_id):
            row = self.data[endpoint].get(object_id, {})
            parent = row.get("device") or row.get("device_type")
            name = row.get("name") or row.get("slug") or row.get("address")
            return f"{endpoint}:{name}@{parent and label_parent(endpoint, parent)}"

        def label_parent(endpoint, parent):
            for target in ("dcim/devices", "dcim/device-types"):
                if parent in self.data[target]:
                    row = self.data[target][parent]
                    return row.get("name") or row.get("slug")
            return parent

        result = {}
        for endpoint, rows in self.data.items():
            items = []
            for row in rows.values():
                item = {}
                for name, (kind, _req, *rest) in SCHEMA[endpoint].items():
                    value = row.get(name)
                    if kind == R and value:
                        value = label(rest[0], value)
                    elif kind == "tags":
                        value = sorted(label("extras/tags", v) for v in value or ())
                    elif kind == "terminations":
                        value = sorted(
                            label(TYPES[t["object_type"]], t["object_id"])
                            for t in value or ()
                        )
                    elif kind == "generic" and value:
                        kind_name = row.get(f"{rest[0] or 'object'}_type")
                        value = label(TYPES[kind_name], value)
                    elif kind == "image" and value:
                        value = self.media.get(value)
                    item[name] = value
                items.append(repr(sorted(item.items(), key=str)))
            result[endpoint] = sorted(items)
        return result

    # -- session side (backup) ---------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None):
        parsed = urlparse(url)
        path = parsed.path
        if path in self.media:
            return _Response(200, content=self.media[path])
        if path == "/api/":
            return _Response(
                200, {a: "" for a in sorted({e.split("/")[0] for e in SCHEMA})}
            )
        if path == "/api/status/":
            return _Response(200, {"netbox-version": "4.7.3"})
        if path == "/api/core/object-types/":
            rows = [
                {
                    "app_label": k.split(".")[0],
                    "model": k.split(".")[1],
                    "rest_api_endpoint": f"/api/{v}/",
                }
                for k, v in TYPES.items()
            ]
            return _Response(200, {"count": len(rows), "results": rows})
        parts = path.strip("/").split("/")
        if len(parts) == 2:  # app root
            app = parts[1]
            return _Response(
                200, {e.split("/")[1]: "" for e in SCHEMA if e.startswith(app + "/")}
            )
        endpoint = "/".join(parts[1:3])
        rows = self.list_objects(f"/api/{endpoint}/")
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["1000"])[0])
        offset = int(query.get("offset", ["0"])[0])
        return _Response(
            200, {"count": len(rows), "results": rows[offset : offset + limit]}
        )

    def options(self, url, headers=None):
        endpoint = "/".join(urlparse(url).path.strip("/").split("/")[1:3])
        post = {}
        for name, (kind, required, *_rest) in SCHEMA[endpoint].items():
            api_type = {
                R: "nested object",
                "image": "image upload",
                "generic": "integer",
                "tags": "field",
                "terminations": "field",
            }.get(kind, kind)
            post[name] = {"type": api_type, "required": required, "read_only": False}
        post["display"] = {"type": "string", "read_only": True}
        return _Response(200, {"actions": {"POST": post}})

    # -- backend side (restore) ------------------------------------------------------

    def list_objects(self, path, **filters):
        endpoint = path.strip("/").removeprefix("api/")
        return [self.api_row(endpoint, i) for i in sorted(self.data[endpoint])]

    def count(self, path):
        return len(self.data[path.strip("/").removeprefix("api/")])

    def bulk_create(self, path, payloads):
        endpoint = path.strip("/").removeprefix("api/")
        ids = []
        for payload in payloads:
            ids.append(str(self._store(endpoint, copy.deepcopy(payload))))
            self.writes.append(("POST", endpoint))
        if self.fail_next_create == endpoint:
            self.fail_next_create = None
            raise requests.exceptions.Timeout("timed out")
        return ids

    def bulk_update(self, path, payloads):
        endpoint = path.strip("/").removeprefix("api/")
        for payload in payloads:
            row = self.data[endpoint][int(payload["id"])]
            row.update({k: v for k, v in payload.items() if k != "id"})
            self.writes.append(("PATCH", endpoint))

    def bulk_delete(self, path, ids):
        endpoint = path.strip("/").removeprefix("api/")
        for object_id in ids:
            self.data[endpoint].pop(int(object_id), None)
            self.writes.append(("DELETE", endpoint))
        if endpoint == "dcim/devices":  # cascade, like NetBox
            for key, row in list(self.data["dcim/interfaces"].items()):
                if row["device"] not in self.data["dcim/devices"]:
                    self.data["dcim/interfaces"].pop(key)

    def upload_files(self, path, files):
        endpoint, object_id = path.strip("/").removeprefix("api/").rsplit("/", 1)
        for name, file in files.items():
            media = f"/media/{endpoint}/{object_id}/{file.name}"
            self.media[media] = file.read_bytes()
            self.data[endpoint][int(object_id)][name] = media
            self.writes.append(("UPLOAD", endpoint))

    def create_with_files(self, path, data, files):
        endpoint = path.strip("/").removeprefix("api/")
        values = dict(data)
        for name, file in files.items():
            media = f"/media/{endpoint}/{file.name}"
            self.media[media] = file.read_bytes()
            values[name] = media
        self.writes.append(("POST", endpoint))
        return str(self._store(endpoint, values))


class _Response:
    def __init__(self, status, payload=None, content=b""):
        self.status_code = status
        self.payload = payload
        self.content = content

    def json(self):
        return self.payload


def sample() -> MemNetBox:
    """A small instance with every kind of reference."""
    nb = MemNetBox()
    tag = nb.add("extras/tags", name="Core", slug="core")
    maker = nb.add("dcim/manufacturers", name="Ubiquiti", slug="ubiquiti")
    site = nb.add("dcim/sites", name="Lab", slug="lab", status="active", tags=[tag])
    nb.media["/media/devicetype-images/box.png"] = b"PNG"
    box = nb.add(
        "dcim/device-types",
        manufacturer=maker,
        model="Box",
        slug="ubiquiti-box",
        front_image="/media/devicetype-images/box.png",
    )
    nb.add("dcim/interface-templates", device_type=box, name="eth0", type="1000base-t")
    nb.add("dcim/interface-templates", device_type=box, name="eth1", type="1000base-t")
    sw1 = nb.add("dcim/devices", name="sw1", site=site, device_type=box)
    sw2 = nb.add("dcim/devices", name="sw2", site=site, device_type=box)
    eth0 = next(
        i
        for i, r in nb.data["dcim/interfaces"].items()
        if r["device"] == sw1 and r["name"] == "eth0"
    )
    nb.add("dcim/interfaces", device=sw1, name="eth0.10", type="virtual", parent=eth0)
    peer = next(
        i
        for i, r in nb.data["dcim/interfaces"].items()
        if r["device"] == sw2 and r["name"] == "eth0"
    )
    ip = nb.add(
        "ipam/ip-addresses",
        address="10.0.0.1/24",
        assigned_object_type="dcim.interface",
        assigned_object_id=eth0,
    )
    nb.data["dcim/devices"][sw1]["primary_ip4"] = ip
    nb.add(
        "dcim/cables",
        status="connected",
        a_terminations=[{"object_type": "dcim.interface", "object_id": eth0}],
        b_terminations=[{"object_type": "dcim.interface", "object_id": peer}],
    )
    nb.media["/media/image-attachments/photo.jpg"] = b"JPG"
    nb.add(
        "extras/image-attachments",
        object_type="dcim.device",
        object_id=sw1,
        name="photo",
        image="/media/image-attachments/photo.jpg",
    )
    nb.writes.clear()
    return nb
