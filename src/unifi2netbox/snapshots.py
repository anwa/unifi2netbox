import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from unifi2netbox.inventory import (
    InventoryDevice,
    InventoryDeviceRole,
    InventoryDeviceStatus,
    InventoryDeviceType,
    InventoryDisk,
    InventoryInterface,
    InventoryItem,
    InventoryNetwork,
    InventoryPort,
    InventoryPrefix,
    InventorySite,
    InventorySnapshot,
    InventorySource,
    InventoryVlan,
    InventoryVlanGroup,
)
from unifi2netbox.links import InventoryLink
from unifi2netbox.port_config import InventoryPortConfig

SNAPSHOT_SCHEMA_VERSION = 1


class SnapshotStoreError(ValueError):
    pass


@dataclass(frozen=True)
class StoredSnapshots:
    current: InventorySnapshot | None
    previous: InventorySnapshot | None
    updated_at: str


class SnapshotStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    source TEXT PRIMARY KEY,
                    current_json TEXT NOT NULL,
                    previous_json TEXT,
                    updated_at TEXT NOT NULL
                )
                """)
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO metadata(key, value) VALUES('schema_version', ?)",
                    (str(SNAPSHOT_SCHEMA_VERSION),),
                )
            elif row[0] != str(SNAPSHOT_SCHEMA_VERSION):
                raise SnapshotStoreError("Unsupported snapshot schema version.")

    def save_current(self, snapshot: InventorySnapshot) -> None:
        self.initialize()
        now = datetime.now(UTC).isoformat(timespec="seconds")
        encoded = _encode(snapshot)
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT current_json FROM snapshots WHERE source = ?",
                (snapshot.source.value,),
            ).fetchone()
            previous = row[0] if row is not None else None
            connection.execute(
                """
                INSERT INTO snapshots(source, current_json, previous_json, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    current_json = excluded.current_json,
                    previous_json = excluded.previous_json,
                    updated_at = excluded.updated_at
                """,
                (snapshot.source.value, encoded, previous, now),
            )

    def load_current(self, source: InventorySource) -> InventorySnapshot | None:
        return self.load_state(source).current

    def load_previous(self, source: InventorySource) -> InventorySnapshot | None:
        return self.load_state(source).previous

    def load_state(self, source: InventorySource) -> StoredSnapshots:
        self.initialize()
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                """
                SELECT current_json, previous_json, updated_at
                FROM snapshots
                WHERE source = ?
                """,
                (source.value,),
            ).fetchone()
        if row is None:
            return StoredSnapshots(None, None, "")
        try:
            current = _decode(row[0])
            previous = _decode(row[1]) if row[1] is not None else None
            updated_at = str(row[2])
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
            raise SnapshotStoreError("Stored snapshot data is invalid.") from error
        return StoredSnapshots(current, previous, updated_at)


def _encode(snapshot: InventorySnapshot) -> str:
    data = {
        "source": snapshot.source.value,
        "captured_at": snapshot.captured_at,
        "source_version": snapshot.source_version,
        "scope": snapshot.scope,
        "devices": [asdict(device) for device in snapshot.devices],
        "device_types": [asdict(item) for item in snapshot.device_types],
        "device_roles": [asdict(item) for item in snapshot.device_roles],
        "sites": [asdict(item) for item in snapshot.sites],
        "device_statuses": [asdict(item) for item in snapshot.device_statuses],
        "unifi_api_feedback": list(snapshot.unifi_api_feedback),
        "unifi_raw_devices": list(snapshot.unifi_raw_devices),
        "ports": [asdict(item) for item in snapshot.ports],
        "interfaces": [asdict(item) for item in snapshot.interfaces],
        "networks": [asdict(item) for item in snapshot.networks],
        "vlan_groups": [asdict(item) for item in snapshot.vlan_groups],
        "vlans": [asdict(item) for item in snapshot.vlans],
        "prefixes": [asdict(item) for item in snapshot.prefixes],
        "ipam_error": snapshot.ipam_error,
        "port_configs": [asdict(item) for item in snapshot.port_configs],
        "port_config_error": snapshot.port_config_error,
        "links": [asdict(item) for item in snapshot.links],
        "disks": [asdict(item) for item in snapshot.disks],
        "disk_error": snapshot.disk_error,
        "inventory_items": [asdict(item) for item in snapshot.inventory_items],
        "inventory_item_error": snapshot.inventory_item_error,
    }
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def _decode(raw: str) -> InventorySnapshot:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError
    devices = payload.get("devices")
    if not isinstance(devices, list) or not all(
        isinstance(item, dict) for item in devices
    ):
        raise ValueError
    device_types = payload.get("device_types", [])
    if not isinstance(device_types, list) or not all(
        isinstance(item, dict) for item in device_types
    ):
        raise ValueError
    device_roles = payload.get("device_roles", [])
    if not isinstance(device_roles, list) or not all(
        isinstance(item, dict) for item in device_roles
    ):
        raise ValueError
    sites = payload.get("sites", [])
    if not isinstance(sites, list) or not all(isinstance(item, dict) for item in sites):
        raise ValueError
    device_statuses = payload.get("device_statuses", [])
    if not isinstance(device_statuses, list) or not all(
        isinstance(item, dict) for item in device_statuses
    ):
        raise ValueError
    unifi_api_feedback = payload.get("unifi_api_feedback", [])
    if not isinstance(unifi_api_feedback, list) or not all(
        isinstance(item, dict) for item in unifi_api_feedback
    ):
        raise ValueError
    unifi_raw_devices = payload.get("unifi_raw_devices", [])
    if not isinstance(unifi_raw_devices, list) or not all(
        isinstance(item, dict) for item in unifi_raw_devices
    ):
        raise ValueError
    ports = payload.get("ports", [])
    interfaces = payload.get("interfaces", [])
    networks = payload.get("networks", [])
    vlan_groups = payload.get("vlan_groups", [])
    vlans = payload.get("vlans", [])
    prefixes = payload.get("prefixes", [])
    port_configs = payload.get("port_configs", [])
    links = payload.get("links", [])
    disks = payload.get("disks", [])
    inventory_items = payload.get("inventory_items", [])
    for items in (
        ports,
        interfaces,
        networks,
        vlan_groups,
        vlans,
        prefixes,
        port_configs,
        links,
        disks,
        inventory_items,
    ):
        if not isinstance(items, list) or not all(
            isinstance(item, dict) for item in items
        ):
            raise ValueError
    return InventorySnapshot(
        source=InventorySource(payload["source"]),
        captured_at=str(payload["captured_at"]),
        source_version=str(payload.get("source_version", "")),
        scope=str(payload.get("scope", "")),
        devices=tuple(InventoryDevice(**item) for item in devices),
        device_types=tuple(InventoryDeviceType(**item) for item in device_types),
        device_roles=tuple(InventoryDeviceRole(**item) for item in device_roles),
        sites=tuple(InventorySite(**item) for item in sites),
        device_statuses=tuple(
            InventoryDeviceStatus(**item) for item in device_statuses
        ),
        unifi_api_feedback=tuple(unifi_api_feedback),
        unifi_raw_devices=tuple(unifi_raw_devices),
        ports=tuple(InventoryPort(**item) for item in ports),
        interfaces=tuple(
            InventoryInterface(
                **item
                | {
                    "tagged_vlan_ids": tuple(item.get("tagged_vlan_ids", ())),
                    "link_peer_ids": tuple(item.get("link_peer_ids", ())),
                }
            )
            for item in interfaces
        ),
        networks=tuple(InventoryNetwork(**item) for item in networks),
        vlan_groups=tuple(InventoryVlanGroup(**item) for item in vlan_groups),
        vlans=tuple(InventoryVlan(**item) for item in vlans),
        prefixes=tuple(InventoryPrefix(**item) for item in prefixes),
        ipam_error=str(payload.get("ipam_error", "")),
        port_configs=tuple(
            InventoryPortConfig(
                **item
                | {
                    "tagged_vids": tuple(item.get("tagged_vids", ())),
                    "notes": tuple(item.get("notes", ())),
                }
            )
            for item in port_configs
        ),
        port_config_error=str(payload.get("port_config_error", "")),
        links=tuple(InventoryLink(**item) for item in links),
        disks=tuple(InventoryDisk(**item) for item in disks),
        disk_error=str(payload.get("disk_error", "")),
        inventory_items=tuple(InventoryItem(**item) for item in inventory_items),
        inventory_item_error=str(payload.get("inventory_item_error", "")),
    )
