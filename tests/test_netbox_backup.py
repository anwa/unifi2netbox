"""NetBox backup (M15 slice 1)."""

import base64
import json
from urllib.parse import parse_qs, urlparse

import pytest

from unifi2netbox.config import NetBoxConfig
from unifi2netbox.netbox_backup import (
    BackupCancelled,
    BackupError,
    create_backup,
    default_name,
    read_backup,
    write_backup,
)

CONFIG = NetBoxConfig(url="https://netbox.example.com", token="secret-token")
B = "https://netbox.example.com"


def nested(endpoint, object_id, **extra):
    return {"id": object_id, "url": f"{B}/api/{endpoint}/{object_id}/", **extra}


def choice(value):
    return {"value": value, "label": value.title()}


def field(kind="string", required=False, read_only=False):
    return {"type": kind, "required": required, "read_only": read_only}


ROOTS = {
    "/api/": {
        a: f"{B}/api/{a}/"
        for a in ("core", "dcim", "extras", "ipam", "users", "plugins", "wireless")
    },
    "/api/dcim/": {
        n: ""
        for n in (
            "manufacturers",
            "sites",
            "devices",
            "interfaces",
            "cable-terminations",
            "cables",
            "device-types",
            "front-ports",
            "rear-ports",
        )
    },
    "/api/extras/": {
        n: ""
        for n in (
            "tags",
            "webhooks",
            "journal-entries",
            "image-attachments",
            "scripts/upload",
        )
    },
    "/api/wireless/": {"wireless-lans": ""},
    "/api/ipam/": {"ip-addresses": ""},
    "/api/users/": {n: "" for n in ("users", "tokens", "owners", "owner-groups")},
    "/api/status/": {"netbox-version": "4.7.3"},
}
OPTIONS = {
    "dcim/manufacturers": {"name": field(), "slug": field("slug")},
    "dcim/sites": {
        "name": field(required=True),
        "slug": field("slug"),
        "status": field("choice"),
        "tags": field("field"),
    },
    "dcim/device-types": {
        "manufacturer": field("nested object", True),
        "model": field(),
        "slug": field("slug"),
        "front_image": field("image upload"),
    },
    "dcim/devices": {
        "name": field(),
        "site": field("nested object", True),
        "device_type": field("nested object", True),
        "primary_ip4": field("nested object"),
        "display": field(read_only=True),
    },
    "dcim/interfaces": {
        "device": field("nested object", True),
        "name": field(),
        "type": field("choice"),
    },
    "dcim/cables": {
        "a_terminations": field("field"),
        "b_terminations": field("field"),
        "status": field("choice"),
    },
    "dcim/front-ports": {
        "device": field("nested object", True),
        "name": field(),
        "rear_ports": field("field"),
    },
    "dcim/rear-ports": {
        "device": field("nested object", True),
        "name": field(),
        "front_ports": field("field"),
    },
    "extras/tags": {"name": field(), "slug": field("slug")},
    "extras/webhooks": {
        "name": field(),
        "payload_url": field(),
        "secret": field(),
        "additional_headers": field(),
    },
    "extras/image-attachments": {
        "object_type": field(),
        "object_id": field("integer"),
        "name": field(),
        "image": field("image upload"),
    },
    "ipam/ip-addresses": {
        "address": field(),
        "assigned_object_type": field(),
        "assigned_object_id": field("integer"),
    },
    "users/owners": {"name": field(), "group": field("nested object", True)},
    "users/owner-groups": {"name": field()},
    "wireless/wireless-lans": {
        "ssid": field(),
        "auth_type": field("choice"),
        "auth_cipher": field("choice"),
        "auth_psk": field(),
    },
}
ROWS = {
    "core/object-types": [
        {
            "app_label": "dcim",
            "model": "interface",
            "rest_api_endpoint": "/api/dcim/interfaces/",
        },
        {
            "app_label": "dcim",
            "model": "device",
            "rest_api_endpoint": "/api/dcim/devices/",
        },
    ],
    "dcim/manufacturers": [{"id": 1, "name": "Ubiquiti", "slug": "ubiquiti"}],
    "dcim/sites": [
        {
            "id": 2,
            "name": "Lab",
            "slug": "lab",
            "status": choice("active"),
            "tags": [nested("extras/tags", 9, name="Core", slug="core")],
        }
    ],
    "dcim/device-types": [
        {
            "id": 3,
            "manufacturer": nested("dcim/manufacturers", 1),
            "model": "Box",
            "slug": "ubiquiti-box",
            "front_image": "/media/devicetype-images/box.png",
        }
    ],
    "dcim/devices": [
        {
            "id": 4,
            "name": "sw1",
            "site": nested("dcim/sites", 2),
            "device_type": nested("dcim/device-types", 3),
            "primary_ip4": nested("ipam/ip-addresses", 7),
            "display": "sw1",
        }
    ],
    "dcim/interfaces": [
        {
            "id": 5,
            "device": nested("dcim/devices", 4),
            "name": "eth0",
            "type": choice("1000base-t"),
        },
        {
            "id": 6,
            "device": nested("dcim/devices", 4),
            "name": "eth1",
            "type": choice("1000base-t"),
        },
    ],
    "dcim/cables": [
        {
            "id": 8,
            "status": choice("connected"),
            "a_terminations": [
                {
                    "object_type": "dcim.interface",
                    "object_id": 5,
                    "object": nested("dcim/interfaces", 5),
                }
            ],
            "b_terminations": [
                {
                    "object_type": "dcim.interface",
                    "object_id": 6,
                    "object": nested("dcim/interfaces", 6),
                }
            ],
        }
    ],
    "dcim/rear-ports": [
        {
            "id": 11,
            "device": nested("dcim/devices", 4),
            "name": "R1",
            "front_ports": [{"position": 1, "front_port": 12}],
        }
    ],
    "dcim/front-ports": [
        {
            "id": 12,
            "device": nested("dcim/devices", 4),
            "name": "F1",
            "rear_ports": [{"position": 1, "rear_port": 11, "rear_port_position": 1}],
        }
    ],
    "extras/tags": [{"id": 9, "name": "Core", "slug": "core"}],
    "extras/webhooks": [
        {
            "id": 10,
            "name": "hook",
            "payload_url": "https://x",
            "secret": "s3cret",
            "additional_headers": "X-Auth: 1",
        }
    ],
    "extras/image-attachments": [
        {
            "id": 13,
            "object_type": "dcim.device",
            "object_id": 4,
            "name": "photo",
            "image": f"{B}/media/image-attachments/photo.jpg",
        }
    ],
    "ipam/ip-addresses": [
        {
            "id": 7,
            "address": "10.0.0.2/24",
            "assigned_object_type": "dcim.interface",
            "assigned_object_id": 5,
            "assigned_object": nested("dcim/interfaces", 5),
        }
    ],
    "users/owner-groups": [{"id": 14, "name": "IT"}],
    "users/owners": [
        {"id": 15, "name": "Ops", "group": nested("users/owner-groups", 14)}
    ],
    "users/users": [{"id": 1, "username": "admin"}],
    "wireless/wireless-lans": [
        {
            "id": 16,
            "ssid": "Office",
            "auth_type": choice("wpa-personal"),
            "auth_cipher": choice("aes"),
            "auth_psk": "wifi-password",
        }
    ],
}
MEDIA = {
    "/media/devicetype-images/box.png": b"PNG",
    "/media/image-attachments/photo.jpg": b"JPG",
}


