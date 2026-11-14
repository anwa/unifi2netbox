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
