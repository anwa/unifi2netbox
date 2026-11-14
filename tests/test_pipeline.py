from unifi2netbox.config import NetBoxConfig, UniFiConfig
from unifi2netbox.inventory import (
    InventoryDevice,
    InventoryDeviceRole,
    InventoryError,
    InventorySite,
    InventorySnapshot,
    InventorySource,
)
from unifi2netbox.pipeline import build_inventory_preview

NETBOX = NetBoxConfig("https://netbox.invalid", "token")
UNIFI = UniFiConfig("https://console.invalid", "token", site="default")


def _snapshot(source: InventorySource, devices, **catalogs) -> InventorySnapshot:
    return InventorySnapshot(
        source=source,
        captured_at="2026-11-14T10:00:00+00:00",
        source_version="x",
        devices=tuple(devices),
        **catalogs,
    )


def _patch_readers(monkeypatch, netbox_reader, unifi_reader):
    monkeypatch.setattr("unifi2netbox.refresh.read_netbox_inventory", netbox_reader)
    monkeypatch.setattr("unifi2netbox.refresh.read_unifi_inventory", unifi_reader)


def test_build_inventory_preview_ready_produces_rows_and_plan(tmp_path, monkeypatch):
    netbox = _snapshot(
        InventorySource.NETBOX,
        [InventoryDevice(source_id="1", name="switch-a", serial="OLD", site="HQ")],
        device_roles=(InventoryDeviceRole(source_id="5", name="Switch"),),
        sites=(InventorySite(source_id="7", name="HQ"),),
    )
    unifi = _snapshot(
        InventorySource.UNIFI_NETWORK,
        [InventoryDevice(source_id="a", name="switch-a", serial="NEW", site="HQ")],
        unifi_api_feedback=({"endpoint": "info", "params": {}, "payload": {}},),
        unifi_raw_devices=({"id": "a", "name": "switch-a"},),
    )
    _patch_readers(monkeypatch, lambda config, **kw: netbox, lambda c, **kw: unifi)

    result = build_inventory_preview(
        tmp_path / "config.toml",
        NETBOX,
        UNIFI,
        include_all_netbox_delete_candidates=False,
    )

    assert result.status == "Ready"
    assert result.matched_devices == 1
    assert result.executable_operations == 1
    assert result.netbox_device_roles == ("Switch",)
    assert result.netbox_sites == ("HQ",)
    assert [row.action for row in result.rows] == ["update"]
    assert result.write_plan is not None
    assert result.difference_preview is not None
    assert (tmp_path / "snapshots.sqlite3").exists()
    assert result.unifi_captured_at == "2026-11-14T10:00:00+00:00"
    assert result.unifi_raw_devices == ({"id": "a", "name": "switch-a"},)
    assert result.unifi_api_feedback[0]["endpoint"] == "info"


def test_build_inventory_preview_partial_on_source_error(tmp_path, monkeypatch):
    unifi = _snapshot(InventorySource.UNIFI_NETWORK, [])

    def failing_netbox(config, **kwargs):
        raise InventoryError("NetBox read failed.")

    _patch_readers(monkeypatch, failing_netbox, lambda c, **kw: unifi)

    result = build_inventory_preview(
        tmp_path / "config.toml",
        NETBOX,
        UNIFI,
        include_all_netbox_delete_candidates=False,
    )

    assert result.status == "Partial"
    assert result.write_plan is None
    assert result.difference_preview is None
    assert result.detail_lines
