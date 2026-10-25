import ssl

import httpx
import pytest

from unifi2netbox.config import UniFiConfig
from unifi2netbox.netbox import ConnectionState
from unifi2netbox.unifi import check_connection

SITE_ID = "11111111-1111-4111-8111-111111111111"
SECOND_ID = "22222222-2222-4222-8222-222222222222"


def page(rows, *, offset=0, total=None, limit=200):
    return {
        "offset": offset,
        "limit": limit,
        "count": len(rows),
        "totalCount": len(rows) if total is None else total,
        "data": rows,
    }


def site(identifier=SITE_ID, name="Default", reference="default"):
    return {"id": identifier, "name": name, "internalReference": reference}


@pytest.fixture
def api():
    calls = []
    responses = [
        httpx.Response(200, json={"applicationVersion": "10.6.100"}),
        httpx.Response(200, json=page([site()])),
        httpx.Response(200, json=page([], limit=1)),
    ]

    def handle(request):
        calls.append(request)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return calls, responses, httpx.MockTransport(handle)


def configured(**kwargs):
    return UniFiConfig("https://console.invalid", "synthetic-local-key", **kwargs)


def test_online_checks_local_info_site_and_inventory(api):
    calls, _, transport = api
    result = check_connection(configured(timeout=3), transport=transport)
    assert result.state == ConnectionState.ONLINE
    assert result.version == "10.6.100"
    assert SITE_ID in result.site
    assert result.sites == ((SITE_ID, "Default"),)
    assert [request.url.path for request in calls] == [
        "/proxy/network/integration/v1/info",
        "/proxy/network/integration/v1/sites",
        f"/proxy/network/integration/v1/sites/{SITE_ID}/devices",
    ]
    for request in calls:
        assert request.method == "GET"
        assert request.headers["X-API-KEY"] == "synthetic-local-key"
        assert request.extensions["timeout"]["read"] == 3
    assert calls[-1].url.params["limit"] == "1"


def test_unconfigured_does_not_contact_console(api):
    assert (
        check_connection(UniFiConfig(), transport=api[2]).state
        == ConnectionState.UNCONFIGURED
    )
    assert not api[0]


@pytest.mark.parametrize("selected", [SITE_ID, "Default", "default"])
def test_explicit_site_selection(api, selected):
    assert (
        check_connection(configured(site=selected), transport=api[2]).state
        == ConnectionState.ONLINE
    )


def test_multiple_sites_require_explicit_choice(api):
    api[1][1] = httpx.Response(
        200, json=page([site(), site(SECOND_ID, "Other", "other")])
    )
    result = check_connection(configured(), transport=api[2])
    assert result.state == ConnectionState.UNCONFIGURED
    assert len(result.sites) == 2
    assert len(api[0]) == 2


def test_missing_or_duplicate_site_name_is_not_chosen(api):
    api[1][1] = httpx.Response(200, json=page([site(), site(SECOND_ID)]))
    assert (
        check_connection(configured(site="Default"), transport=api[2]).state
        == ConnectionState.UNCONFIGURED
    )


def test_no_accessible_sites_is_partial(api):
    api[1][1] = httpx.Response(200, json=page([]))
    assert (
        check_connection(configured(), transport=api[2]).state
        == ConnectionState.PARTIAL
    )


def test_site_pagination_is_followed(api):
    api[1][1] = httpx.Response(200, json=page([site()], total=2, limit=1))
    api[1].insert(
        2,
        httpx.Response(
            200,
            json=page([site(SECOND_ID, "Other", "other")], offset=1, total=2, limit=1),
        ),
    )
    result = check_connection(configured(site=SITE_ID), transport=api[2])
    assert result.state == ConnectionState.ONLINE
    assert api[0][2].url.params["offset"] == "1"


