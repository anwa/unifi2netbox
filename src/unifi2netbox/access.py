"""Connection check for the UniFi Access API (read-only).

UniFi Access serves its developer API on its own port (12445) of the console
running Access and needs an Access API token created in the Access app; the
Network key is not accepted. Requests are GET only, never follow redirects
and ignore proxy environment variables. The app only reads devices, even when
the token itself would allow more (users, logs, door control).
"""

import re
import ssl
from datetime import datetime

import httpx

from unifi2netbox.config import AccessConfig
from unifi2netbox.inventory import (
    InventoryDevice,
    InventoryError,
    InventorySnapshot,
    InventorySource,
    _normalize_mac,
    _text,
    _timestamp,
)
from unifi2netbox.netbox import ConnectionResult, ConnectionState
from unifi2netbox.unifi import _tls_failure

API_PATH = "/api/v1/developer/"
ACCESS_PORT = 12445
PORT_HINT = f" The URL has no port; the Access API listens on port {ACCESS_PORT}."

HUB = "hub"
READER = "reader"
INTERCOM = "intercom"
OTHER = "access"


class _Failure(Exception):
    def __init__(self, state: ConnectionState, message: str) -> None:
        self.state = state
        self.message = message
        super().__init__(message)


def access_client(
    config: AccessConfig, *, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    """HTTP client for the Access developer API with the safe defaults."""
    verify: bool | ssl.SSLContext = config.verify_tls
    if config.verify_tls and config.ca_bundle:
        verify = ssl.create_default_context(cafile=config.ca_bundle)
    return httpx.Client(
        base_url=config.url.rstrip("/") + API_PATH,
        headers={
            "Authorization": f"Bearer {config.token}",
            "Accept": "application/json",
        },
        verify=verify,
        timeout=httpx.Timeout(config.timeout),
        follow_redirects=False,
        trust_env=False,
        limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        transport=transport,
    )


def access_data(client: httpx.Client, path: str) -> object:
    """One GET; returns ``data`` of a successful Access envelope."""
    response = client.get(path)
    code = response.status_code
    if 300 <= code < 400:
        raise _Failure(
            ConnectionState.ERROR, "Redirect refused. Configure the final API URL."
        )
    if code in {401, 403}:
        raise _Failure(
            ConnectionState.UNAUTHORIZED,
            "The Access API token was rejected or lacks device-read permission.",
        )
    if code in {404, 405} or "html" in response.headers.get("content-type", ""):
        raise _Failure(
            ConnectionState.UNSUPPORTED,
            "No UniFi Access API answers on this URL. Use the console running "
            "Access with port 12445.",
        )
    if code != 200:
        raise _Failure(ConnectionState.ERROR, f"UniFi Access returned HTTP {code}.")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError
    if payload.get("code") != "SUCCESS":
        result = str(payload.get("code") or "")
        if "AUTH" in result.upper() or "TOKEN" in result.upper():
            raise _Failure(
                ConnectionState.UNAUTHORIZED,
                "The Access API token was rejected or lacks device-read permission.",
            )
        raise _Failure(ConnectionState.ERROR, "UniFi Access reported an error.")
    return payload.get("data")


def flatten_devices(data: object) -> list[dict]:
    """Access groups devices per hub as nested lists; return one flat list."""
    if not isinstance(data, list):
        raise ValueError
    devices: list[dict] = []
    for item in data:
        if isinstance(item, list):
            devices.extend(entry for entry in item if isinstance(entry, dict))
        elif isinstance(item, dict):
            devices.append(item)
        else:
            raise ValueError
    return devices


def check_access_connection(
    config: AccessConfig, *, transport: httpx.BaseTransport | None = None
) -> ConnectionResult:
    if not config.configured:
        return ConnectionResult(
            ConnectionState.UNCONFIGURED,
            "Optional. Set the Access API URL (port 12445) and an Access API token.",
        )
    try:
        with access_client(config, transport=transport) as client:
            devices = flatten_devices(access_data(client, "devices"))
            count = len(devices)
            return ConnectionResult(
                ConnectionState.ONLINE,
                "Authenticated device-read access succeeded "
                f"({count} device{'s' if count != 1 else ''}).",
            )
    except _Failure as error:
        return ConnectionResult(error.state, _with_port_hint(config, error))
    except httpx.TimeoutException:
        return ConnectionResult(ConnectionState.OFFLINE, "The API request timed out.")
    except (httpx.ConnectError, ssl.SSLError) as error:
        if _tls_failure(error):
            return ConnectionResult(
                ConnectionState.TLS_ERROR,
                "TLS validation failed. Check the certificate and CA settings.",
            )
        return ConnectionResult(
            ConnectionState.OFFLINE, "Cannot connect to the configured Access API."
        )
    except OSError:
        return ConnectionResult(
            ConnectionState.TLS_ERROR, "Cannot load the configured CA bundle."
        )
    except httpx.HTTPError, ValueError, TypeError, UnicodeError:
        return ConnectionResult(
            ConnectionState.ERROR,
            "The server did not return a supported UniFi Access API response.",
        )


def _with_port_hint(config: AccessConfig, error: _Failure) -> str:
    """A rejected request without an explicit port usually hit UniFi OS on 443."""
    if error.state != ConnectionState.UNAUTHORIZED:
        return error.message
    try:
        port = httpx.URL(config.url).port
    except httpx.InvalidURL:
        return error.message
    return error.message + (PORT_HINT if port is None else "")


def access_kind(row: dict) -> str:
    """Hub, reader or intercom from the reported capabilities and type."""
    capabilities = row.get("capabilities")
    flags = set(capabilities) if isinstance(capabilities, list) else set()
    model = _text(row.get("type")).upper()
    if "INTERCOM" in model:
        return INTERCOM
    if "is_hub" in flags or model.startswith("UAH"):
        return HUB
    if "is_reader" in flags:
        return READER
    return OTHER


def read_access_inventory(
    config: AccessConfig,
    *,
    captured_at: datetime | None = None,
    transport: httpx.BaseTransport | None = None,
) -> InventorySnapshot:
    """Adopted Access hardware from the developer API (GET ``devices`` only).

    Kept fields: name (alias first), model (``type``), MAC (the device ID is
    the MAC address), kind and online state. Users, logs and doors are never
    requested.
    """
    if not config.configured:
        raise InventoryError("Set the Access API URL (port 12445) and token.")
    try:
        with access_client(config, transport=transport) as client:
            rows = flatten_devices(access_data(client, "devices"))
    except _Failure as error:
        raise InventoryError(_with_port_hint(config, error)) from None
    except (httpx.HTTPError, OSError, ValueError, TypeError) as error:
        raise InventoryError(
            "UniFi Access inventory read failed due to transport errors."
        ) from error
    devices = [_normalize(row) for row in rows if row.get("is_adopted") is not False]
    ids = [device.source_id for device in devices]
    if len(set(ids)) != len(ids):
        raise InventoryError("UniFi Access returned duplicate device IDs.")
    return InventorySnapshot(
        source=InventorySource.UNIFI_ACCESS,
        captured_at=_timestamp(captured_at),
        devices=tuple(devices),
    )


def _normalize(row: dict) -> InventoryDevice:
    source_id = _text(row.get("id"))
    if not source_id:
        raise InventoryError("UniFi Access returned a malformed device entry.")
    mac = (
        _normalize_mac(source_id) if re.fullmatch(r"[0-9a-fA-F]{12}", source_id) else ""
    )
    online = row.get("is_online")
    return InventoryDevice(
        source_id=source_id,
        name=_text(row.get("alias")) or _text(row.get("name")),
        model=_text(row.get("type")),
        manufacturer="Ubiquiti",
        mac_address=mac,
        kind=access_kind(row),
        state="" if online is None else ("online" if online else "offline"),
    )
