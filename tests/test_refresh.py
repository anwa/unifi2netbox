from unifi2netbox.config import NetBoxConfig, UniFiConfig
from unifi2netbox.inventory import (
    InventoryDevice,
    InventoryError,
    InventorySnapshot,
    InventorySource,
)
from unifi2netbox.refresh import refresh_snapshots
from unifi2netbox.snapshots import SnapshotStore


def snapshot(source: InventorySource, captured_at: str) -> InventorySnapshot:
    return InventorySnapshot(
        source=source,
        captured_at=captured_at,
        source_version="4.7.3" if source is InventorySource.NETBOX else "10.6.100",
        devices=(InventoryDevice(source_id="1", name="device"),),
    )


def test_refresh_saves_successful_snapshots_and_preserves_previous(
    tmp_path, monkeypatch
):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    first = snapshot(InventorySource.NETBOX, "2026-10-28T12:00:00+00:00")
    second = snapshot(InventorySource.NETBOX, "2026-10-28T12:01:00+00:00")

    calls = {"netbox": 0}

    def netbox_reader(config, **kwargs):
        calls["netbox"] += 1
        return first if calls["netbox"] == 1 else second

    def unifi_reader(config, **kwargs):
        return snapshot(InventorySource.UNIFI_NETWORK, "2026-10-28T12:00:30+00:00")

    monkeypatch.setattr("unifi2netbox.refresh.read_netbox_inventory", netbox_reader)
    monkeypatch.setattr("unifi2netbox.refresh.read_unifi_inventory", unifi_reader)

    netbox = NetBoxConfig("https://netbox.invalid", "token")
    unifi = UniFiConfig("https://console.invalid", "token", site="default")

    result1 = refresh_snapshots(netbox, unifi, store)
    assert result1.netbox.error == ""
    assert result1.netbox.snapshot == first

    result2 = refresh_snapshots(netbox, unifi, store)
    assert result2.netbox.snapshot == second
    assert store.load_previous(InventorySource.NETBOX) == first


def test_refresh_reports_errors_without_overwriting_last_good_snapshot(
    tmp_path, monkeypatch
):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    good = snapshot(InventorySource.NETBOX, "2026-10-28T12:00:00+00:00")

    monkeypatch.setattr(
        "unifi2netbox.refresh.read_netbox_inventory", lambda config, **kwargs: good
    )
    monkeypatch.setattr(
        "unifi2netbox.refresh.read_unifi_inventory",
        lambda config, **kwargs: snapshot(
            InventorySource.UNIFI_NETWORK, "2026-10-28T12:00:30+00:00"
        ),
    )

    netbox = NetBoxConfig("https://netbox.invalid", "token")
    unifi = UniFiConfig("https://console.invalid", "token", site="default")
    refresh_snapshots(netbox, unifi, store)

    def failing_reader(config, **kwargs):
        raise InventoryError("boom")

    monkeypatch.setattr("unifi2netbox.refresh.read_netbox_inventory", failing_reader)
    result = refresh_snapshots(netbox, unifi, store)

    assert result.netbox.snapshot is None
    assert result.netbox.error
    assert store.load_current(InventorySource.NETBOX) == good