class Response:
    def __init__(self, status, payload=None, content=b""):
        self.status_code = status
        self.payload = payload
        self.content = content

    def json(self):
        return self.payload


class FakeApi:
    def __init__(self, fail=(), page=1000):
        self.fail = set(fail)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None):
        parsed = urlparse(url)
        path = parsed.path
        self.calls.append(("GET", path))
        if path in MEDIA:
            return Response(200, content=MEDIA[path])
        if path in ROOTS:
            return Response(200, ROOTS[path])
        key = path.strip("/").removeprefix("api/")
        if key in self.fail:
            return Response(500, {})
        rows = ROWS.get(key, [])
        query = parse_qs(parsed.query)
        limit = int(query.get("limit", ["1000"])[0])
        offset = int(query.get("offset", ["0"])[0])
        return Response(
            200, {"count": len(rows), "results": rows[offset : offset + limit]}
        )

    def options(self, url, headers=None):
        key = urlparse(url).path.strip("/").removeprefix("api/")
        self.calls.append(("OPTIONS", key))
        if key in OPTIONS:
            return Response(200, {"actions": {"POST": OPTIONS[key]}})
        return Response(200, {"actions": {}})


def backup(**kwargs):
    api = FakeApi(kwargs.pop("fail", ()))
    result = create_backup(CONFIG, session_factory=lambda c: api, **kwargs)
    return result, api


