from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from unifi2netbox.inventory import InventoryDevice, InventorySnapshot, InventorySource
from unifi2netbox.snapshots import SnapshotStore

REPORT_SCHEMA_VERSION = 1


class ExportError(ValueError):
    pass


def export_sanitized_snapshot_report(
    store: SnapshotStore,
    output_path: Path,
    *,
    opt_in: bool,
    include_previous: bool = True,
    generated_at: datetime | None = None,
) -> Path:
    if not opt_in:
        raise ExportError("Snapshot export is disabled unless explicitly opted in.")

    timestamp = generated_at or datetime.now(UTC)
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": timestamp.astimezone(UTC).isoformat(timespec="seconds"),
        "sources": {
            InventorySource.NETBOX.value: _source_payload(
                store, InventorySource.NETBOX, include_previous
            ),
            InventorySource.UNIFI_NETWORK.value: _source_payload(
                store, InventorySource.UNIFI_NETWORK, include_previous
            ),
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output_path


def _source_payload(
    store: SnapshotStore,
    source: InventorySource,
    include_previous: bool,
) -> dict[str, Any]:
    state = store.load_state(source)
    result: dict[str, Any] = {
        "updated_at": state.updated_at,
        "current": _sanitize_snapshot(state.current),
    }
    if include_previous:
        result["previous"] = _sanitize_snapshot(state.previous)
    return result


def _sanitize_snapshot(snapshot: InventorySnapshot | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    return {
        "source": snapshot.source.value,
        "captured_at": snapshot.captured_at,
        "source_version": snapshot.source_version,
        "scope": _mask(snapshot.scope, "scope"),
        "device_count": len(snapshot.devices),
        "devices": [_sanitize_device(device) for device in snapshot.devices],
    }


def _sanitize_device(device: InventoryDevice) -> dict[str, str]:
    return {
        "source_id": _mask(device.source_id, "source_id"),
        "name": _mask(device.name, "name"),
        "serial": _mask(device.serial, "serial"),
        "model": device.model,
        "manufacturer": device.manufacturer,
        "mac_address": _mask(device.mac_address, "mac"),
        "site": _mask(device.site, "site"),
    }


def _mask(value: str, label: str) -> str:
    if not value.strip():
        return ""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{label}:{digest}"
