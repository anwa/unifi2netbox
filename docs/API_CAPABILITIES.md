# API Capabilities

## UniFi Network Connection Gate

Target installation: UDM Pro Max OS 5.1.33, Network 10.6.100. The public
10.6.100 documentation URL returned 404 on 2026-10-25. The official
[10.6.106 OpenAPI](https://developer.ui.com/network/v10.6.106/openapi.json)
was inspected as a reference, not as proof of installed-version compatibility.
The user reported the preceding M2 online tests passed on 2026-10-25. No detailed
capture or exact tested environment was supplied; this is user-reported evidence,
not an assistant-executed live check. The 0.1.4 GUI consolidation does not change
these API requests and still needs targeted GUI confirmation.

| Local GET endpoint | Purpose | Required result |
| --- | --- | --- |
| `/proxy/network/integration/v1/info` | Application version | `applicationVersion` string in stable 10.6 or 11.0 series |
| `/proxy/network/integration/v1/sites` | Accessible sites | Valid paginated sites with UUID, name and internalReference |
| `/proxy/network/integration/v1/sites/{siteId}/devices?limit=1` | Authenticated device-read capability | Valid page, including an empty inventory |

Authentication uses `X-API-KEY` from the local console's integration settings.
No cloud connector, user/password login, internal endpoint fallback or mutation is
implemented. The adapter only sends GET. Missing endpoints report Unsupported;
permission failures report Unauthorized rather than Online. Versions outside the
validated stable 10.6 and 11.0 families report Unsupported until explicitly
validated; pre-releases are always Unsupported.

On 2026-11-14 the installed console reported Network 11.0.99. An
assistant-executed read-only live check on the developer workstation confirmed
the three endpoints above plus paginated device reads (19 devices, 3 pages)
with the same response shape the adapter expects. The 11.0 published schema was
not compared separately. Network 11.0 devices in this installation expose no
serial numbers through the Integration API.

Site discovery follows offset pagination with at most ten pages of up to 200 sites.
A blank site auto-selects only one accessible site; multiple sites require an
unambiguous ID, display name or internal reference. Zero accessible sites reports
Partial. Discovered choices are returned for the settings UI without persisting
them automatically. Network device operating status is unrelated to API status.

Requests have fixed timeouts and never follow redirects or retry automatically.
TLS checks default on and use the configured private CA if supplied. Disabled TLS
checks are per connection; environment proxy settings are ignored for this local
adapter. Errors do not echo URLs, response bodies, keys or exception text.

Port profiles, overrides, VLANs, LLDP, PoE and other inventory field coverage are
not established by this connection gate; those remain the M3/M6 capability work.

## Port and VLAN Coverage (M6)

Read-only probe on 2026-11-14 against the installed Network 11.0.99 (19 devices,
195 ports), assistant-executed on the developer workstation:

| Source | Port and VLAN data |
| --- | --- |
| Official `sites/{id}/devices/{id}` | Per port: `idx`, `state` (UP/DOWN), `connector` (RJ45, SFP, SFPPLUS, SFP28), `maxSpeedMbps`, `speedMbps` (only when up), `poe` (`standard`, `type`, `enabled`, `state`); `features.switching.lags`; `uplink.deviceId` without port |
| Official `sites/{id}/networks` | Network name, `vlanId`, `enabled`, `management`, IPv4 host address and prefix length |
| Official, not available | Port names, configured port enable state, port profiles, overrides, native/tagged VLANs per port, LLDP, port MAC addresses (`port-profiles`, `vlans` return 404) |
| Internal `api/s/{site}/stat/device` | `port_table` with names, `enable`, `aggregated_by`, PoE, speed, uplink marker; `lldp_table` |
| Internal `api/s/{site}/rest/portconf` | Port profiles with native network and tagged VLAN rule |
| Internal `api/s/{site}/rest/networkconf` | Networks with VLAN and subnet; also contains secrets, so only allow-listed fields may be read |

Port configuration resolution (0.6.6, live read-only on 2026-11-14 against
Network 11.0.99): internal devices map to official devices by MAC (19 of 19).
Port entries hold their override values; a port with `portconf_id` takes
`forward`, `native_networkconf_id`, `tagged_vlan_mgmt` and
`excluded_networkconf_ids` from the profile. `forward` values seen: `all`,
`native`, `disabled`, `customize` (with `tagged_vlan_mgmt` `auto`, `block_all`
or `custom`). The default network has no VLAN (`vlan_enabled` false) and is
VLAN 1. `link_aggregation_groups` was present but empty on all 13 switches and
`aggregated_by` false on every port, so LAG handling is covered by offline tests
only. Internal network IDs differ from the official network IDs; networks are
related by VLAN ID. Result: 195 of 195 ports resolved (90 `tagged-all`, 46
`access`, 57 `disabled`, 2 `tagged`) without unknown profiles or networks.

The official API therefore leaves a demonstrated coverage gap for M6. Internal
endpoints are used read-only, gated to the validated 11.0 series and covered by
version-specific fixtures; see the M6 decision in `IMPLEMENTATION_PLAN.md`.

## Device Type Sources (M12)

Public, read-only sources, used only on a user action (Settings switches in
`[device_types]`); only a model slug or library file path is sent.

| Source | Access | Data used |
| --- | --- | --- |
| GitHub API `repos/{repo}/git/trees/{branch}` and the `device-types` subtree (`?recursive=1`) | on **Refresh index** | file paths and blob SHAs of `device-types/<Manufacturer>/<file>.yaml`; the index is cached as `library-index.json` |
| `raw.githubusercontent.com/{repo}/{branch}/device-types/...` | when a library type is chosen | the definition YAML, cached by blob SHA |
| `techspecs.ui.com/unifi/{category}/{slug}` | **Look up specs** / **New** for Ubiquiti | `__NEXT_DATA__` `props.pageProps.product`: `slug`, `title`, `variants[].sku`, `technicalSpecification.sections[].features[]` (Dimensions, Form Factor, Weight, Max. Power Consumption, Power Method, Port Layout, Networking Interface) |

Live check (2026-11-16, read-only): the library index lists 14,433 files of
455 manufacturers (one request, not truncated); techspecs pages resolve for
USW-Pro-24, U6-Lite, UDM-Pro, USW-Lite-8-POE, UA-Intercom, U6+ and
UVC-G5-Bullet. An invalid category in the URL redirects to a category page and
an unknown slug serves the home page, so a hit requires a product page whose
slug equals the request. SKUs may carry a regional suffix (`U6-Lite-US`),
which is dropped for the part number. The bundled JSON schema comes from
`schema/` of the library (CC0, see `resources/devicetype-schema/SOURCE.txt`).

NetBox writes for imports (M13): `dcim/device-types` with every writable
field (owner, default platform and tags by ID, custom fields, cooling method,
end of life, exclude from utilization) and the template endpoints
`console-port-`, `console-server-port-`, `power-port-`, `power-outlet-`,
`interface-` (parent and bridge set by `PATCH` afterwards), `rear-port-`,
`front-port-` (`rear_ports`: `position`, `rear_port`, `rear_port_position`),
`module-bay-`, `device-bay-`, `cooling-intake-`, `cooling-outflow-` and
`inventory-item-templates` (parent, role, manufacturer, `component_type` and
`component_id`). Front and rear images: multipart `PATCH` of
`front_image`/`rear_image` on the new type. `module_bay_types` is not sent.
Before writing, the import reads `dcim/manufacturers`, `users/owners`,
`dcim/platforms`, `extras/tags` and `dcim/inventory-item-roles` by name or
slug.

The field lists come from `resources/netbox-metadata/netbox-4.7.json`,
written by `tools/update_netbox_metadata.py` from `OPTIONS` requests
(read-only) on `dcim/device-types`, all template endpoints and the objects
below; regenerate it for a new NetBox series.

NetBox catalog for the editor (read-only, paginated, on open and **Reload
from NetBox**): `dcim/manufacturers`, `dcim/platforms`, `users/owners`,
`users/owner-groups`, `extras/tags`, `dcim/inventory-item-roles`,
`extras/custom-fields` (those whose `object_types` include
`dcim.devicetype`) and `extras/custom-field-choice-sets`.

NetBox writes from the **New...** dialogs (one object per confirmed dialog,
looked up by name and slug first, read back, saved to the write history):
`dcim/manufacturers` (name, slug, description), `dcim/platforms` (+
manufacturer), `users/owner-groups` (name, description), `users/owners`
(name, group, description), `extras/tags` (name, slug, color, description)
and `dcim/inventory-item-roles` (name, slug, color, description).

Device type comparison and sync (M14). Reads (GET, paginated, on editor
open and **Reload from NetBox**): `dcim/device-types` and all 12 template
endpoints unfiltered (about 14 requests; 377 types in 1.4 s on the
developer NetBox), grouped by `device_type`. Before a sync: the type and its
templates by `device_type_id` (drift check and read-back), for the preflight
`dcim/devices?device_type_id=` and, when height or depth change for racked
devices, `dcim/racks/{id}` and `dcim/devices?rack_id=`; when the subdevice
role changes `dcim/device-bays?device_id=`. Writes (only after the
confirmed sync): `PATCH dcim/device-types/{id}` with the chosen fields
(references by ID), `POST` of new templates (dependency order as on
import), `PATCH` of changed templates and of front ports' `rear_ports`,
`PATCH` of interface `parent`/`bridge`, multipart image upload. Never:
deleting device types or templates, or changing devices.

## Extended UniFi Details (M11)

Read-only probe on 2026-11-15 against Network 11.0.99, assistant-executed on
the developer workstation with the local API key (status codes and counts
only): the internal endpoints used by the earlier script project still answer
(`stat/sysinfo`, `stat/device`, `stat/sta`, `rest/user`, `rest/networkconf`,
`rest/portconf`, `rest/wlanconf`, `rest/firewallgroup`, `rest/portforward`,
`stat/rogueap`, `stat/ccode`: HTTP 200; `rest/firewallrule`, `rest/routing`,
`rest/dynamicdns`: empty; `rest/tag`: HTTP 400). No login with user name and
password is needed.

| Source | Fields kept (allow-list) |
| --- | --- |
| Official `sites/{id}/devices` | `ipAddress` (IPv4 only), `firmwareVersion` |
| Internal `stat/device` `port_table` | `sfp_found`, `sfp_vendor`, `sfp_part`, `sfp_serial`, `sfp_compliance`, `sfp_rev` |
| Internal `stat/device` `port_overrides`, `rest/portconf` | `autoneg`, `speed`, `full_duplex` (fixed speed only when `autoneg` is false; the override wins over the profile) |
| Internal `rest/networkconf` | `dhcpd_enabled`, `dhcpd_start`, `dhcpd_stop` plus name, purpose and VLAN |
| Internal `rest/wlanconf` | `_id`, `name` (SSID), `enabled`, `security`, `wpa_mode`, `wpa_enc`, `networkconf_id`, `hide_ssid`, `is_guest`; never `x_passphrase` or any other `x_*` field |
| Internal `rest/user` | only rows with `use_fixedip`: `mac`, `fixed_ip`, `name`, `hostname`, `local_dns_record` (when `local_dns_record_enabled`) |

Live result (application 1.0.1): 19 of 19 devices with IP and firmware, 18
ports with a fixed speed (all set by port overrides; both profiles use
auto-negotiation), 23 SFP modules with serial, 15 DHCP ranges, 6 wireless LANs
(WPA2 personal and enterprise, all with a network) and 139 reservations (3
with a local DNS record; only 54 carry `network_id`, so reservations are
related to networks by subnet). Notes: the `port_table` `speed` is the live
link speed and `autoneg` there also reads false for some SFP+ ports without a
configured speed, so neither is used as configuration. `poe_caps` is an
undocumented bit mask; PoE capability is taken from the official
`poe.standard` instead.

NetBox mapping of the site-level details (slice 6, NetBox 4.7.3; wireless LAN
scope needs NetBox 4.2 or later):

| UniFi | NetBox object | Fields |
| --- | --- | --- |
| `rest/wlanconf` | `wireless/wireless-lans` | `ssid`; `status` active/disabled; `auth_type` from `security` (`open`, `wep`, `wpapsk` = `wpa-personal`, `wpaeap` = `wpa-enterprise`); `auth_cipher` from `wpa_enc` (`ccmp`/`gcmp` = `aes`, `tkip`, `auto`); `vlan` from the site VLAN group; `scope_type`/`scope_id` the site |
| `rest/networkconf` DHCP pool | `ipam/ip-ranges` | `start_address`/`end_address` with the network prefix length, `status` active, `description` `DHCP <network>` |
| `rest/user` fixed IP | `ipam/ip-addresses` | `address` with the prefix length of the containing UniFi network, `status` reserved, `dns_name`, `description`; never assigned |

## UniFi Protect Connection Gate (M7)

Protect runs on its own console with its own local API key; the Network
console's key and URL are not reused. Read-only probe on 2026-11-14 against the
UDM Pro Max (Network console): `/proxy/protect/integration/v1/meta/info`,
`nvrs` and `cameras` returned HTTP 200 with `text/html` (the UniFi OS page), so
Protect is not installed there. The gate therefore treats HTML answers as
"no Protect".

Read-only probe on 2026-11-14 against the UNVR (assistant-executed on the
developer workstation, application 0.7.1): Protect reports version 7.3.74 and
the check is Online (7.3 series). Field coverage of the official API:

| Endpoint | Fields | Not available |
| --- | --- | --- |
| `meta/info` | `applicationVersion` | - |
| `nvrs` (one object, not a list) | `id`, `guid`, `name`, `mac`, `modelKey` (`nvr`), `type` (hardware code, e.g. `UNVR4`), arm mode and doorbell settings | serial, firmware, IP, storage |
| `cameras` (list, 10 entries) | `id`, `guid`, `name`, `mac`, `modelKey` (`camera`), `type` (model, e.g. `UVC G4 Instant`), `state` (`CONNECTED`/`DISCONNECTED`), video, HDR, LED, OSD, mic and smart-detect settings, feature flags | serial, firmware, IP, manufacturer |
| `cameras/{id}` | same fields as the list | - |

Observations: `type` is the only model field; three cameras are third-party
(`CAM-PT2`) without a manufacturer field, and one entry is a UniFi Access
intercom (`UA Intercom`) listed as a camera. Matching can therefore use MAC and
name only; the manufacturer must not be assumed.

| Endpoint | Purpose |
| --- | --- |
| `/proxy/protect/integration/v1/meta/info` | Application version (gate: 7.3 series) |
| `/proxy/protect/integration/v1/nvrs` | NVR read access |
| `/proxy/protect/integration/v1/cameras` | Camera read access |

## UniFi Access Connection Gate (M8)

Read-only probe on 2026-11-14 (assistant-executed, application 0.8.0): the UNVR
answers `/proxy/access/...` with its HTML page (no Access); the UDM answers
`/proxy/access/...` with JSON 404 errors and `https://<udm>:12445/api/v1/developer/devices`
with HTTP 401 when called without an Access token. Access therefore runs on
the UDM and needs an Access API token created in the Access app; the Network
key is not accepted. The developer API reports no application version, so the
user-reported Access 4.3.22 is recorded instead of a version gate.

| Endpoint | Purpose |
| --- | --- |
| `https://<console>:12445/api/v1/developer/devices` | Device read access (Bearer token, `SUCCESS` envelope, devices grouped per hub) |

Device fields observed live on 2026-11-14 (application 0.8.1, UAH hub and
UA-Intercom): `id`, `name`, `alias`, `type`, `is_adopted`, `is_online`,
`is_connected`, `is_managed`, `location_id`, `connected_uah_id` and
`capabilities`. There is no MAC or serial field; the 12-digit hex `id` is the
MAC address (the intercom ID equals the MAC Protect reports for it). Serial
numbers, firmware and IP addresses are not reported and stay unsupported.

| Field | Snapshot value |
| --- | --- |
| `alias`, else `name` | device name |
| `type` | model (for example `UAH`, `UA-Intercom`) |
| `id` (12 hex digits) | MAC address |
| `capabilities` (`is_hub`, `is_reader`) and `type` | kind: hub, reader, intercom or access |
| `is_online` | state online/offline (operational, display only) |
| `is_adopted` = false | device skipped |

## UniFi Drive Connection Gate (M9)

Read-only probe on 2026-11-14 (assistant-executed, application 0.9.0, no
credentials sent): the developer portal index (`developer.ui.com/llms.txt`)
lists Network, Protect, Site Manager and others, but no Drive or UNAS API.
The UNAS Pro answers `/api/system` with JSON including `hardware.shortname`
(`UNASPRO`), `mac` and `name`, but no serial or firmware. Every
`/proxy/drive/...` path answers 401 JSON, including a nonexistent one, so the
gateway authenticates before routing and no Drive endpoint is confirmed. The
Network and Protect integration paths return the UniFi OS HTML page.

| Endpoint | Purpose |
| --- | --- |
| `https://<unas>/api/system` | Public UniFi OS system information (model, system MAC); used by the Drive check |
| `https://<unas>/proxy/drive/api/v2/storage` | Internal Drive endpoint (local API key): drive bays and pools; used for the drive inventory |

With the stored local API key (2026-11-14, application 0.9.1) unknown
`/proxy/drive/...` paths answer 404 instead of 401, so the key is accepted;
`/proxy/drive/integration/v1/...` does not exist. The storage endpoint is
internal and undocumented; only these drive-bay fields are kept: `slotId`,
`model`, `serial`, `firmware`, `type`, `size`, `state`, `temperature`,
`healthScore` and `poolId`. SMART counters, throughput, RAID and pool
details are ignored. On the tested UNAS Pro `healthScore` was 5 for healthy
disks (scale not documented), empty bays report `state` "empty".

## Installed-Version Field Capability Matrix

M3 now provides a service-level matrix builder for installed-version capability
tracking of ports, profiles, overrides, VLAN, PoE, speed/duplex, LAG and LLDP.
The matrix records:

- installed UniFi and NetBox versions,
- generation timestamp,
- per-field UniFi evidence signal,
- intended NetBox target mapping,
- status (`Verified`, `Unverified` or `Missing`) and implementation note.

Without sampled field evidence, matrix entries are intentionally `Unverified`
rather than assumed supported. Evidence-backed states are derived from observed
payload keys and remain read-only diagnostics at this stage.