def test_backup_reads_included_endpoints_with_references():
    result, api = backup()
    data = result.data
    assert data["format"] == "unifi2netbox-backup" and data["version"] == 1
    assert data["netbox_version"] == "4.7.3" and data["source"] == "netbox.example.com"
    assert "secret-token" not in json.dumps(data)
    assert data["complete"] and result.complete
    objects = data["objects"]
    assert "users/users" not in objects and "users/tokens" not in objects
    assert "dcim/cable-terminations" not in objects
    assert "extras/journal-entries" not in objects
    assert any(s.startswith("core") for s in data["skipped"])
    assert objects["users/owners"] == [
        {"id": 15, "name": "Ops", "group": {"$ref": ["users/owner-groups", 14]}}
    ]
    device = objects["dcim/devices"][0]
    assert device == {
        "id": 4,
        "name": "sw1",
        "site": {"$ref": ["dcim/sites", 2]},
        "device_type": {"$ref": ["dcim/device-types", 3]},
        "primary_ip4": {"$ref": ["ipam/ip-addresses", 7]},
    }
    assert objects["dcim/sites"][0]["status"] == "active"
    assert objects["dcim/sites"][0]["tags"] == [{"$ref": ["extras/tags", 9]}]
    ip = objects["ipam/ip-addresses"][0]
    assert ip["assigned_object_type"] == "dcim.interface"
    assert ip["assigned_object_id"] == {"$ref": ["dcim/interfaces", 5]}
    cable = objects["dcim/cables"][0]
    assert cable["a_terminations"] == [
        {"object_type": "dcim.interface", "object_id": {"$ref": ["dcim/interfaces", 5]}}
    ]
    assert objects["dcim/front-ports"][0]["rear_ports"][0]["rear_port"] == {
        "$ref": ["dcim/rear-ports", 11]
    }
    assert "front_ports" not in objects["dcim/rear-ports"][0]
    assert data["object_types"]["dcim.interface"] == "dcim/interfaces"
    assert data["fields"]["dcim/devices"]["site"]["required"] is True
    assert "display" not in data["fields"]["dcim/devices"]
    assert ("POST", "x") not in api.calls


def test_secrets_are_left_out_and_images_embedded():
    result, _api = backup()
    data = result.data
    hook = data["objects"]["extras/webhooks"][0]
    assert "secret" not in hook and "additional_headers" not in hook
    assert set(data["omitted"]) == {
        "extras/webhooks.secret",
        "extras/webhooks.additional_headers",
        "wireless/wireless-lans.auth_psk",
    }
    assert data["objects"]["wireless/wireless-lans"][0] == {
        "id": 16,
        "ssid": "Office",
        "auth_type": "wpa-personal",
        "auth_cipher": "aes",
    }
    assert "wifi-password" not in json.dumps(data)
    assert "extras/scripts/upload" not in data["objects"]
    assert "s3cret" not in json.dumps(data)
    files = {(f["endpoint"], f["field"]): f for f in data["files"]}
    image = files[("dcim/device-types", "front_image")]
    assert image["id"] == 3 and image["name"] == "box.png"
    assert base64.b64decode(image["data"]) == b"PNG"
    assert (
        base64.b64decode(files[("extras/image-attachments", "image")]["data"]) == b"JPG"
    )
    assert "front_image" not in data["objects"]["dcim/device-types"][0]

    without, _ = backup(include_files=False)
    assert without.data["files"] == []


def test_failed_endpoints_mark_the_backup_incomplete_and_cancel_stops():
    result, _ = backup(fail={"dcim/cables"})
    assert not result.complete and result.data["complete"] is False
    assert result.data["errors"][0].startswith("dcim/cables:")
    assert "dcim/cables" not in result.data["objects"]

    seen = []
    with pytest.raises(BackupCancelled):
        backup(progress=seen.append, cancelled=lambda: len(seen) >= 2)
    assert len(seen) == 2


def test_files_round_trip_as_json_and_yaml(tmp_path):
    result, _ = backup()
    for name in ("b.json", "b.yaml"):
        path = tmp_path / name
        write_backup(result, path)
        again = read_backup(path)
        assert again.data == result.data
        assert again.counts() == result.counts()
    assert result.total() == sum(result.counts().values()) > 10
    (tmp_path / "x.json").write_text('{"format": "other"}', encoding="utf-8")
    with pytest.raises(BackupError, match="not a unifi2netbox backup"):
        read_backup(tmp_path / "x.json")
    assert default_name(CONFIG).startswith("netbox-backup-netbox.example.com-")
