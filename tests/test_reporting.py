import json
from datetime import UTC, datetime

import pytest

from unifi2netbox.inventory import InventoryDevice, InventorySnapshot, InventorySource
from unifi2netbox.reporting import ExportError, export_sanitized_snapshot_report
from unifi2netbox.snapshots import SnapshotStore


def netbox_snapshot(captured: str, source_id: str, serial: str) -> InventorySnapshot:
    return InventorySnapshot(
        source=InventorySource.NETBOX,
        captured_at=captured,
        source_version="4.7.3",
        scope="HQ (site-1)",
        devices=(
            InventoryDevice(
                source_id=source_id,
                name="edge-a",
                serial=serial,
                model="USW-24",
                manufacturer="Ubiquiti",
                mac_address="00:11:22:33:44:55",
                site="HQ",
            ),
        ),
    )


def test_export_requires_explicit_opt_in(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    with pytest.raises(ExportError, match="explicitly opted in"):
        export_sanitized_snapshot_report(
            store,
            tmp_path / "report.json",
            opt_in=False,
        )


def test_export_writes_sanitized_current_and_previous(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    first = netbox_snapshot("2026-10-28T12:00:00+00:00", "id-a", "SERIAL-A")
    second = netbox_snapshot("2026-10-28T12:05:00+00:00", "id-b", "SERIAL-B")
    store.save_current(first)
    store.save_current(second)

    output = tmp_path / "reports" / "snapshot-report.json"
    export_sanitized_snapshot_report(
        store,
        output,
        opt_in=True,
        include_previous=True,
        generated_at=datetime(2026, 10, 28, 13, 0, tzinfo=UTC),
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["generated_at"] == "2026-10-28T13:00:00+00:00"

    netbox = payload["sources"]["netbox"]
    current = netbox["current"]
    previous = netbox["previous"]

    assert current["source"] == "netbox"
    assert current["source_version"] == "4.7.3"
    assert current["device_count"] == 1
    assert current["devices"][0]["model"] == "USW-24"
    assert current["devices"][0]["manufacturer"] == "Ubiquiti"

    # Sensitive values must be pseudonymized deterministically.
    assert current["scope"].startswith("scope:")
    assert current["devices"][0]["source_id"].startswith("source_id:")
    assert current["devices"][0]["serial"].startswith("serial:")
    assert current["devices"][0]["mac_address"].startswith("mac:")
    assert current["devices"][0]["site"].startswith("site:")

    # Previous snapshot is available and separately sanitized.
    assert previous["devices"][0]["serial"].startswith("serial:")
    assert previous["devices"][0]["serial"] != current["devices"][0]["serial"]


def test_export_can_omit_previous_snapshot(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.save_current(netbox_snapshot("2026-10-28T12:00:00+00:00", "id-a", "S-A"))

    output = tmp_path / "report.json"
    export_sanitized_snapshot_report(
        store,
        output,
        opt_in=True,
        include_previous=False,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    netbox = payload["sources"]["netbox"]
    assert "previous" not in netbox
