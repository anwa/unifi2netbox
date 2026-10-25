from dataclasses import dataclass
from enum import StrEnum

import pynetbox
import requests
from packaging.version import InvalidVersion, Version
from pynetbox.core.query import ContentError, RequestError

from unifi2netbox.config import NetBoxConfig


class ConnectionState(StrEnum):
    UNCONFIGURED = "Unconfigured"
    CHECKING = "Checking"
    ONLINE = "Online"
    OFFLINE = "Offline"
    UNAUTHORIZED = "Unauthorized"
    TLS_ERROR = "TLS error"
    UNSUPPORTED = "Unsupported"
    ERROR = "Error"


@dataclass(frozen=True)
class ConnectionResult:
    state: ConnectionState
    message: str
    version: str = ""


class RedirectError(Exception):
    pass


class ReadOnlySession(requests.Session):
    def __init__(self, config: NetBoxConfig) -> None:
        super().__init__()
        self.verify = (config.ca_bundle or True) if config.verify_tls else False
        self.timeout = config.timeout

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        if method.lower() != "get":
            raise ValueError("This milestone only permits read-only API requests.")
        kwargs["timeout"] = (self.timeout, self.timeout)
        kwargs["allow_redirects"] = False
        response = super().request(method, url, **kwargs)
        if 300 <= response.status_code < 400:
            raise RedirectError
        return response


def check_connection(config: NetBoxConfig) -> ConnectionResult:
    if not config.configured:
        return ConnectionResult(
            ConnectionState.UNCONFIGURED, "Set a NetBox URL and API token."
        )
    try:
        with ReadOnlySession(config) as session:
            api = pynetbox.api(config.url.rstrip("/"), token=config.token)
            api.http_session.close()
            api.http_session = session
            status = api.status()
            version_text = status.get("netbox-version", "")
            if not isinstance(version_text, str):
                raise ValueError
            version = Version(version_text)
            if version.release[:2] != (4, 7) or version.is_prerelease:
                return ConnectionResult(
                    ConnectionState.UNSUPPORTED,
                    "This build targets the NetBox 4.7 API.",
                )
            next(iter(api.dcim.devices.filter(limit=1)), None)
            return ConnectionResult(
                ConnectionState.ONLINE,
                "Authenticated device inventory access succeeded.",
                str(version),
            )
    except requests.exceptions.SSLError:
        return ConnectionResult(
            ConnectionState.TLS_ERROR,
            "Certificate validation failed. Check the CA bundle or TLS settings.",
        )
    except requests.exceptions.Timeout:
        return ConnectionResult(ConnectionState.OFFLINE, "The API request timed out.")
    except requests.exceptions.ConnectionError:
        return ConnectionResult(
            ConnectionState.OFFLINE, "Cannot connect to the configured NetBox host."
        )
    except RequestError as error:
        code = error.req.status_code
        if code in {401, 403}:
            return ConnectionResult(
                ConnectionState.UNAUTHORIZED,
                "Authentication or device-read permission was denied.",
            )
        return ConnectionResult(ConnectionState.ERROR, f"NetBox returned HTTP {code}.")
    except RedirectError:
        return ConnectionResult(
            ConnectionState.ERROR,
            "Redirect refused. Configure the final NetBox URL explicitly.",
        )
    except (
        ContentError,
        InvalidVersion,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        requests.exceptions.RequestException,
    ):
        return ConnectionResult(
            ConnectionState.ERROR,
            "The server did not return a supported NetBox response.",
        )
