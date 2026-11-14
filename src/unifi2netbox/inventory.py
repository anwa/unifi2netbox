import ipaddress
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

import httpx
import requests

from unifi2netbox.config import NetBoxConfig, UniFiConfig
from unifi2netbox.links import InventoryLink, read_links
from unifi2netbox.netbox import ReadOnlySession, RedirectError
from unifi2netbox.port_config import (
    InventoryPortConfig,
    allowed_networks,
    allowed_profiles,
    resolve_port_configs,
)

# Internal Network endpoints are only read for validated versions.
INTERNAL_API_SERIES = ("11.0.",)


class InventorySource(StrEnum):
    NETBOX = "netbox"
    UNIFI_NETWORK = "unifi_network"
    UNIFI_PROTECT = "unifi_protect"
    UNIFI_ACCESS = "unifi_access"
    UNIFI_DRIVE = "unifi_drive"


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
    kind: str = ""
    state: str = ""


@dataclass(frozen=True)
class InventoryDeviceType:
    source_id: str
    manufacturer: str
    model: str
    part_number: str = ""


@dataclass(frozen=True)
class InventoryDeviceRole:
    source_id: str
    name: str


@dataclass(frozen=True)
class InventorySite:
    source_id: str
    name: str


@dataclass(frozen=True)
class InventoryDeviceStatus:
    value: str
    label: str


@dataclass(frozen=True)
class InventoryPort:
    """One UniFi switch port from the official Integration API.

    ``link_state`` and ``speed_mbps`` are operational values: they describe the
    current link and must never be written as configuration.
    """

    device_id: str
    idx: int
    connector: str
    max_speed_mbps: int = 0
    link_state: str = ""
    speed_mbps: int = 0
    poe_standard: str = ""
    poe_type: int = 0
    poe_enabled: bool | None = None
    poe_state: str = ""


@dataclass(frozen=True)
class InventoryInterface:
    """One NetBox device interface."""

    source_id: str
    device_id: str
    name: str
    type: str
    enabled: bool = True
    mgmt_only: bool = False
    mode: str = ""
    poe_mode: str = ""
    poe_type: str = ""
    speed_kbps: int = 0
    untagged_vlan_id: str = ""
    tagged_vlan_ids: tuple[str, ...] = ()
    lag_id: str = ""
    cable_id: str = ""
    link_peer_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class InventoryNetwork:
    """One UniFi network (official API) with its VLAN and IPv4 subnet."""

    source_id: str
    name: str
    vlan_id: int
    enabled: bool = True
    subnet: str = ""
    gateway_ip: str = ""
    default: bool = False


@dataclass(frozen=True)
class InventoryVlanGroup:
    source_id: str
    name: str
    slug: str = ""
    scope_type: str = ""
    scope_id: str = ""


@dataclass(frozen=True)
class InventoryVlan:
    source_id: str
    vid: int
    name: str
    group_id: str = ""
    status: str = ""


@dataclass(frozen=True)
class InventoryPrefix:
    source_id: str
    prefix: str
    vlan_id: str = ""
    scope_type: str = ""
    scope_id: str = ""
    status: str = ""
    description: str = ""


@dataclass(frozen=True)
class InventoryDisk:
    """One drive bay of a UNAS (UniFi Drive), from allow-listed fields.

    ``slot``, ``model``, ``serial``, ``firmware``, ``kind`` and ``size_bytes``
    describe the hardware; ``state``, ``temperature_c``, ``health`` and
    ``pool`` are operational and display only. Empty bays have no model.
    """

    device_id: str
    slot: str
    model: str = ""
    serial: str = ""
    firmware: str = ""
    kind: str = ""
    size_bytes: int = 0
    state: str = ""
    temperature_c: int | None = None
    health: int | None = None
    pool: str = ""


