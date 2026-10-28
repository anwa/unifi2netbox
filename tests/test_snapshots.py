import sqlite3

import pytest

from unifi2netbox.inventory import InventoryDevice, InventorySnapshot, InventorySource
from unifi2netbox.snapshots import (
    SNAPSHOT_SCHEMA_VERSION,
    SnapshotStore,
    SnapshotStoreError,
)


def netbox_snapshot(captured: str, serial: str) -> InventorySnapshot:
    return InventorySnapshot(
        source=InventorySource.NETBOX,
        captured_at=captured,
        source_version="4.7.3",
        devices=(
            InventoryDevice(
                source_id="1",
                name="edge-a",
                serial=serial,
                model="USW-24",
                manufacturer="Ubiquiti",
                mac_address="00:11:22:33:44:55",
                site="HQ",
            ),
        ),
    )


def test_store_initializes_schema(tmp_path):
    path = tmp_path / "state" / "snapshots.sqlite3"
    store = SnapshotStore(path)
    store.initialize()

    with sqlite3.connect(path) as connection:
        value = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()[0]
    assert value == str(SNAPSHOT_SCHEMA_VERSION)


def test_save_current_shifts_previous(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")

    first = netbox_snapshot("2026-10-28T12:00:00+00:00", "ABC")
    second = netbox_snapshot("2026-10-28T12:05:00+00:00", "DEF")

    store.save_current(first)
    assert store.load_current(InventorySource.NETBOX) == first
    assert store.load_previous(InventorySource.NETBOX) is None

    store.save_current(second)
    assert store.load_current(InventorySource.NETBOX) == second
    assert store.load_previous(InventorySource.NETBOX) == first


def test_sources_are_stored_independently(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    netbox = netbox_snapshot("2026-10-28T12:00:00+00:00", "ABC")
    unifi = InventorySnapshot(
        source=InventorySource.UNIFI_NETWORK,
        captured_at="2026-10-28T12:01:00+00:00",
        source_version="10.6.100",
        scope="Default (site)",
        devices=(InventoryDevice(source_id="u1", name="ap-1"),),
    )

    store.save_current(netbox)
    store.save_current(unifi)

    assert store.load_current(InventorySource.NETBOX) == netbox
    assert store.load_current(InventorySource.UNIFI_NETWORK) == unifi


def test_schema_mismatch_is_rejected(tmp_path):
    path = tmp_path / "snapshots.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO metadata(key, value) VALUES('schema_version', '999')"
        )
        connection.execute("""
            CREATE TABLE snapshots (
                source TEXT PRIMARY KEY,
                current_json TEXT NOT NULL,
                previous_json TEXT,
                updated_at TEXT NOT NULL
            )
            """)

    with pytest.raises(SnapshotStoreError, match="Unsupported snapshot schema version"):
        SnapshotStore(path).initialize()


def test_invalid_snapshot_payload_raises_store_error(tmp_path):
    path = tmp_path / "snapshots.sqlite3"
    store = SnapshotStore(path)
    store.initialize()
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO snapshots(source, current_json, previous_json, updated_at)
            VALUES(?, ?, NULL, '2026-10-28T12:00:00+00:00')
            """,
            (InventorySource.NETBOX.value, "{}"),
        )

    with pytest.raises(SnapshotStoreError, match="invalid"):
        store.load_current(InventorySource.NETBOX)
