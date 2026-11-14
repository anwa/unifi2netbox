"""UniFi Drive console (UNAS): connection check and inventory, read-only.

Ubiquiti documents no Drive or UNAS device API yet. The connection check reads
only the public UniFi OS system information of the configured console
(``/api/system``: model and system MAC) and confirms that it is a UNAS.

The inventory additionally reads the internal Drive storage endpoint
(``/proxy/drive/api/v2/storage``) with the local API key and keeps only
allow-listed drive-bay fields (slot, model, serial, firmware, type, size,
state, temperature, health, pool). Requests are GET only, never follow
redirects and ignore proxy environment variables. File contents, shares and
users are never requested.
"""

import ssl
from dataclasses import replace
from datetime import datetime

import httpx

from unifi2netbox.config import DriveConfig
from unifi2netbox.inventory import (
    InventoryDevice,
    InventoryDisk,
    InventoryError,
    InventorySnapshot,
    InventorySource,
    _normalize_mac,
    _text,
    _timestamp,
)
from unifi2netbox.netbox import ConnectionResult, ConnectionState
from unifi2netbox.unifi import _tls_failure

SYSTEM_PATH = "/api/system"
STORAGE_PATH = "/proxy/drive/api/v2/storage"
DRIVE_MODEL_PREFIX = "UNAS"
NAS = "nas"


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


def read_drive_inventory(
    config: DriveConfig,
    *,
    captured_at: datetime | None = None,
    transport: httpx.BaseTransport | None = None,
) -> InventorySnapshot:
    """The UNAS as one device plus its drive bays.

    The device comes from the public system information (name, model, system
    MAC). Drive bays come from the internal storage endpoint with the local
    API key; if that read fails, the device is still returned and
    ``disk_error`` explains why the bays are missing.
    """
    if not config.configured:
        raise InventoryError("Set the UNAS console URL and its local API key.")
    try:
        with drive_client(config, transport=transport) as client:
            system = read_system(client)
            disks, disk_error = _read_disks(client, config)
    except _Failure as error:
        raise InventoryError(error.message) from None
    except (httpx.HTTPError, OSError, ValueError, TypeError) as error:
        raise InventoryError(
            "UniFi Drive inventory read failed due to transport errors."
        ) from error
    mac = _normalize_mac(system.get("mac"))
    source_id = mac.replace(":", "").lower() or "unas"
    device = InventoryDevice(
        source_id=source_id,
        name=_text(system.get("name")),
        model=_text(system["hardware"]["shortname"]),
        manufacturer="Ubiquiti",
        mac_address=mac,
        kind=NAS,
        # deviceState reports setup phases ("setup"), not reachability; the
        # system read itself just succeeded, so the console is online.
        state="online",
    )
    return InventorySnapshot(
        source=InventorySource.UNIFI_DRIVE,
        captured_at=_timestamp(captured_at),
        devices=(device,),
        disks=tuple(replace(disk, device_id=source_id) for disk in disks),
        disk_error=disk_error,
    )


def _read_disks(
    client: httpx.Client, config: DriveConfig
) -> tuple[tuple[InventoryDisk, ...], str]:
    response = client.get(STORAGE_PATH, headers={"X-API-KEY": config.token})
    code = response.status_code
    if code in {401, 403}:
        return (), "The UNAS rejected the local API key for the storage read."
    if code != 200 or "json" not in response.headers.get("content-type", ""):
        return (), f"The UNAS storage read returned HTTP {code}; drive bays unknown."
    payload = response.json()
    rows = payload.get("disks") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return (), "The UNAS returned no supported drive-bay list."
    disks = tuple(_disk(row) for row in rows if isinstance(row, dict))
    slots = [disk.slot for disk in disks]
    if len(set(slots)) != len(slots):
        return (), "The UNAS returned duplicate drive bays."
    return disks, ""


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _disk(row: dict) -> InventoryDisk:
    """Allow-listed drive-bay fields; everything else is ignored."""
    return InventoryDisk(
        device_id="",
        slot=_text(row.get("slotId")) or str(_int(row.get("slotId")) or ""),
        model=_text(row.get("model")),
        serial=_text(row.get("serial")),
        firmware=_text(row.get("firmware")),
        kind=_text(row.get("type")),
        size_bytes=_int(row.get("size")) or 0,
        state=_text(row.get("state")),
        temperature_c=_int(row.get("temperature")),
        health=_int(row.get("healthScore")),
        pool=_text(row.get("poolId")),
    )