@dataclass(frozen=True)
class InventorySnapshot:
    source: InventorySource
    captured_at: str
    source_version: str = ""
    scope: str = ""
    devices: tuple[InventoryDevice, ...] = ()
    device_types: tuple[InventoryDeviceType, ...] = ()
    device_roles: tuple[InventoryDeviceRole, ...] = ()
    sites: tuple[InventorySite, ...] = ()
    device_statuses: tuple[InventoryDeviceStatus, ...] = ()
    unifi_api_feedback: tuple[dict[str, object], ...] = ()
    unifi_raw_devices: tuple[dict[str, object], ...] = ()
    ports: tuple[InventoryPort, ...] = ()
    interfaces: tuple[InventoryInterface, ...] = ()
    networks: tuple[InventoryNetwork, ...] = ()
    vlan_groups: tuple[InventoryVlanGroup, ...] = ()
    vlans: tuple[InventoryVlan, ...] = ()
    prefixes: tuple[InventoryPrefix, ...] = ()
    ipam_error: str = ""
    port_configs: tuple[InventoryPortConfig, ...] = ()
    port_config_error: str = ""
    links: tuple[InventoryLink, ...] = ()
    disks: tuple[InventoryDisk, ...] = ()
    disk_error: str = ""


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


def normalize_netbox_device(row: dict[str, object]) -> InventoryDevice:
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


def _normalize_netbox_device_type(row: dict[str, object]) -> InventoryDeviceType | None:
    manufacturer = ""
    vendor = row.get("manufacturer")
    if isinstance(vendor, dict):
        manufacturer = _text(vendor.get("name"))
    model = _text(row.get("model"))
    source_id = str(row.get("id", "")).strip()
    if not manufacturer or not model or not source_id:
        return None
    return InventoryDeviceType(
        source_id=source_id,
        manufacturer=manufacturer,
        model=model,
        part_number=_text(row.get("part_number")),
    )


def _identifier(value: object) -> str:
    """NetBox IDs arrive as integers; accept integer or text IDs."""
    if type(value) is int:
        return str(value)
    return _text(value)


def _choice_value(value: object) -> str:
    if isinstance(value, dict):
        return _text(value.get("value"))
    return _text(value)


def _normalize_netbox_interface(row: dict[str, object]) -> InventoryInterface | None:
    device = row.get("device")
    device_id = _identifier(device.get("id")) if isinstance(device, dict) else ""
    source_id = _identifier(row.get("id"))
    name = _text(row.get("name"))
    if not device_id or not source_id or not name:
        return None
    speed = row.get("speed")
    tagged = row.get("tagged_vlans")
    if not isinstance(tagged, list):
        tagged = []
    return InventoryInterface(
        source_id=source_id,
        device_id=device_id,
        name=name,
        type=_choice_value(row.get("type")),
        enabled=row.get("enabled") is not False,
        mgmt_only=row.get("mgmt_only") is True,
        mode=_choice_value(row.get("mode")),
        poe_mode=_choice_value(row.get("poe_mode")),
        poe_type=_choice_value(row.get("poe_type")),
        speed_kbps=speed if type(speed) is int and speed > 0 else 0,
        untagged_vlan_id=_related_id(row.get("untagged_vlan")),
        tagged_vlan_ids=tuple(
            sorted(
                {vlan_id for item in tagged if (vlan_id := _related_id(item))},
                key=_numeric_key,
            )
        ),
        lag_id=_related_id(row.get("lag")),
        cable_id=_related_id(row.get("cable")),
        link_peer_ids=_interface_peers(row),
    )


def _interface_peers(row: dict[str, object]) -> tuple[str, ...]:
    """IDs of cabled peer interfaces; other peer types are not interfaces."""
    peers = row.get("link_peers")
    if row.get("link_peers_type") != "dcim.interface" or not isinstance(peers, list):
        return ()
    return tuple(peer_id for item in peers if (peer_id := _related_id(item)))


def _numeric_key(value: str) -> tuple[int, str]:
    return (int(value), "") if value.isdigit() else (0, value)


def _related_id(value: object) -> str:
    return _identifier(value.get("id")) if isinstance(value, dict) else ""


def _normalize_netbox_vlan_group(row: dict[str, object]) -> InventoryVlanGroup | None:
    source_id = _identifier(row.get("id"))
    name = _text(row.get("name"))
    if not source_id or not name:
        return None
    return InventoryVlanGroup(
        source_id=source_id,
        name=name,
        slug=_text(row.get("slug")),
        scope_type=_text(row.get("scope_type")),
        scope_id=_identifier(row.get("scope_id")),
    )


