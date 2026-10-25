import json

import pytest
import requests

from unifi2netbox.config import NetBoxConfig
from unifi2netbox.netbox import ConnectionState, ReadOnlySession, check_connection


@pytest.fixture
def transport(monkeypatch):
    calls = []
    responses = [
        (200, {"netbox-version": "4.7.3"}),
        (200, {"count": 0, "next": None, "previous": None, "results": []}),
    ]

    def send(session, request, **kwargs):
        calls.append((request, kwargs))
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        code, payload = item
        response = requests.Response()
        response.status_code = code
        response._content = json.dumps(payload).encode()
        response.headers["Content-Type"] = "application/json"
        response.request = request
        response.url = request.url
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    return calls, responses


def configured():
    return NetBoxConfig("https://netbox.invalid", "synthetic-token", timeout=3)


def test_online_requires_authenticated_inventory_read(transport):
    calls, _ = transport
    result = check_connection(configured())
    assert result.state == ConnectionState.ONLINE
    assert result.version == "4.7.3"
    assert len(calls) == 2
    assert "/api/dcim/devices/" in calls[1][0].url
    for request, options in calls:
        assert request.method == "GET"
        assert "synthetic-token" in request.headers["Authorization"]
        assert options["timeout"] == (3, 3)
        assert options["allow_redirects"] is False
        assert options["verify"] is True


def test_unconfigured_makes_no_calls(transport):
    assert check_connection(NetBoxConfig()).state == ConnectionState.UNCONFIGURED
    assert not transport[0]


@pytest.mark.parametrize("code", [401, 403])
def test_inventory_permissions_are_required(transport, code):
    transport[1][1] = (code, {"detail": "synthetic-token must not be echoed"})
    result = check_connection(configured())
    assert result.state == ConnectionState.UNAUTHORIZED
    assert "synthetic-token" not in result.message


@pytest.mark.parametrize(
    ("failure", "state"),
    [
        (requests.exceptions.SSLError("secret"), ConnectionState.TLS_ERROR),
        (requests.exceptions.Timeout("secret"), ConnectionState.OFFLINE),
        (requests.exceptions.ConnectionError("secret"), ConnectionState.OFFLINE),
    ],
)
def test_transport_errors_are_sanitized(transport, failure, state):
    transport[1][0] = failure
    result = check_connection(configured())
    assert result.state == state
    assert "secret" not in result.message


def test_redirect_is_not_followed(transport):
    transport[1][0] = (302, {})
    assert check_connection(configured()).state == ConnectionState.ERROR
    assert len(transport[0]) == 1


def test_unsupported_version(transport):
    transport[1][0] = (200, {"netbox-version": "5.0.0"})
    assert check_connection(configured()).state == ConnectionState.UNSUPPORTED
    assert len(transport[0]) == 1


@pytest.mark.parametrize("payload", [{}, [], {"netbox-version": "secret"}])
def test_malformed_status_is_not_online(transport, payload):
    transport[1][0] = (200, payload)
    assert check_connection(configured()).state == ConnectionState.ERROR


def test_tls_configuration_reaches_transport(transport, tmp_path):
    bundle = tmp_path / "ca.pem"
    bundle.write_text("synthetic certificate fixture")
    check_connection(
        NetBoxConfig("https://netbox.invalid", "test", ca_bundle=str(bundle))
    )
    assert transport[0][0][1]["verify"] == str(bundle)
    transport[1].extend(
        [(200, {"netbox-version": "4.7.3"}), (200, {"results": [], "next": None})]
    )
    check_connection(NetBoxConfig("https://netbox.invalid", "test", False))
    assert transport[0][-1][1]["verify"] is False


def test_read_only_session_blocks_writes():
    with ReadOnlySession(configured()) as session:
        with pytest.raises(ValueError, match="read-only"):
            session.post("https://netbox.invalid")
