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