def _normalize_netbox_vlan(row: dict[str, object]) -> InventoryVlan | None:
    source_id = _identifier(row.get("id"))
    vid = row.get("vid")
    if not source_id or type(vid) is not int:
        return None
    return InventoryVlan(
        source_id=source_id,
        vid=vid,
        name=_text(row.get("name")),
        group_id=_related_id(row.get("group")),
        status=_choice_value(row.get("status")),
    )


def _normalize_netbox_prefix(row: dict[str, object]) -> InventoryPrefix | None:
    source_id = _identifier(row.get("id"))
    prefix = _text(row.get("prefix"))
    if not source_id or not prefix:
        return None
    return InventoryPrefix(
        source_id=source_id,
        prefix=prefix,
        vlan_id=_related_id(row.get("vlan")),
        scope_type=_text(row.get("scope_type")),
        scope_id=_identifier(row.get("scope_id")),
        status=_choice_value(row.get("status")),
        description=_text(row.get("description")),
    )


def _normalize_netbox_device_role(row: dict[str, object]) -> InventoryDeviceRole | None:
    source_id = str(row.get("id", "")).strip()
    name = _text(row.get("name"))
    if not source_id or not name:
        return None
    return InventoryDeviceRole(source_id=source_id, name=name)


def _normalize_netbox_site(row: dict[str, object]) -> InventorySite | None:
    source_id = str(row.get("id", "")).strip()
    name = _text(row.get("name"))
    if not source_id or not name:
        return None
    return InventorySite(source_id=source_id, name=name)


def _netbox_device_statuses(
    session: requests.Session, config: NetBoxConfig
) -> list[InventoryDeviceStatus]:
    payload = _netbox_json(session, config, "/api/dcim/devices/_choices/")
    actions = payload.get("actions") if isinstance(payload, dict) else None
    post = actions.get("POST") if isinstance(actions, dict) else None
    status = post.get("status") if isinstance(post, dict) else None
    choices = status.get("choices") if isinstance(status, dict) else None
    if not isinstance(choices, list):
        raise InventoryError("NetBox device status choices payload is invalid.")

    values: list[InventoryDeviceStatus] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        value = _text(choice.get("value"))
        label = _text(choice.get("label")) or value
        if not value:
            continue
        values.append(InventoryDeviceStatus(value=value, label=label))
    return values


def _netbox_device_statuses_from_devices(
    device_rows: list[dict[str, object]],
) -> list[InventoryDeviceStatus]:
    inferred: dict[str, str] = {}
    for row in device_rows:
        status = row.get("status")
        value = ""
        label = ""
        if isinstance(status, dict):
            value = _text(status.get("value"))
            label = _text(status.get("label")) or _text(status.get("name"))
        elif isinstance(status, str):
            value = _text(status)
        if not value:
            continue
        if not label:
            label = value
        inferred[value] = label
    return [
        InventoryDeviceStatus(value=value, label=inferred[value])
        for value in sorted(inferred)
    ]


