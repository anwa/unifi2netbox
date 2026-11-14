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