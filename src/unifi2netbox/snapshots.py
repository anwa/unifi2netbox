import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from unifi2netbox.inventory import InventoryDevice, InventorySnapshot, InventorySource

SNAPSHOT_SCHEMA_VERSION = 1


class SnapshotStoreError(ValueError):
    pass


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
        return self._load(source, "current_json")

    def load_previous(self, source: InventorySource) -> InventorySnapshot | None:
        return self._load(source, "previous_json")

    def _load(self, source: InventorySource, column: str) -> InventorySnapshot | None:
        self.initialize()
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                f"SELECT {column} FROM snapshots WHERE source = ?",  # noqa: S608
                (source.value,),
            ).fetchone()
        if row is None or row[0] is None:
            return None
        try:
            return _decode(row[0])
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
            raise SnapshotStoreError("Stored snapshot data is invalid.") from error


def _encode(snapshot: InventorySnapshot) -> str:
    data = {
        "source": snapshot.source.value,
        "captured_at": snapshot.captured_at,
        "source_version": snapshot.source_version,
        "scope": snapshot.scope,
        "devices": [asdict(device) for device in snapshot.devices],
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
    return InventorySnapshot(
        source=InventorySource(payload["source"]),
        captured_at=str(payload["captured_at"]),
        source_version=str(payload.get("source_version", "")),
        scope=str(payload.get("scope", "")),
        devices=tuple(InventoryDevice(**item) for item in devices),
    )
