"""Connection check for the UniFi Protect local Integration API (read-only).

Protect runs on its own console (for example a UNVR) with its own local API
key, so it has a separate configuration section. "Online" means the info, NVR
and camera reads succeed with the configured key. Requests are GET only, never
follow redirects and ignore proxy environment variables.
"""

import ssl

import httpx
from packaging.version import Version

from unifi2netbox.config import ProtectConfig
from unifi2netbox.netbox import ConnectionResult, ConnectionState
from unifi2netbox.unifi import _tls_failure

API_PATH = "/proxy/protect/integration/v1/"

# Protect release series validated for the local Integration API.
SUPPORTED_SERIES: frozenset[tuple[int, int]] = frozenset({(7, 3)})


class _Failure(Exception):
    def __init__(self, state: ConnectionState, message: str) -> None:
        self.state = state
        self.message = message
        super().__init__(message)


def protect_client(
    config: ProtectConfig, *, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    """HTTP client for the Protect Integration API with the safe defaults."""
    verify: bool | ssl.SSLContext = config.verify_tls
    if config.verify_tls and config.ca_bundle:
        verify = ssl.create_default_context(cafile=config.ca_bundle)
    return httpx.Client(
        base_url=config.url.rstrip("/") + API_PATH,
        headers={"X-API-KEY": config.token, "Accept": "application/json"},
        verify=verify,
        timeout=httpx.Timeout(config.timeout),
        follow_redirects=False,
        trust_env=False,
        limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        transport=transport,
    )


def protect_json(client: httpx.Client, path: str) -> object:
    """One GET; HTML answers mean no Protect application on that console."""
    response = client.get(path)
    code = response.status_code
    if 300 <= code < 400:
        raise _Failure(
            ConnectionState.ERROR, "Redirect refused. Configure the final console URL."
        )
    if code in {401, 403}:
        raise _Failure(
            ConnectionState.UNAUTHORIZED,
            "Local API key or Protect read permission was denied.",
        )
    if code in {404, 405} or "html" in response.headers.get("content-type", ""):
        raise _Failure(
            ConnectionState.UNSUPPORTED,
            "No UniFi Protect Integration API answers on this console. Check that "
            "the URL points to the console running Protect.",
        )
    if code != 200:
        raise _Failure(ConnectionState.ERROR, f"UniFi Protect returned HTTP {code}.")
    return response.json()


def check_protect_connection(
    config: ProtectConfig, *, transport: httpx.BaseTransport | None = None
) -> ConnectionResult:
    if not config.configured:
        return ConnectionResult(
            ConnectionState.UNCONFIGURED,
            "Optional. Set the URL and local API key of the console running "
            "UniFi Protect.",
        )
    version = ""
    try:
        with protect_client(config, transport=transport) as client:
            info = protect_json(client, "meta/info")
            text = info.get("applicationVersion") if isinstance(info, dict) else None
            if not isinstance(text, str):
                raise ValueError
            parsed = Version(text)
            version = str(parsed)
            if parsed.release[:2] not in SUPPORTED_SERIES or parsed.is_prerelease:
                return ConnectionResult(
                    ConnectionState.UNSUPPORTED,
                    "This build supports the Protect 7.3 local Integration API.",
                    version,
                )
            nvrs = protect_json(client, "nvrs")
            cameras = protect_json(client, "cameras")
            if not isinstance(nvrs, dict | list) or not isinstance(cameras, list):
                raise ValueError
            count = len(cameras)
            return ConnectionResult(
                ConnectionState.ONLINE,
                "Authenticated local info, NVR and camera-read access succeeded "
                f"({count} camera{'s' if count != 1 else ''}).",
                version,
            )
    except _Failure as error:
        return ConnectionResult(error.state, error.message, version)
    except httpx.TimeoutException:
        return ConnectionResult(
            ConnectionState.OFFLINE, "The API request timed out.", version
        )
    except (httpx.ConnectError, ssl.SSLError) as error:
        if _tls_failure(error):
            return ConnectionResult(
                ConnectionState.TLS_ERROR,
                "TLS validation failed. Check the certificate and CA settings.",
                version,
            )
        return ConnectionResult(
            ConnectionState.OFFLINE,
            "Cannot connect to the configured Protect console.",
            version,
        )
    except OSError:
        return ConnectionResult(
            ConnectionState.TLS_ERROR, "Cannot load the configured CA bundle.", version
        )
    except httpx.HTTPError, ValueError, TypeError, UnicodeError:
        return ConnectionResult(
            ConnectionState.ERROR,
            "The server did not return a supported Protect Integration API response.",
            version,
        )