@pytest.mark.parametrize(
    ("code", "state"),
    [
        (401, ConnectionState.UNAUTHORIZED),
        (403, ConnectionState.UNAUTHORIZED),
        (404, ConnectionState.UNSUPPORTED),
        (405, ConnectionState.UNSUPPORTED),
        (302, ConnectionState.ERROR),
        (429, ConnectionState.ERROR),
        (502, ConnectionState.ERROR),
    ],
)
def test_failed_device_read_never_reports_online(api, code, state):
    api[1][2] = httpx.Response(
        code,
        json={"error": "synthetic-local-key"},
        headers={"Location": "https://other.invalid"},
    )
    result = check_connection(configured(), transport=api[2])
    assert result.state == state
    assert "synthetic-local-key" not in result.message
    assert len(api[0]) == 3


@pytest.mark.parametrize(
    "data", [{}, [], {"applicationVersion": 42}, {"applicationVersion": "secret"}]
)
def test_invalid_info_is_sanitized(api, data):
    api[1][0] = httpx.Response(200, json=data)
    assert (
        check_connection(configured(), transport=api[2]).state == ConnectionState.ERROR
    )


def test_unvalidated_version_is_explicitly_unsupported(api):
    api[1][0] = httpx.Response(200, json={"applicationVersion": "11.0.0"})
    assert (
        check_connection(configured(), transport=api[2]).state
        == ConnectionState.UNSUPPORTED
    )
    assert len(api[0]) == 1


@pytest.mark.parametrize(
    "data",
    [
        [],
        {},
        page([], total=1),
        {**page([]), "offset": True},
        page([{"id": "../escape"}]),
    ],
)
def test_bad_site_page_is_not_online(api, data):
    api[1][1] = httpx.Response(200, json=data)
    assert (
        check_connection(configured(), transport=api[2]).state == ConnectionState.ERROR
    )


def test_timeout_is_offline(api):
    api[1][0] = httpx.ReadTimeout("synthetic-local-key")
    result = check_connection(configured(), transport=api[2])
    assert result.state == ConnectionState.OFFLINE
    assert "synthetic-local-key" not in result.message


def test_tls_failure_is_distinct_from_connection_refusal(api):
    def handle(request):
        raise httpx.ConnectError("private error", request=request) from ssl.SSLError(
            "private CA"
        )

    result = check_connection(configured(), transport=httpx.MockTransport(handle))
    assert result.state == ConnectionState.TLS_ERROR
    api[1][0] = httpx.ConnectError("private host")
    assert (
        check_connection(configured(), transport=api[2]).state
        == ConnectionState.OFFLINE
    )


@pytest.mark.parametrize("verify_tls", [True, False])
def test_tls_preferences_and_direct_connection_are_explicit(
    api, monkeypatch, verify_tls
):
    captured = []
    client_type = httpx.Client

    def create_client(**kwargs):
        captured.append(kwargs)
        return client_type(**kwargs)

    monkeypatch.setattr("unifi2netbox.unifi.httpx.Client", create_client)
    assert (
        check_connection(configured(verify_tls=verify_tls), transport=api[2]).state
        == ConnectionState.ONLINE
    )
    assert captured[0]["verify"] is verify_tls
    assert captured[0]["follow_redirects"] is False
    assert captured[0]["trust_env"] is False


def test_private_ca_is_loaded(api, tmp_path, monkeypatch):
    path = tmp_path / "ca.pem"
    path.write_text("synthetic certificate fixture")
    loaded = []
    context = ssl.create_default_context()

    def create_context(*, cafile):
        loaded.append(cafile)
        return context

    monkeypatch.setattr("unifi2netbox.unifi.ssl.create_default_context", create_context)
    result = check_connection(configured(ca_bundle=str(path)), transport=api[2])
    assert result.state == ConnectionState.ONLINE
    assert loaded == [str(path)]


def test_site_discovery_has_a_fixed_page_limit():
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path.endswith("/info"):
            return httpx.Response(200, json={"applicationVersion": "10.6.100"})
        offset = int(request.url.params["offset"])
        identifier = f"00000000-0000-4000-8000-{offset:012d}"
        return httpx.Response(
            200, json=page([site(identifier)], offset=offset, total=11, limit=1)
        )

    result = check_connection(configured(), transport=httpx.MockTransport(handle))
    assert result.state == ConnectionState.PARTIAL
    assert len(calls) == 11