def _netbox_paginated_rows(
    session: requests.Session,
    config: NetBoxConfig,
    path: str,
    *,
    page_size: int,
    max_pages: int,
    limit_error: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    offset = 0
    pages = 0

    while pages < max_pages:
        payload = _netbox_json(
            session,
            config,
            f"{path}?limit={page_size}&offset={offset}",
        )
        count = payload.get("count")
        page_rows = payload.get("results")
        if (
            type(count) is not int
            or count < 0
            or not isinstance(page_rows, list)
            or not all(isinstance(row, dict) for row in page_rows)
            or len(page_rows) > page_size
            or offset + len(page_rows) > count
        ):
            raise InventoryError("NetBox returned an invalid paginated payload.")
        rows.extend(page_rows)
        pages += 1
        if offset + len(page_rows) >= count:
            break
        if not page_rows:
            raise InventoryError(
                "NetBox pagination stopped unexpectedly before count was reached."
            )
        offset += len(page_rows)
    else:
        raise InventoryError(limit_error)

    return rows


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
    interfaces: list[InventoryInterface] = []
    vlan_groups: list[InventoryVlanGroup] = []
    vlans: list[InventoryVlan] = []
    prefixes: list[InventoryPrefix] = []
    ipam_error = ""
    device_types: list[InventoryDeviceType] = []
    device_roles: list[InventoryDeviceRole] = []
    sites: list[InventorySite] = []
    device_statuses: list[InventoryDeviceStatus] = []
    version = ""
    try:
        with ReadOnlySession(config) as session:
            status = _netbox_json(session, config, "/api/status/")
            version = _text(status.get("netbox-version"))
            device_rows = _netbox_paginated_rows(
                session,
                config,
                "/api/dcim/devices/",
                page_size=page_size,
                max_pages=max_pages,
                limit_error=(
                    "NetBox pagination exceeded the configured page safety limit."
                ),
            )
            devices.extend(normalize_netbox_device(row) for row in device_rows)
            device_statuses.extend(_netbox_device_statuses_from_devices(device_rows))

            interface_rows = _netbox_paginated_rows(
                session,
                config,
                "/api/dcim/interfaces/",
                page_size=page_size,
                max_pages=max_pages,
                limit_error=(
                    "NetBox interface pagination exceeded the configured page "
                    "safety limit."
                ),
            )
            for row in interface_rows:
                interface = _normalize_netbox_interface(row)
                if interface is not None:
                    interfaces.append(interface)

            # IPAM is optional: a token without IPAM rights must not break the
            # device inventory; network planning is skipped instead.
            try:
                for path, normalize, target in (
                    (
                        "/api/ipam/vlan-groups/",
                        _normalize_netbox_vlan_group,
                        vlan_groups,
                    ),
                    ("/api/ipam/vlans/", _normalize_netbox_vlan, vlans),
                    ("/api/ipam/prefixes/", _normalize_netbox_prefix, prefixes),
                ):
                    rows = _netbox_paginated_rows(
                        session,
                        config,
                        path,
                        page_size=page_size,
                        max_pages=max_pages,
                        limit_error=(
                            "NetBox IPAM pagination exceeded the configured page "
                            "safety limit."
                        ),
                    )
                    target.extend(
                        item for item in map(normalize, rows) if item is not None
                    )
            except InventoryError as error:
                vlan_groups.clear()
                vlans.clear()
                prefixes.clear()
                ipam_error = f"NetBox IPAM could not be read: {error}"

            type_rows = _netbox_paginated_rows(
                session,
                config,
                "/api/dcim/device-types/",
                page_size=page_size,
                max_pages=max_pages,
                limit_error=(
                    "NetBox device-type pagination exceeded the configured page "
                    "safety limit."
                ),
            )
            for row in type_rows:
                item = _normalize_netbox_device_type(row)
                if item is not None:
                    device_types.append(item)

            role_rows = _netbox_paginated_rows(
                session,
                config,
                "/api/dcim/device-roles/",
                page_size=page_size,
                max_pages=max_pages,
                limit_error=(
                    "NetBox device-role pagination exceeded the configured page "
                    "safety limit."
                ),
            )
            for row in role_rows:
                role = _normalize_netbox_device_role(row)
                if role is not None:
                    device_roles.append(role)

            site_rows = _netbox_paginated_rows(
                session,
                config,
                "/api/dcim/sites/",
                page_size=page_size,
                max_pages=max_pages,
                limit_error=(
                    "NetBox site pagination exceeded the configured page safety limit."
                ),
            )
            for row in site_rows:
                site = _normalize_netbox_site(row)
                if site is not None:
                    sites.append(site)

            try:
                # Device status choices are optional enrichment for create defaults.
                # Inventory refresh must still succeed when this endpoint is missing
                # or restricted on a specific NetBox deployment/version.
                endpoint_statuses = _netbox_device_statuses(session, config)
                if endpoint_statuses:
                    device_statuses = endpoint_statuses
            except InventoryError:
                pass
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
        device_types=tuple(device_types),
        device_roles=tuple(device_roles),
        sites=tuple(sites),
        device_statuses=tuple(device_statuses),
        interfaces=tuple(interfaces),
        vlan_groups=tuple(vlan_groups),
        vlans=tuple(vlans),
        prefixes=tuple(prefixes),
        ipam_error=ipam_error,
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


def _read_port_configs(
    client: httpx.Client,
    config: UniFiConfig,
    version: str,
    reference: str,
    raw_devices: list[dict[str, object]],
) -> tuple[tuple[InventoryPortConfig, ...], tuple[InventoryLink, ...], str]:
    """Port configuration and link evidence from internal endpoints.

    Returns (configs, links, error); on failure both tuples are empty and the
    error explains why.

    Read-only and tolerant: any failure leaves the official data untouched.
    Raw internal payloads are reduced to allow-listed fields right here and
    never stored, so network secrets do not leave this function.
    """
    if not version.startswith(INTERNAL_API_SERIES):
        return (
            (),
            (),
            (
                "Port configuration is only read for validated UniFi Network "
                f"{', '.join(s.rstrip('.') for s in INTERNAL_API_SERIES)}; "
                f"installed {version or 'unknown'}."
            ),
        )
    base = f"{config.url.rstrip('/')}/proxy/network/api/s/{reference}/"
    try:
        devices = _internal_rows(client, base + "stat/device")
        profiles = allowed_profiles(_internal_rows(client, base + "rest/portconf"))
        networks = allowed_networks(_internal_rows(client, base + "rest/networkconf"))
    except InventoryError as error:
        return (), (), f"Port configuration unavailable: {error}"
    except httpx.HTTPError, OSError, ValueError, TypeError:
        return (), (), "Port configuration unavailable due to transport errors."
    by_mac = {
        mac: _text(row.get("id"))
        for row in raw_devices
        if (mac := _normalize_mac(row.get("macAddress")).replace(":", "").lower())
    }
    return (
        resolve_port_configs(devices, profiles, networks, by_mac),
        read_links(devices, by_mac),
        "",
    )


def _internal_rows(client: httpx.Client, url: str) -> list[object]:
    response = client.get(url)
    if 300 <= response.status_code < 400:
        raise InventoryError("redirect refused.")
    if response.status_code in {401, 403}:
        raise InventoryError("permission denied.")
    if response.status_code != 200:
        raise InventoryError(f"HTTP {response.status_code}.")
    payload = response.json()
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise InventoryError("unsupported JSON shape.")
    return rows


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
    manufacturer = ""
    manufacturer_value = row.get("manufacturer")
    if isinstance(manufacturer_value, dict):
        manufacturer = _text(manufacturer_value.get("name"))
    else:
        manufacturer = _text(manufacturer_value)
    if not manufacturer:
        # UniFi Network devices belong to the Ubiquiti vendor family.
        manufacturer = "Ubiquiti"

    return InventoryDevice(
        source_id=_text(row.get("id")) or _text(row.get("_id")),
        name=_text(row.get("name")) or _text(row.get("hostname")),
        serial=_text(row.get("serial")).upper(),
        model=_text(row.get("model")),
        manufacturer=manufacturer,
        mac_address=_normalize_mac(row.get("macAddress") or row.get("mac")),
        site=site_name,
    )


def _int(value: object) -> int:
    return value if type(value) is int and value >= 0 else 0


def _normalize_unifi_ports(
    device_id: str, detail: dict[str, object]
) -> list[InventoryPort]:
    interfaces = detail.get("interfaces")
    rows = interfaces.get("ports") if isinstance(interfaces, dict) else None
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise InventoryError("UniFi returned a malformed port list.")
    ports: list[InventoryPort] = []
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict) or type(row.get("idx")) is not int:
            raise InventoryError("UniFi returned a malformed port entry.")
        idx = row["idx"]
        if idx in seen:
            raise InventoryError("UniFi returned duplicate port indexes.")
        seen.add(idx)
        poe = row.get("poe") if isinstance(row.get("poe"), dict) else {}
        enabled = poe.get("enabled")
        ports.append(
            InventoryPort(
                device_id=device_id,
                idx=idx,
                connector=_text(row.get("connector")).upper(),
                max_speed_mbps=_int(row.get("maxSpeedMbps")),
                link_state=_text(row.get("state")).upper(),
                speed_mbps=_int(row.get("speedMbps")),
                poe_standard=_text(poe.get("standard")),
                poe_type=_int(poe.get("type")),
                poe_enabled=enabled if isinstance(enabled, bool) else None,
                poe_state=_text(poe.get("state")).upper(),
            )
        )
    return sorted(ports, key=lambda port: port.idx)


