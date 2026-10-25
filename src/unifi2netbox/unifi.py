import ssl
from uuid import UUID

import httpx
from packaging.version import Version

from unifi2netbox.config import UniFiConfig
from unifi2netbox.netbox import ConnectionResult, ConnectionState


class CheckFailure(Exception):
    def __init__(self, state: ConnectionState, message: str) -> None:
        self.state = state
        self.message = message
        super().__init__(message)


def _get(client: httpx.Client, path: str, **params) -> dict:
    response = client.get(path, params=params)
    code = response.status_code
    if 300 <= code < 400:
        raise CheckFailure(
            ConnectionState.ERROR, "Redirect refused. Configure the final console URL."
        )
    if code in {401, 403}:
        raise CheckFailure(
            ConnectionState.UNAUTHORIZED,
            "Local API key or site/device-read permission was denied.",
        )
    if code in {404, 405}:
        raise CheckFailure(
            ConnectionState.UNSUPPORTED,
            "A required local Network Integration API endpoint is unavailable. "
            "Check the console URL, version and local Integrations documentation.",
        )
    if code != 200:
        raise CheckFailure(ConnectionState.ERROR, f"UniFi returned HTTP {code}.")
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError
    return data


def _page(data: dict, offset: int, requested_limit: int) -> list[dict]:
    for key in ("offset", "limit", "count", "totalCount"):
        if type(data.get(key)) is not int or data[key] < 0:
            raise ValueError
    rows = data.get("data")
    if (
        not isinstance(rows, list)
        or not all(isinstance(row, dict) for row in rows)
        or data["offset"] != offset
        or not 0 < data["limit"] <= requested_limit
        or data["count"] != len(rows)
        or len(rows) > data["limit"]
        or data["totalCount"] < offset + len(rows)
        or (not rows and data["totalCount"] > offset)
    ):
        raise ValueError
    return rows


def _sites(client: httpx.Client) -> list[dict]:
    sites = []
    seen = set()
    for _ in range(10):
        data = _get(client, "sites", offset=len(sites), limit=200)
        rows = _page(data, len(sites), 200)
        for site in rows:
            for key in ("id", "name", "internalReference"):
                if not isinstance(site.get(key), str):
                    raise ValueError
            identifier = str(UUID(site["id"]))
            if identifier in seen:
                raise ValueError
            seen.add(identifier)
            sites.append(site)
        if len(sites) == data["totalCount"]:
            return sites
    raise CheckFailure(
        ConnectionState.PARTIAL, "Site discovery exceeded the bounded ten-page limit."
    )


def _tls_failure(error: BaseException) -> bool:
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        if isinstance(current, ssl.SSLError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def check_connection(
    config: UniFiConfig, *, transport: httpx.BaseTransport | None = None
) -> ConnectionResult:
    if not config.configured:
        return ConnectionResult(
            ConnectionState.UNCONFIGURED, "Set a UniFi console URL and local API key."
        )
    version = ""
    choices = ()
    try:
        verify = config.verify_tls
        if config.verify_tls and config.ca_bundle:
            verify = ssl.create_default_context(cafile=config.ca_bundle)
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
            info = _get(client, "info")
            text = info.get("applicationVersion")
            if not isinstance(text, str):
                raise ValueError
            parsed = Version(text)
            version = str(parsed)
            if parsed.release[:2] != (10, 6) or parsed.is_prerelease:
                return ConnectionResult(
                    ConnectionState.UNSUPPORTED,
                    "This build targets the Network 10.6 local Integration API.",
                    version,
                )
            sites = _sites(client)
            choices = tuple((site["id"], site["name"]) for site in sites)
            if not sites:
                raise CheckFailure(
                    ConnectionState.PARTIAL,
                    "The API is reachable, but the key exposes no accessible site.",
                )
            selected = [
                site
                for site in sites
                if config.site.strip()
                in {site["id"], site["name"], site["internalReference"]}
            ]
            if not config.site.strip() and len(sites) == 1:
                selected = sites
            if len(selected) != 1:
                raise CheckFailure(
                    ConnectionState.UNCONFIGURED,
                    "Choose one accessible site by ID, name or internal reference "
                    "in UniFi Network Settings.",
                )
            site = selected[0]
            identifier = str(UUID(site["id"]))
            devices = _get(client, f"sites/{identifier}/devices", offset=0, limit=1)
            _page(devices, 0, 1)
            return ConnectionResult(
                ConnectionState.ONLINE,
                "Authenticated local info, site and device-read access succeeded.",
                version,
                f"{site['name']} ({identifier})",
                choices,
            )
    except CheckFailure as error:
        return ConnectionResult(error.state, error.message, version, sites=choices)
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
            "Cannot connect to the configured UniFi console.",
            version,
        )
    except OSError:
        return ConnectionResult(
            ConnectionState.TLS_ERROR, "Cannot load the configured CA bundle.", version
        )
    except httpx.HTTPError, ValueError, TypeError, UnicodeError:
        return ConnectionResult(
            ConnectionState.ERROR,
            "The server did not return a supported Network Integration API response.",
            version,
        )
