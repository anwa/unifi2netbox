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
| `/proxy/network/integration/v1/info` | Application version | `applicationVersion` string in stable 10.6 series |
| `/proxy/network/integration/v1/sites` | Accessible sites | Valid paginated sites with UUID, name and internalReference |
| `/proxy/network/integration/v1/sites/{siteId}/devices?limit=1` | Authenticated device-read capability | Valid page, including an empty inventory |

Authentication uses `X-API-KEY` from the local console's integration settings.
No cloud connector, user/password login, internal endpoint fallback or mutation is
implemented. The adapter only sends GET. Missing endpoints report Unsupported;
permission failures report Unauthorized rather than Online. Versions outside the
targeted stable 10.6 family also report Unsupported until explicitly validated.

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