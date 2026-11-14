"""Protect connection check against synthetic transports."""

import httpx
import pytest

from unifi2netbox.config import ConfigError, ProtectConfig
from unifi2netbox.netbox import ConnectionState
from unifi2netbox.protect import check_protect_connection

CONFIG = ProtectConfig("https://unvr.invalid", "synthetic-key")


def transport(responses, seen=None):
    def handle(request):
        assert request.method == "GET"
        path = request.url.path.split("/proxy/protect/integration/v1/", 1)[1]
        if seen is not None:
            seen.append((path, request.headers.get("X-API-KEY")))
        value = responses[path]
        if isinstance(value, httpx.Response):
            return value
        return httpx.Response(200, json=value)

    return httpx.MockTransport(handle)


GOOD = {
    "meta/info": {"applicationVersion": "7.3.70"},
    "nvrs": {"id": "n1", "modelKey": "nvr", "name": "UNVR"},
    "cameras": [{"id": "c1"}, {"id": "c2"}],
}


def test_online_reads_info_nvr_and_cameras_with_the_key():
    seen = []

    result = check_protect_connection(CONFIG, transport=transport(GOOD, seen))

    assert result.state == ConnectionState.ONLINE
    assert result.version == "7.3.70"
    assert "2 cameras" in result.message
    assert [path for path, _ in seen] == ["meta/info", "nvrs", "cameras"]
    assert {key for _, key in seen} == {"synthetic-key"}


def test_unconfigured_is_optional_and_never_contacts_a_console():
    def refuse(request):
        raise AssertionError("no request expected")

    result = check_protect_connection(
        ProtectConfig(), transport=httpx.MockTransport(refuse)
    )

    assert result.state == ConnectionState.UNCONFIGURED
    assert result.message.startswith("Optional.")


def test_console_without_protect_answers_html_and_is_unsupported():
    html = httpx.Response(
        200, text="<!doctype html><html></html>", headers={"content-type": "text/html"}
    )

    result = check_protect_connection(CONFIG, transport=transport({"meta/info": html}))

    assert result.state == ConnectionState.UNSUPPORTED
    assert "No UniFi Protect" in result.message


@pytest.mark.parametrize(
    ("code", "state"),
    [
        (401, ConnectionState.UNAUTHORIZED),
        (403, ConnectionState.UNAUTHORIZED),
        (404, ConnectionState.UNSUPPORTED),
        (302, ConnectionState.ERROR),
        (500, ConnectionState.ERROR),
    ],
)
def test_failed_reads_are_never_online(code, state):
    responses = dict(GOOD, cameras=httpx.Response(code, json={"secret": "x"}))

    result = check_protect_connection(CONFIG, transport=transport(responses))

    assert result.state == state
    assert "secret" not in result.message


@pytest.mark.parametrize("text", ["6.2.88", "7.4.0", "7.3.0-beta.1"])
def test_unvalidated_versions_are_unsupported(text):
    responses = dict(GOOD, **{"meta/info": {"applicationVersion": text}})

    result = check_protect_connection(CONFIG, transport=transport(responses))

    assert result.state == ConnectionState.UNSUPPORTED


@pytest.mark.parametrize("cameras", [{"id": "c1"}, "x", None])
def test_unexpected_shapes_are_errors(cameras):
    responses = dict(GOOD, cameras=cameras)

    result = check_protect_connection(CONFIG, transport=transport(responses))

    assert result.state == ConnectionState.ERROR


def test_timeout_is_offline():
    def handle(request):
        raise httpx.ReadTimeout("slow", request=request)

    result = check_protect_connection(CONFIG, transport=httpx.MockTransport(handle))

    assert result.state == ConnectionState.OFFLINE


def test_protect_config_rejects_api_endpoints():
    with pytest.raises(ConfigError):
        ProtectConfig("https://unvr.invalid/proxy/protect/integration/v1", "k")


INVENTORY = {
    "meta/info": {"applicationVersion": "7.3.74"},
    "nvrs": {
        "id": "nvr1",
        "modelKey": "nvr",
        "name": "Rack NVR",
        "type": "UNVR4",
        "mac": "AABBCC000001",
        "doorbellSettings": {"customMessages": ["synthetic"]},
    },
    "cameras": [
        {
            "id": "c1",
            "modelKey": "camera",
            "name": "Garden",
            "type": "UVC G6 Bullet",
            "mac": "aabbcc000002",
            "state": "CONNECTED",
            "osdSettings": {"isNameEnabled": True},
        },
        {
            "id": "c2",
            "modelKey": "camera",
            "name": "Pan tilt",
            "type": "CAM-PT2",
            "mac": "aabbcc000003",
            "state": "DISCONNECTED",
        },
    ],
}


def test_inventory_keeps_identity_fields_and_never_assumes_a_vendor():
    from unifi2netbox.inventory import InventorySource
    from unifi2netbox.protect import read_protect_inventory

    seen = []
    snapshot = read_protect_inventory(CONFIG, transport=transport(INVENTORY, seen))

    assert snapshot.source == InventorySource.UNIFI_PROTECT
    assert (snapshot.source_version, snapshot.scope) == ("7.3.74", "Rack NVR")
    nvr, garden, third_party = snapshot.devices
    assert (nvr.kind, nvr.model, nvr.manufacturer) == ("nvr", "UNVR4", "Ubiquiti")
    assert nvr.mac_address == "AA:BB:CC:00:00:01"
    assert (garden.kind, garden.state, garden.manufacturer) == (
        "camera",
        "CONNECTED",
        "Ubiquiti",
    )
    assert (third_party.model, third_party.manufacturer) == ("CAM-PT2", "")
    assert "synthetic" not in repr(snapshot)
    assert [path for path, _ in seen] == ["meta/info", "nvrs", "cameras"]


@pytest.mark.parametrize(
    "cameras",
    [
        "not-a-list",
        [{"modelKey": "camera", "name": "no id"}],
        [{"id": "c1", "modelKey": "light"}],
        [{"id": "nvr1", "modelKey": "camera"}],
    ],
)
def test_malformed_protect_inventory_is_rejected(cameras):
    from unifi2netbox.inventory import InventoryError
    from unifi2netbox.protect import read_protect_inventory

    with pytest.raises(InventoryError):
        read_protect_inventory(
            CONFIG, transport=transport(dict(INVENTORY, cameras=cameras))
        )


def test_protect_read_failures_become_inventory_errors():
    from unifi2netbox.inventory import InventoryError
    from unifi2netbox.protect import read_protect_inventory

    denied = dict(INVENTORY, nvrs=httpx.Response(403, json={}))

    with pytest.raises(InventoryError, match="denied"):
        read_protect_inventory(CONFIG, transport=transport(denied))
    with pytest.raises(InventoryError):
        read_protect_inventory(ProtectConfig())