def _normalize_unifi_network(
    row: dict[str, object], detail: dict[str, object]
) -> InventoryNetwork | None:
    source_id = _text(row.get("id"))
    vlan_id = row.get("vlanId")
    if not source_id or type(vlan_id) is not int:
        return None
    subnet = ""
    gateway = ""
    ipv4 = detail.get("ipv4Configuration")
    if isinstance(ipv4, dict):
        host = _text(ipv4.get("hostIpAddress"))
        length = ipv4.get("prefixLength")
        if host and type(length) is int:
            try:
                interface = ipaddress.ip_interface(f"{host}/{length}")
            except ValueError:
                interface = None
            if interface is not None:
                subnet = str(interface.network)
                gateway = str(interface.ip)
    return InventoryNetwork(
        source_id=source_id,
        name=_text(row.get("name")),
        vlan_id=vlan_id,
        enabled=row.get("enabled") is not False,
        subnet=subnet,
        gateway_ip=gateway,
        default=row.get("default") is True,
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
    ports: list[InventoryPort] = []
    networks: list[InventoryNetwork] = []
    api_feedback: list[dict[str, object]] = []
    raw_devices: list[dict[str, object]] = []
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
            api_feedback.append({"endpoint": "info", "params": {}, "payload": info})
            version = _text(info.get("applicationVersion"))

            sites: list[dict[str, str]] = []
            seen_sites: set[str] = set()
            for _ in range(max_pages):
                offset = len(sites)
                site_payload = _unifi_json(client, "sites", offset=offset, limit=200)
                api_feedback.append(
                    {
                        "endpoint": "sites",
                        "params": {"offset": offset, "limit": 200},
                        "payload": site_payload,
                    }
                )
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
                api_feedback.append(
                    {
                        "endpoint": f"sites/{site['id']}/devices",
                        "params": {"offset": offset, "limit": page_size},
                        "payload": payload,
                    }
                )
                rows = _unifi_page(payload, offset, page_size)
                raw_devices.extend(rows)
                devices.extend(
                    _normalize_unifi_device(row, site["name"]) for row in rows
                )
                if offset + len(rows) >= payload["totalCount"]:
                    break
            else:
                raise InventoryError(
                    "UniFi device pagination exceeded the configured page safety limit."
                )

            for row in raw_devices:
                listed = row.get("interfaces")
                device_id = _text(row.get("id"))
                if not device_id or not (
                    isinstance(listed, list) and "ports" in listed
                ):
                    continue
                path = f"sites/{site['id']}/devices/{device_id}"
                detail = _unifi_json(client, path)
                api_feedback.append({"endpoint": path, "params": {}, "payload": detail})
                ports.extend(_normalize_unifi_ports(device_id, detail))

            network_rows: list[dict[str, object]] = []
            for page_index in range(max_pages):
                offset = page_index * page_size
                payload = _unifi_json(
                    client,
                    f"sites/{site['id']}/networks",
                    offset=offset,
                    limit=page_size,
                )
                rows = _unifi_page(payload, offset, page_size)
                network_rows.extend(rows)
                if offset + len(rows) >= payload["totalCount"]:
                    break
            else:
                raise InventoryError(
                    "UniFi network pagination exceeded the configured page safety "
                    "limit."
                )
            for row in network_rows:
                network_id = _text(row.get("id"))
                if not network_id:
                    continue
                detail = _unifi_json(
                    client, f"sites/{site['id']}/networks/{network_id}"
                )
                network = _normalize_unifi_network(row, detail)
                if network is not None:
                    networks.append(network)

            port_configs, links, port_config_error = _read_port_configs(
                client, config, version, site["internalReference"], raw_devices
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
        unifi_api_feedback=tuple(api_feedback),
        unifi_raw_devices=tuple(raw_devices),
        ports=tuple(ports),
        networks=tuple(networks),
        port_configs=port_configs,
        port_config_error=port_config_error,
        links=links,
    )
