import json
from datetime import UTC, datetime

import httpx
import pytest
import requests

from unifi2netbox.config import NetBoxConfig, UniFiConfig
from unifi2netbox.inventory import (
    InventoryError,
    InventorySource,
    read_netbox_inventory,
    read_unifi_inventory,
)

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


@pytest.fixture
def netbox_transport(monkeypatch):
    calls = []
    responses = [
        (200, {"netbox-version": "4.7.3"}),
        (
            200,
            {
                "count": 2,
                "next": "https://netbox.invalid/api/dcim/devices/?limit=1&offset=1",
                "previous": None,
                "results": [
                    {
                        "id": 7,
                        "name": "edge-a",
                        "serial": " abcd1234 ",
                        "primary_mac_address": "00-11-22-33-44-55",
                        "device_type": {
                            "model": "USW-24",
                            "manufacturer": {"name": "Ubiquiti"},
                        },
                        "site": {"name": "HQ"},
                    }
                ],
            },
        ),
        (
            200,
            {
                "count": 2,
                "next": None,
                "previous": "https://netbox.invalid/api/dcim/devices/?limit=1&offset=0",
                "results": [
                    {
                        "id": 8,
                        "name": "edge-b",
                        "serial": "xyz",
                        "primary_mac_address": "66:55:44:33:22:11",
                        "device_type": {
                            "model": "U7-Pro",
                            "manufacturer": {"name": "Ubiquiti"},
                        },
                        "site": {"name": "HQ"},
                    }
                ],
            },
        ),
    ]

    def send(session, request, **kwargs):
        calls.append((request, kwargs))
        code, payload = responses.pop(0)
        response = requests.Response()
        response.status_code = code
        response._content = json.dumps(payload).encode()
        response.headers["Content-Type"] = "application/json"
        response.request = request
        response.url = request.url
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    return calls, responses


@pytest.fixture
def unifi_api():
    calls = []
    responses = [
        httpx.Response(200, json={"applicationVersion": "10.6.100"}),
        httpx.Response(
            200,
            json=page(
                [
                    {
                        "id": SITE_ID,
                        "name": "Default",
                        "internalReference": "default",
                    },
                    {
                        "id": SECOND_ID,
                        "name": "Other",
                        "internalReference": "other",
                    },
                ],
                total=2,
                limit=200,
            ),
        ),
        httpx.Response(
            200,
            json=page(
                [
                    {
                        "id": "dev-1",
                        "name": "switch-1",
                        "model": "USW-24",
                        "serial": "abc123",
                        "macAddress": "001122334455",
                    }
                ],
                total=2,
                limit=1,
            ),
        ),
        httpx.Response(
            200,
            json=page(
                [
                    {
                        "id": "dev-2",
                        "hostname": "ap-2",
                        "model": "U7-Pro",
                        "serial": "def456",
                        "mac": "66:55:44:33:22:11",
                    }
                ],
                offset=1,
                total=2,
                limit=1,
            ),
        ),
    ]

    def handle(request):
        calls.append(request)
        return responses.pop(0)

    return calls, responses, httpx.MockTransport(handle)


def test_netbox_inventory_is_paginated_and_normalized(netbox_transport):
    captured_at = datetime(2026, 10, 28, 12, 30, 0, tzinfo=UTC)
    snapshot = read_netbox_inventory(
        NetBoxConfig("https://netbox.invalid", "synthetic-token"),
        page_size=1,
        captured_at=captured_at,
    )
    calls, _ = netbox_transport

    assert snapshot.source == InventorySource.NETBOX
    assert snapshot.source_version == "4.7.3"
    assert snapshot.captured_at == "2026-10-28T12:30:00+00:00"
    assert [device.source_id for device in snapshot.devices] == ["7", "8"]
    assert snapshot.devices[0].serial == "ABCD1234"
    assert snapshot.devices[0].mac_address == "00:11:22:33:44:55"
    assert snapshot.devices[0].manufacturer == "Ubiquiti"
    assert snapshot.devices[1].name == "edge-b"

    for request, options in calls:
        assert request.method == "GET"
        assert options["timeout"] == (10.0, 10.0)
        assert options["allow_redirects"] is False


def test_netbox_inventory_page_limit_is_bounded(netbox_transport):
    with pytest.raises(InventoryError, match="page safety limit"):
        read_netbox_inventory(
            NetBoxConfig("https://netbox.invalid", "synthetic-token"),
            page_size=1,
            max_pages=1,
        )


def test_unifi_inventory_is_paginated_and_normalized(unifi_api):
    calls, _, transport = unifi_api
    captured_at = datetime(2026, 10, 28, 13, 0, 0, tzinfo=UTC)
    snapshot = read_unifi_inventory(
        UniFiConfig("https://console.invalid", "synthetic-key", site=SITE_ID),
        page_size=1,
        captured_at=captured_at,
        transport=transport,
    )

    assert snapshot.source == InventorySource.UNIFI_NETWORK
    assert snapshot.source_version == "10.6.100"
    assert snapshot.scope == f"Default ({SITE_ID})"
    assert snapshot.captured_at == "2026-10-28T13:00:00+00:00"
    assert [device.source_id for device in snapshot.devices] == ["dev-1", "dev-2"]
    assert snapshot.devices[0].serial == "ABC123"
    assert snapshot.devices[0].mac_address == "00:11:22:33:44:55"
    assert snapshot.devices[1].name == "ap-2"
    assert snapshot.devices[1].mac_address == "66:55:44:33:22:11"

    assert [request.url.path for request in calls] == [
        "/proxy/network/integration/v1/info",
        "/proxy/network/integration/v1/sites",
        f"/proxy/network/integration/v1/sites/{SITE_ID}/devices",
        f"/proxy/network/integration/v1/sites/{SITE_ID}/devices",
    ]


def test_unifi_inventory_requires_explicit_site_for_multiple_sites(unifi_api):
    with pytest.raises(InventoryError, match="Choose one accessible site"):
        read_unifi_inventory(
            UniFiConfig("https://console.invalid", "synthetic-key"),
            transport=unifi_api[2],
        )


def test_unifi_inventory_rejects_bad_pagination(unifi_api):
    unifi_api[1][2] = httpx.Response(
        200,
        json={
            "offset": 0,
            "limit": 1,
            "count": 2,
            "totalCount": 2,
            "data": [{"id": "dev-1"}],
        },
    )
    with pytest.raises(InventoryError, match="pagination metadata"):
        read_unifi_inventory(
            UniFiConfig("https://console.invalid", "synthetic-key", site=SITE_ID),
            page_size=1,
            transport=unifi_api[2],
        )
