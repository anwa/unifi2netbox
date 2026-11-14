"""Drive (UNAS) connection check against synthetic transports."""

import httpx
import pytest

from unifi2netbox.config import ConfigError, DriveConfig
from unifi2netbox.drive import check_drive_connection
from unifi2netbox.netbox import ConnectionState

CONFIG = DriveConfig("https://unas.invalid", "synthetic-key")
SYSTEM = {"hardware": {"shortname": "UNASPRO"}, "mac": "aabbccddeeff", "name": "NAS"}


def transport(response, seen=None):
    def handle(request):
        assert request.method == "GET"
        if seen is not None:
            seen.append((request.url.path, dict(request.headers)))
        if isinstance(response, httpx.Response):
            return response
        return httpx.Response(200, json=response)

    return httpx.MockTransport(handle)


def test_online_reads_public_system_info_without_sending_the_key():
    seen = []

    result = check_drive_connection(CONFIG, transport=transport(SYSTEM, seen))

    assert result.state == ConnectionState.ONLINE
    assert "UNASPRO" in result.message
    ((path, headers),) = seen
    assert path == "/api/system"
    assert "synthetic-key" not in " ".join(headers.values())


def test_unconfigured_is_optional_and_never_contacts_a_console():
    def refuse(request):
        raise AssertionError("no request expected")

    result = check_drive_connection(
        DriveConfig(), transport=httpx.MockTransport(refuse)
    )

    assert result.state == ConnectionState.UNCONFIGURED
    assert result.message.startswith("Optional.")


@pytest.mark.parametrize(
    ("response", "state"),
    [
        ({"hardware": {"shortname": "UDMPRO"}}, "Unsupported"),
        ({"hardware": "UNAS"}, "Unsupported"),
        ({"no": "hardware"}, "Unsupported"),
        (
            httpx.Response(200, text="<html>", headers={"content-type": "text/html"}),
            "Unsupported",
        ),
        (httpx.Response(404, json={}), "Unsupported"),
        (httpx.Response(302, headers={"location": "/login"}), "Error"),
        (httpx.Response(500, json={}), "Error"),
        (["not a dict"], "Error"),
    ],
)
def test_other_answers_are_never_online(response, state):
    result = check_drive_connection(CONFIG, transport=transport(response))

    assert result.state == state
    assert "synthetic-key" not in result.message


def test_timeout_is_offline():
    def handle(request):
        raise httpx.ReadTimeout("slow", request=request)

    result = check_drive_connection(CONFIG, transport=httpx.MockTransport(handle))

    assert result.state == ConnectionState.OFFLINE


def test_drive_config_rejects_paths():
    with pytest.raises(ConfigError):
        DriveConfig("https://unas.invalid/api/system", "k")
    assert DriveConfig("https://unas.invalid/", "k").url


STORAGE = {
    "disks": [
        {
            "slotId": "1",
            "model": "WDC WD80EFPX",
            "serial": "SYN-SERIAL-1",
            "firmware": "81.00A81",
            "type": "HDD",
            "size": 8001563222016,
            "state": "optimal",
            "temperature": 34,
            "healthScore": 100,
            "poolId": "pool-1",
            "readKBPS": 12,
            "location": "ignored",
        },
        {"slotId": "2", "state": "empty", "model": "", "type": ""},
    ],
    "pools": [{"id": "pool-1", "capacity": 1}],
}


def inventory_transport(storage, seen):
    def handle(request):
        assert request.method == "GET"
        seen.append((request.url.path, request.headers.get("X-API-KEY")))
        if request.url.path == "/api/system":
            return httpx.Response(200, json=SYSTEM | {"deviceState": "setup"})
        if isinstance(storage, httpx.Response):
            return storage
        return httpx.Response(200, json=storage)

    return httpx.MockTransport(handle)


def test_inventory_reads_the_unas_and_allow_listed_drive_bays():
    from unifi2netbox.drive import read_drive_inventory
    from unifi2netbox.inventory import InventorySource

    seen = []
    snapshot = read_drive_inventory(
        CONFIG, transport=inventory_transport(STORAGE, seen)
    )

    assert snapshot.source == InventorySource.UNIFI_DRIVE
    assert seen == [
        ("/api/system", None),
        ("/proxy/drive/api/v2/storage", "synthetic-key"),
    ]
    (device,) = snapshot.devices
    assert (device.source_id, device.name, device.model, device.kind) == (
        "aabbccddeeff",
        "NAS",
        "UNASPRO",
        "nas",
    )
    assert (device.mac_address, device.manufacturer) == (
        "AA:BB:CC:DD:EE:FF",
        "Ubiquiti",
    )
    assert device.state == "online"
    full, empty = snapshot.disks
    assert full.device_id == "aabbccddeeff"
    assert (full.slot, full.model, full.serial, full.firmware) == (
        "1",
        "WDC WD80EFPX",
        "SYN-SERIAL-1",
        "81.00A81",
    )
    assert (full.kind, full.size_bytes, full.state) == ("HDD", 8001563222016, "optimal")
    assert (full.temperature_c, full.health, full.pool) == (34, 100, "pool-1")
    assert (empty.slot, empty.model, empty.state) == ("2", "", "empty")
    assert snapshot.disk_error == ""


@pytest.mark.parametrize(
    ("storage", "fragment"),
    [
        (httpx.Response(401, json={}), "rejected the local API key"),
        (httpx.Response(404, json={"err": "x"}), "HTTP 404"),
        ({"no": "disks"}, "no supported drive-bay list"),
        ({"disks": [{"slotId": "1"}, {"slotId": "1"}]}, "duplicate"),
    ],
)
def test_failed_storage_reads_keep_the_device(storage, fragment):
    from unifi2netbox.drive import read_drive_inventory

    snapshot = read_drive_inventory(CONFIG, transport=inventory_transport(storage, []))

    assert len(snapshot.devices) == 1
    assert snapshot.disks == ()
    assert fragment in snapshot.disk_error
    assert "synthetic-key" not in snapshot.disk_error


def test_inventory_refuses_non_unas_consoles_and_missing_settings():
    from unifi2netbox.drive import read_drive_inventory
    from unifi2netbox.inventory import InventoryError

    with pytest.raises(InventoryError, match="not a UniFi Drive console"):
        read_drive_inventory(
            CONFIG, transport=transport({"hardware": {"shortname": "UDMPRO"}})
        )
    with pytest.raises(InventoryError):
        read_drive_inventory(DriveConfig())


def test_drive_snapshot_round_trips_with_disks(tmp_path):
    from unifi2netbox.drive import read_drive_inventory
    from unifi2netbox.inventory import InventorySource
    from unifi2netbox.snapshots import SnapshotStore

    snapshot = read_drive_inventory(CONFIG, transport=inventory_transport(STORAGE, []))
    store = SnapshotStore(tmp_path / "snapshots.sqlite3")
    store.save_current(snapshot)

    assert store.load_current(InventorySource.UNIFI_DRIVE) == snapshot
