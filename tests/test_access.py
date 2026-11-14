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
