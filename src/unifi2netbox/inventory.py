import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

import httpx
import requests

from unifi2netbox.config import NetBoxConfig, UniFiConfig
from unifi2netbox.netbox import ReadOnlySession, RedirectError


class InventorySource(StrEnum):
    NETBOX = "netbox"
    UNIFI_NETWORK = "unifi_network"


class InventoryError(ValueError):
    pass


@dataclass(frozen=True)
class InventoryDevice:
    source_id: str
    name: str
    serial: str = ""
    model: str = ""
    manufacturer: str = ""
    mac_address: str = ""
    site: str = ""


@dataclass(frozen=True)
class InventorySnapshot:
    source: InventorySource
    captured_at: str
    source_version: str = ""
    scope: str = ""
    devices: tuple[InventoryDevice, ...] = ()


def _text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _timestamp(captured_at: datetime | None) -> str:
    if captured_at is None:
        captured_at = datetime.now(UTC)
    return captured_at.astimezone(UTC).isoformat(timespec="seconds")


def _normalize_mac(value: object) -> str:
    text = "".join(character for character in _text(value) if character.isalnum())
    if len(text) != 12:
        return _text(value)
    return ":".join(text[index : index + 2] for index in range(0, 12, 2)).upper()


def _netbox_json(
    session: requests.Session, config: NetBoxConfig, path: str
) -> dict[str, object]:
    response = session.get(
        f"{config.url.rstrip('/')}{path}",
        headers={"Authorization": f"Token {config.token}"},
    )
    if response.status_code in {401, 403}:
        raise InventoryError("Authentication or device-read permission was denied.")
    if response.status_code != 200:
        raise InventoryError(f"NetBox returned HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as error:
        raise InventoryError("NetBox returned malformed JSON.") from error
    if not isinstance(payload, dict):
        raise InventoryError("NetBox returned an unsupported JSON shape.")
    return payload


def _normalize_netbox_device(row: dict[str, object]) -> InventoryDevice:
    device_type = row.get("device_type")
    manufacturer = ""
    model = ""
    if isinstance(device_type, dict):
        model = _text(device_type.get("model"))
        vendor = device_type.get("manufacturer")
        if isinstance(vendor, dict):
            manufacturer = _text(vendor.get("name"))

    site = ""
    site_value = row.get("site")
    if isinstance(site_value, dict):
        site = _text(site_value.get("name"))

    return InventoryDevice(
        source_id=str(row.get("id", "")).strip(),
        name=_text(row.get("name")),
        serial=_text(row.get("serial")).upper(),
        model=model,
        manufacturer=manufacturer,
        mac_address=_normalize_mac(row.get("primary_mac_address")),
        site=site,
    )


def read_netbox_inventory(
    config: NetBoxConfig,
    *,
    page_size: int = 200,
    max_pages: int = 50,
    captured_at: datetime | None = None,
) -> InventorySnapshot:
    if not config.configured:
        raise InventoryError("Set a NetBox URL and API token.")
    if page_size < 1 or max_pages < 1:
        raise InventoryError("Pagination bounds must be positive.")

    devices: list[InventoryDevice] = []
    offset = 0
    pages = 0
    version = ""
    try:
        with ReadOnlySession(config) as session:
            status = _netbox_json(session, config, "/api/status/")
            version = _text(status.get("netbox-version"))
            while pages < max_pages:
                payload = _netbox_json(
                    session,
                    config,
                    f"/api/dcim/devices/?limit={page_size}&offset={offset}",
                )
                count = payload.get("count")
                rows = payload.get("results")
                if (
                    type(count) is not int
                    or count < 0
                    or not isinstance(rows, list)
                    or not all(isinstance(row, dict) for row in rows)
                    or len(rows) > page_size
                    or offset + len(rows) > count
                ):
                    raise InventoryError(
                        "NetBox returned an invalid paginated payload."
                    )
                devices.extend(_normalize_netbox_device(row) for row in rows)
                pages += 1
                if offset + len(rows) >= count:
                    break
                if not rows:
                    raise InventoryError(
                        "NetBox pagination stopped unexpectedly before count was "
                        "reached."
                    )
                offset += len(rows)
            else:
                raise InventoryError(
                    "NetBox pagination exceeded the configured page safety limit."
                )
    except RedirectError as error:
        raise InventoryError(
            "Redirect refused. Configure the final NetBox URL explicitly."
        ) from error
    except requests.exceptions.RequestException as error:
        raise InventoryError(
            "NetBox inventory read failed due to transport errors."
        ) from error

    return InventorySnapshot(
        source=InventorySource.NETBOX,
        captured_at=_timestamp(captured_at),
        source_version=version,
        devices=tuple(devices),
    )


def _unifi_json(client: httpx.Client, path: str, **params) -> dict[str, object]:
    response = client.get(path, params=params)
    if 300 <= response.status_code < 400:
        raise InventoryError("Redirect refused. Configure the final console URL.")
    if response.status_code in {401, 403}:
        raise InventoryError("Local API key or inventory permission was denied.")
    if response.status_code in {404, 405}:
        raise InventoryError(
            "A required local Network Integration API endpoint is unavailable."
        )
    if response.status_code != 200:
        raise InventoryError(f"UniFi returned HTTP {response.status_code}.")
    payload = response.json()
    if not isinstance(payload, dict):
        raise InventoryError("UniFi returned an unsupported JSON shape.")
    return payload


def _unifi_page(
    data: dict[str, object], offset: int, requested_limit: int
) -> list[dict]:
    rows = data.get("data")
    values = [
        data.get("offset"),
        data.get("limit"),
        data.get("count"),
        data.get("totalCount"),
    ]
    if (
        any(type(value) is not int or value < 0 for value in values)
        or not isinstance(rows, list)
        or not all(isinstance(row, dict) for row in rows)
    ):
        raise InventoryError("UniFi returned an invalid paginated payload.")
    if (
        data["offset"] != offset
        or not 0 < data["limit"] <= requested_limit
        or data["count"] != len(rows)
        or len(rows) > data["limit"]
        or data["totalCount"] < offset + len(rows)
    ):
        raise InventoryError("UniFi returned inconsistent pagination metadata.")
    if not rows and data["totalCount"] > offset:
        raise InventoryError("UniFi pagination ended unexpectedly before totalCount.")
    return rows


def _select_site(config: UniFiConfig, sites: list[dict[str, str]]) -> dict[str, str]:
    selected = [
        site
        for site in sites
        if config.site.strip() in {site["id"], site["name"], site["internalReference"]}
    ]
    if not config.site.strip() and len(sites) == 1:
        selected = sites
    if len(selected) != 1:
        raise InventoryError(
            "Choose one accessible site by ID, name or internal reference in "
            "UniFi settings."
        )
    return selected[0]


def _normalize_unifi_device(row: dict[str, object], site_name: str) -> InventoryDevice:
    return InventoryDevice(
        source_id=_text(row.get("id")) or _text(row.get("_id")),
        name=_text(row.get("name")) or _text(row.get("hostname")),
        serial=_text(row.get("serial")).upper(),
        model=_text(row.get("model")),
        mac_address=_normalize_mac(row.get("macAddress") or row.get("mac")),
        site=site_name,
    )


def read_unifi_inventory(
    config: UniFiConfig,
    *,
    page_size: int = 200,
    max_pages: int = 50,
    captured_at: datetime | None = None,
    transport: httpx.BaseTransport | None = None,
) -> InventorySnapshot:
    if not config.configured:
        raise InventoryError("Set a UniFi console URL and local API key.")
    if page_size < 1 or max_pages < 1:
        raise InventoryError("Pagination bounds must be positive.")

    verify: bool | ssl.SSLContext = config.verify_tls
    if config.verify_tls and config.ca_bundle:
        verify = ssl.create_default_context(cafile=config.ca_bundle)

    site_scope = ""
    version = ""
    devices: list[InventoryDevice] = []
    try:
        with httpx.Client(
            base_url=config.url.rstrip("/") + "/proxy/network/integration/v1/",
            headers={"X-API-KEY": config.token, "Accept": "application/json"},
            verify=verify,
            timeout=httpx.Timeout(config.timeout),
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
            transport=transport,
        ) as client:
            info = _unifi_json(client, "info")
            version = _text(info.get("applicationVersion"))

            sites: list[dict[str, str]] = []
            seen_sites: set[str] = set()
            for _ in range(max_pages):
                offset = len(sites)
                site_payload = _unifi_json(client, "sites", offset=offset, limit=200)
                rows = _unifi_page(site_payload, offset, 200)
                for row in rows:
                    site_id = _text(row.get("id"))
                    name = _text(row.get("name"))
                    reference = _text(row.get("internalReference"))
                    if not site_id or not name or not reference:
                        raise InventoryError("UniFi returned malformed site entries.")
                    if site_id in seen_sites:
                        raise InventoryError("UniFi returned duplicate site IDs.")
                    seen_sites.add(site_id)
                    sites.append(
                        {"id": site_id, "name": name, "internalReference": reference}
                    )
                if len(sites) >= site_payload["totalCount"]:
                    break
            else:
                raise InventoryError(
                    "UniFi site discovery exceeded the configured page safety limit."
                )

            site = _select_site(config, sites)
            site_scope = f"{site['name']} ({site['id']})"
            for page_index in range(max_pages):
                offset = page_index * page_size
                payload = _unifi_json(
                    client,
                    f"sites/{site['id']}/devices",
                    offset=offset,
                    limit=page_size,
                )
                rows = _unifi_page(payload, offset, page_size)
                devices.extend(
                    _normalize_unifi_device(row, site["name"]) for row in rows
                )
                if offset + len(rows) >= payload["totalCount"]:
                    break
            else:
                raise InventoryError(
                    "UniFi device pagination exceeded the configured page safety limit."
                )
    except InventoryError:
        raise
    except (httpx.HTTPError, OSError, ValueError, TypeError) as error:
        raise InventoryError(
            "UniFi inventory read failed due to transport errors."
        ) from error

    return InventorySnapshot(
        source=InventorySource.UNIFI_NETWORK,
        captured_at=_timestamp(captured_at),
        source_version=version,
        scope=site_scope,
        devices=tuple(devices),
    )
