"""Refresh the bundled NetBox field metadata for device types (read-only).

Usage (repository root, project .venv; reads the app configuration):

    python tools/update_netbox_metadata.py [--config PATH]

Sends OPTIONS requests to the device type, template and related endpoints of
the configured NetBox and writes the writable fields (type, required, label,
help text, choices) to
``src/unifi2netbox/resources/netbox-metadata/netbox-<major.minor>.json``.
Nothing is written to NetBox; the token is never printed. Review the diff
before committing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from unifi2netbox.config import default_config_path, load_config  # noqa: E402

ENDPOINTS = (
    "dcim/device-types",
    "dcim/console-port-templates",
    "dcim/console-server-port-templates",
    "dcim/power-port-templates",
    "dcim/power-outlet-templates",
    "dcim/interface-templates",
    "dcim/front-port-templates",
    "dcim/rear-port-templates",
    "dcim/module-bay-templates",
    "dcim/device-bay-templates",
    "dcim/inventory-item-templates",
    "dcim/cooling-intake-templates",
    "dcim/cooling-outflow-templates",
    "dcim/manufacturers",
    "dcim/platforms",
    "dcim/inventory-item-roles",
    "extras/tags",
    "users/owners",
    "users/owner-groups",
)
SKIP = {"id", "url", "display", "display_url", "created", "last_updated"}
TARGET = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "unifi2netbox"
    / "resources"
    / "netbox-metadata"
)


def describe(field: dict) -> dict:
    kind = field.get("type", "")
    result: dict = {
        "type": kind,
        "required": bool(field.get("required")),
        "label": field.get("label", ""),
    }
    if field.get("help_text"):
        result["help"] = field["help_text"]
    if field.get("choices"):
        result["choices"] = [str(c.get("value")) for c in field["choices"]]
    child = field.get("child")
    if isinstance(child, dict) and isinstance(child.get("children"), dict):
        result["children"] = {
            name: describe(sub)
            for name, sub in child["children"].items()
            if name not in SKIP and not sub.get("read_only")
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=default_config_path())
    args = parser.parse_args()
    config = load_config(args.config)
    session = requests.Session()
    session.headers["Authorization"] = f"Token {config.token}"
    session.headers["Accept"] = "application/json"
    verify = (config.ca_bundle or True) if config.verify_tls else False
    base = config.url.rstrip("/") + "/api/"

    def call(method: str, path: str) -> dict:
        response = session.request(
            method, base + path, timeout=config.timeout, verify=verify,
            allow_redirects=False,
        )
        response.raise_for_status()
        return response.json()

    version = str(call("GET", "status/").get("netbox-version", ""))
    endpoints = {}
    for path in ENDPOINTS:
        post = (call("OPTIONS", f"{path}/").get("actions") or {}).get("POST", {})
        endpoints[path] = {
            name: describe(field)
            for name, field in post.items()
            if name not in SKIP and not field.get("read_only")
        }
        print(f"{path}: {len(endpoints[path])} fields")
    series = ".".join(version.split(".")[:2]) or "unknown"
    TARGET.mkdir(parents=True, exist_ok=True)
    target = TARGET / f"netbox-{series}.json"
    target.write_text(
        json.dumps(
            {"netbox_version": version, "endpoints": endpoints},
            indent=1,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print("wrote", target.name, "for NetBox", version)


if __name__ == "__main__":
    main()
