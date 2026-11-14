"""Connection check for a UniFi Drive console (UNAS), read-only.

Ubiquiti documents no Drive or UNAS device API yet. The check therefore reads
only the public UniFi OS system information of the configured console
(``/api/system``: model and system MAC) and confirms that it is a UNAS. The
local API key created on the UNAS is stored for future Drive APIs but not
sent anywhere yet. Requests are GET only, never follow redirects and ignore
proxy environment variables. File contents and storage data are never read.
"""

import ssl

import httpx

from unifi2netbox.config import DriveConfig
from unifi2netbox.netbox import ConnectionResult, ConnectionState
from unifi2netbox.unifi import _tls_failure

SYSTEM_PATH = "/api/system"
DRIVE_MODEL_PREFIX = "UNAS"


class _Failure(Exception):
    def __init__(self, state: ConnectionState, message: str) -> None:
        self.state = state
        self.message = message
        super().__init__(message)


def drive_client(
    config: DriveConfig, *, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    """HTTP client for the UNAS console with the safe defaults (no key header)."""
    verify: bool | ssl.SSLContext = config.verify_tls
    if config.verify_tls and config.ca_bundle:
        verify = ssl.create_default_context(cafile=config.ca_bundle)
    return httpx.Client(
        base_url=config.url.rstrip("/"),
        headers={"Accept": "application/json"},
        verify=verify,
        timeout=httpx.Timeout(config.timeout),
        follow_redirects=False,
        trust_env=False,
        limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        transport=transport,
    )


def read_system(client: httpx.Client) -> dict:
    """Public UniFi OS system info of a UNAS; raises ``_Failure`` otherwise."""
    response = client.get(SYSTEM_PATH)
    code = response.status_code
    if 300 <= code < 400:
        raise _Failure(
            ConnectionState.ERROR, "Redirect refused. Configure the final console URL."
        )
    if code in {404, 405} or "html" in response.headers.get("content-type", ""):
        raise _Failure(
            ConnectionState.UNSUPPORTED,
            "No UniFi OS console answers on this URL. Use the UNAS management address.",
        )
    if code != 200:
        raise _Failure(ConnectionState.ERROR, f"The console returned HTTP {code}.")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError
    hardware = payload.get("hardware")
    model = hardware.get("shortname") if isinstance(hardware, dict) else None
    if not isinstance(model, str) or not model.upper().startswith(DRIVE_MODEL_PREFIX):
        raise _Failure(
            ConnectionState.UNSUPPORTED,
            "This console is not a UniFi Drive console (UNAS).",
        )
    return payload


def check_drive_connection(
    config: DriveConfig, *, transport: httpx.BaseTransport | None = None
) -> ConnectionResult:
    if not config.configured:
        return ConnectionResult(
            ConnectionState.UNCONFIGURED,
            "Optional. Set the UNAS console URL and its local API key.",
        )
    try:
        with drive_client(config, transport=transport) as client:
            system = read_system(client)
    except _Failure as error:
        return ConnectionResult(error.state, error.message)
    except httpx.TimeoutException:
        return ConnectionResult(ConnectionState.OFFLINE, "The request timed out.")
    except (httpx.ConnectError, ssl.SSLError) as error:
        if _tls_failure(error):
            return ConnectionResult(
                ConnectionState.TLS_ERROR,
                "TLS validation failed. Check the certificate and CA settings.",
            )
        return ConnectionResult(
            ConnectionState.OFFLINE, "Cannot connect to the configured UNAS console."
        )
    except OSError:
        return ConnectionResult(
            ConnectionState.TLS_ERROR, "Cannot load the configured CA bundle."
        )
    except httpx.HTTPError, ValueError, TypeError, UnicodeError:
        return ConnectionResult(
            ConnectionState.ERROR,
            "The console did not return supported UniFi OS system information.",
        )
    model = system["hardware"]["shortname"]
    return ConnectionResult(
        ConnectionState.ONLINE,
        f"{model} reachable (system information read). The API key is stored "
        "for future UniFi Drive APIs; Ubiquiti documents no Drive device API yet.",
    )
