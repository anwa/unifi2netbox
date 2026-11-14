"""Connection check for the UniFi Access API (read-only).

UniFi Access serves its developer API on its own port (12445) of the console
running Access and needs an Access API token created in the Access app; the
Network key is not accepted. Requests are GET only, never follow redirects
and ignore proxy environment variables. The app only reads devices, even when
the token itself would allow more (users, logs, door control).
"""

import ssl

import httpx

from unifi2netbox.config import AccessConfig
from unifi2netbox.netbox import ConnectionResult, ConnectionState
from unifi2netbox.unifi import _tls_failure

API_PATH = "/api/v1/developer/"


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
        return ConnectionResult(error.state, error.message)
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
