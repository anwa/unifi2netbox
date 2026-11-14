from datetime import UTC, datetime

from unifi2netbox.config import NetBoxConfig, UniFiConfig
from unifi2netbox.inventory import (
    InventoryDevice,
    InventoryError,
    InventorySnapshot,
    InventorySource,
)
from unifi2netbox.refresh import browse_cached_snapshots, refresh_snapshots
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
    assert result1.netbox.previous_snapshot is None
    assert result1.netbox.stale is False
    assert result1.netbox.cached is False
    assert result1.netbox.last_updated

    result2 = refresh_snapshots(netbox, unifi, store)
    assert result2.netbox.snapshot == second
    assert result2.netbox.previous_snapshot == first
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

    assert result.netbox.snapshot == good
    assert result.netbox.cached is True
    assert result.netbox.stale is True
    assert result.netbox.error
    assert "refresh failed" in result.netbox.diagnostics[0]
    assert store.load_current(InventorySource.NETBOX) == good


def test_browse_cached_snapshots_marks_missing_data_as_stale(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")

    result = browse_cached_snapshots(store, max_age_seconds=300)

    assert result.netbox.stale is True
    assert result.netbox.snapshot is None
    assert "No cached NetBox snapshot" in result.netbox.diagnostics[0]
    assert result.unifi.stale is True
    assert result.unifi.snapshot is None


def test_browse_cached_snapshots_marks_old_snapshot_as_stale(tmp_path, monkeypatch):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    old = snapshot(InventorySource.NETBOX, "2026-10-28T12:00:00+00:00")
    monkeypatch.setattr(
        "unifi2netbox.refresh.read_netbox_inventory", lambda config, **kwargs: old
    )
    monkeypatch.setattr(
        "unifi2netbox.refresh.read_unifi_inventory",
        lambda config, **kwargs: snapshot(
            InventorySource.UNIFI_NETWORK, "2026-10-28T12:00:30+00:00"
        ),
    )
    refresh_snapshots(
        NetBoxConfig("https://netbox.invalid", "token"),
        UniFiConfig("https://console.invalid", "token", site="default"),
        store,
    )

    browse = browse_cached_snapshots(
        store,
        max_age_seconds=60,
        now=datetime(2026, 10, 28, 12, 5, 0, tzinfo=UTC),
    )

    assert browse.netbox.stale is True
    assert "older than 60 seconds" in browse.netbox.diagnostics[0]


def test_browse_cached_snapshots_marks_recent_snapshot_as_fresh(tmp_path, monkeypatch):
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    current = snapshot(InventorySource.NETBOX, "2026-10-28T12:05:00+00:00")
    monkeypatch.setattr(
        "unifi2netbox.refresh.read_netbox_inventory", lambda config, **kwargs: current
    )
    monkeypatch.setattr(
        "unifi2netbox.refresh.read_unifi_inventory",
        lambda config, **kwargs: snapshot(
            InventorySource.UNIFI_NETWORK, "2026-10-28T12:05:00+00:00"
        ),
    )
    refresh_snapshots(
        NetBoxConfig("https://netbox.invalid", "token"),
        UniFiConfig("https://console.invalid", "token", site="default"),
        store,
    )

    browse = browse_cached_snapshots(
        store,
        max_age_seconds=120,
        now=datetime(2026, 10, 28, 12, 5, 30, tzinfo=UTC),
    )

    assert browse.netbox.stale is False
    assert "within freshness limits" in browse.netbox.diagnostics[0]


def test_protect_is_refreshed_only_when_configured_and_fails_softly(
    tmp_path, monkeypatch
):
    from unifi2netbox.config import ProtectConfig

    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    netbox = NetBoxConfig("https://netbox.invalid", "nb")
    unifi = UniFiConfig("https://udm.invalid", "uf")
    protect = ProtectConfig("https://unvr.invalid", "pr")
    good = snapshot(InventorySource.UNIFI_PROTECT, "2026-11-14T12:00:00+00:00")
    reads = {"protect": 0}

    def protect_reader(config, **kwargs):
        reads["protect"] += 1
        if reads["protect"] == 2:
            raise InventoryError("Local API key or Protect read permission was denied.")
        return good

    monkeypatch.setattr(
        "unifi2netbox.refresh.read_netbox_inventory",
        lambda config, **kw: snapshot(InventorySource.NETBOX, good.captured_at),
    )
    monkeypatch.setattr(
        "unifi2netbox.refresh.read_unifi_inventory",
        lambda config, **kw: snapshot(InventorySource.UNIFI_NETWORK, good.captured_at),
    )
    monkeypatch.setattr("unifi2netbox.protect.read_protect_inventory", protect_reader)

    assert refresh_snapshots(netbox, unifi, store).protect is None
    assert refresh_snapshots(netbox, unifi, store, ProtectConfig()).protect is None
    first = refresh_snapshots(netbox, unifi, store, protect)
    failed = refresh_snapshots(netbox, unifi, store, protect)

    assert first.protect.snapshot == good and not first.protect.error
    assert failed.protect.stale and failed.protect.snapshot == good
    assert "denied" in failed.protect.error
    assert not failed.netbox.error and not failed.unifi.error
    assert store.load_current(InventorySource.UNIFI_PROTECT) == good


def test_access_is_refreshed_only_when_configured_and_fails_softly(
    tmp_path, monkeypatch
):
    from unifi2netbox.config import AccessConfig

    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    netbox = NetBoxConfig("https://netbox.invalid", "nb")
    unifi = UniFiConfig("https://udm.invalid", "uf")
    access = AccessConfig("https://udm.invalid:12445", "ac")
    good = snapshot(InventorySource.UNIFI_ACCESS, "2026-11-14T12:00:00+00:00")
    reads = {"access": 0}

    def access_reader(config, **kwargs):
        reads["access"] += 1
        if reads["access"] == 2:
            raise InventoryError("The Access API token was rejected.")
        return good

    monkeypatch.setattr(
        "unifi2netbox.refresh.read_netbox_inventory",
        lambda config, **kw: snapshot(InventorySource.NETBOX, good.captured_at),
    )
    monkeypatch.setattr(
        "unifi2netbox.refresh.read_unifi_inventory",
        lambda config, **kw: snapshot(InventorySource.UNIFI_NETWORK, good.captured_at),
    )
    monkeypatch.setattr("unifi2netbox.access.read_access_inventory", access_reader)

    assert refresh_snapshots(netbox, unifi, store).access is None
    assert refresh_snapshots(netbox, unifi, store, None, AccessConfig()).access is None
    first = refresh_snapshots(netbox, unifi, store, None, access)
    failed = refresh_snapshots(netbox, unifi, store, None, access)

    assert first.access.snapshot == good and not first.access.error
    assert failed.access.stale and failed.access.snapshot == good
    assert "rejected" in failed.access.error
    assert not failed.netbox.error and not failed.unifi.error
    assert store.load_current(InventorySource.UNIFI_ACCESS) == good
