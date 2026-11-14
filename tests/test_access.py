"""Access connection check against synthetic transports."""

import httpx
import pytest

from unifi2netbox.access import check_access_connection, flatten_devices
from unifi2netbox.config import AccessConfig, ConfigError
from unifi2netbox.netbox import ConnectionState

CONFIG = AccessConfig("https://udm.invalid:12445", "synthetic-token")


def envelope(data, code="SUCCESS"):
    return {"code": code, "msg": "success", "data": data}


def transport(response, seen=None):
    def handle(request):
        assert request.method == "GET"
        if seen is not None:
            seen.append((request.url.path, request.headers.get("Authorization")))
        if isinstance(response, httpx.Response):
            return response
        return httpx.Response(200, json=response)

    return httpx.MockTransport(handle)


def test_online_reads_devices_with_the_bearer_token():
    seen = []
    data = [[{"id": "hub"}, {"id": "reader"}], [{"id": "intercom"}]]

    result = check_access_connection(CONFIG, transport=transport(envelope(data), seen))

    assert result.state == ConnectionState.ONLINE
    assert "3 devices" in result.message
    assert seen == [("/api/v1/developer/devices", "Bearer synthetic-token")]


def test_unconfigured_is_optional_and_never_contacts_a_console():
    def refuse(request):
        raise AssertionError("no request expected")

    result = check_access_connection(
        AccessConfig(), transport=httpx.MockTransport(refuse)
    )

    assert result.state == ConnectionState.UNCONFIGURED
    assert result.message.startswith("Optional.")


@pytest.mark.parametrize(
    ("response", "state"),
    [
        (httpx.Response(401, json={"code": "CODE_UNAUTHORIZED"}), "Unauthorized"),
        (httpx.Response(403, json={}), "Unauthorized"),
        (httpx.Response(404, json={}), "Unsupported"),
        (
            httpx.Response(200, text="<html>", headers={"content-type": "text/html"}),
            "Unsupported",
        ),
        (httpx.Response(302, headers={"location": "/login"}), "Error"),
        (httpx.Response(500, json={}), "Error"),
        (envelope([], code="CODE_AUTH_FAILED"), "Unauthorized"),
        (envelope([], code="CODE_SYSTEM_ERROR"), "Error"),
        (envelope({"not": "a list"}), "Error"),
        (["not an envelope"], "Error"),
    ],
)
def test_failed_reads_are_never_online(response, state):
    result = check_access_connection(CONFIG, transport=transport(response))

    assert result.state == state
    assert "synthetic-token" not in result.message


def test_timeout_is_offline():
    def handle(request):
        raise httpx.ReadTimeout("slow", request=request)

    result = check_access_connection(CONFIG, transport=httpx.MockTransport(handle))

    assert result.state == ConnectionState.OFFLINE


def test_flatten_devices_accepts_grouped_and_flat_lists():
    assert flatten_devices([[{"id": 1}], {"id": 2}]) == [{"id": 1}, {"id": 2}]
    with pytest.raises(ValueError):
        flatten_devices([1])


def test_access_config_rejects_api_paths():
    with pytest.raises(ConfigError):
        AccessConfig("https://udm.invalid:12445/api/v1/developer", "t")


def device(**overrides):
    row = {
        "id": "a1b2c3d4e5f6",
        "name": "UA-Hub",
        "alias": "",
        "type": "UAH",
        "is_adopted": True,
        "is_online": True,
        "capabilities": ["is_hub"],
        "location_id": "loc",
    }
    row.update(overrides)
    return row


def test_inventory_keeps_identity_fields_and_derives_the_mac():
    from unifi2netbox.access import read_access_inventory
    from unifi2netbox.inventory import InventorySource

    seen = []
    rows = [
        [
            device(),
            device(
                id="0a0b0c0d0e0f",
                name="Default",
                alias="Front door",
                type="UA-Intercom",
                is_online=False,
                capabilities=["is_reader"],
            ),
            device(id="aabbccddeeff", type="UA-G2-Pro", capabilities=["is_reader"]),
            device(id="not-a-mac", type="UA-Lock", capabilities=[]),
            device(id="112233445566", is_adopted=False),
        ]
    ]

    snapshot = read_access_inventory(CONFIG, transport=transport(envelope(rows), seen))

    assert snapshot.source == InventorySource.UNIFI_ACCESS
    assert seen == [("/api/v1/developer/devices", "Bearer synthetic-token")]
    hub, intercom, reader, other = snapshot.devices
    assert (hub.name, hub.model, hub.kind, hub.state) == (
        "UA-Hub",
        "UAH",
        "hub",
        "online",
    )
    assert hub.mac_address == "A1:B2:C3:D4:E5:F6"
    assert hub.manufacturer == "Ubiquiti"
    assert (intercom.name, intercom.kind, intercom.state) == (
        "Front door",
        "intercom",
        "offline",
    )
    assert reader.kind == "reader"
    assert (other.kind, other.mac_address) == ("access", "")


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        ([[{"id": "same"}, {"id": "same"}]], "duplicate"),
        ([[{"name": "no id"}]], "malformed"),
        ({"not": "a list"}, "transport"),
    ],
)
def test_inventory_rejects_malformed_answers(data, fragment):
    from unifi2netbox.access import read_access_inventory
    from unifi2netbox.inventory import InventoryError

    with pytest.raises(InventoryError, match=fragment):
        read_access_inventory(CONFIG, transport=transport(envelope(data)))


def test_unconfigured_inventory_is_refused_without_requests():
    from unifi2netbox.access import read_access_inventory
    from unifi2netbox.inventory import InventoryError

    def refuse(request):
        raise AssertionError("no request expected")

    with pytest.raises(InventoryError):
        read_access_inventory(AccessConfig(), transport=httpx.MockTransport(refuse))


def test_rejection_without_a_port_points_to_12445():
    from unifi2netbox.access import read_access_inventory
    from unifi2netbox.inventory import InventoryError

    rejected = httpx.Response(401, json={})
    no_port = AccessConfig("https://udm.invalid", "synthetic-token")

    check = check_access_connection(no_port, transport=transport(rejected))
    with_port = check_access_connection(CONFIG, transport=transport(rejected))
    missing = check_access_connection(
        no_port, transport=transport(httpx.Response(404, json={}))
    )

    assert "port 12445" in check.message
    assert "port 12445" not in with_port.message
    assert "no port" not in missing.message
    with pytest.raises(InventoryError, match="12445"):
        read_access_inventory(no_port, transport=transport(rejected))
