# Connection Behavior

## UniFi Configuration Preparation

The independent `[unifi_network]` TOML section stores a console base URL, local
API key in `token`, optional site ID/name, TLS verification, private CA path and
request timeout. Omitted UniFi settings leave NetBox-only configuration working.
The shared Settings dialog writes both services in a single atomic operation and
preserves unrelated tables/comments. Version 0.1.4 includes the unified GUI and
read-only local API checks. See
[the capability matrix](API_CAPABILITIES.md) for endpoints and reference versions.

## UniFi Protect Configuration

The optional `[unifi_protect]` section stores the base URL and local API key of
the console that runs UniFi Protect (for example a UNVR), plus TLS verification,
private CA path and timeout. Without it Protect is shown as "Off" and nothing
else changes. The check sends GET requests to
`/proxy/protect/integration/v1/meta/info`, `nvrs` and `cameras`; Online means
all three succeed with a validated Protect series (7.3). A console without
Protect answers these paths with its HTML page; this is reported as
Unsupported. Recordings, snapshots and streams are never requested.

## UniFi Access Configuration

The optional `[unifi_access]` section stores the Access API base URL of the
console running Access including port 12445 (for example
`https://unifi.example.lan:12445`), an Access API token, TLS verification,
private CA path and timeout. Create the token in the Access app with
device-read permission only; the app reads devices only, even if the token
allows more. The check sends one GET to `/api/v1/developer/devices` with
`Authorization: Bearer <token>`; Online means a `SUCCESS` envelope with a
device list.

The first milestone supports NetBox 4.7.x through pynetbox 7.9.0. It performs
GET requests only, first to `/api/status/`, then `/api/dcim/devices/?limit=1`.
The second request checks actual inventory access, including an empty inventory.
It does not verify future write permissions. No network request occurs without
both a base URL and a token.

| Status | Meaning |
| --- | --- |
| Unconfigured | URL or token is missing |
| Checking | A background read is in progress |
| Online | Supported version and authenticated device read succeeded |
| Offline | Connection failed or a request timed out |
| Unauthorized | API returned 401 or 403, including missing device-read permission |
| TLS error | Certificate validation/negotiation failed |
| Unsupported | API version is outside the supported 4.7 stable series |
| Partial | UniFi API responds but exposes no site or exceeds bounded discovery |
| Error | Redirect, HTTP error, malformed JSON/schema or other invalid response |

The configured 1-60 second timeout applies separately to each request's connection
and read inactivity. It is not a hard wall-clock deadline for an entire operation;
DNS/proxy behavior and a continuously streaming response can extend elapsed time.
Automatic retries are not enabled. Redirects are refused, including login-page
and HTTP-to-HTTPS redirects; configure the final endpoint explicitly instead.

TLS verification defaults on. A configured existing CA file overrides the default
trust store only when verification is enabled. An explicit opt-out disables
verification for this connection. Plain HTTP and opt-out settings need visible
warnings. Never include URL credentials; API authentication uses the token header.
Error messages are generated locally instead of echoing remote response bodies,
URLs or exception text that could contain credentials.

TOML settings validate types and the URL before use. Missing files represent a
first-run configuration, while unreadable/malformed files report an error.
Saving uses a temporary file in the same directory, flush/fsync and atomic replace;
unrelated tables/comments are preserved. A failed replacement leaves the previous
file intact. New temporary files use restrictive permissions where the OS supports
them; Windows ACLs still depend on the user's profile configuration.

## GUI Lifecycle

First run opens settings; saved connections are checked automatically at startup.
One Settings dialog contains NetBox and UniFi Network tabs, one Check Connections
command and shared Save/Cancel buttons. The command tests both tabs' unsaved values
without touching the file. Both results appear in a summary and their respective
tabs. Invalid settings in one tab do not skip a valid other connection's check.
Save validates both tabs before replacing the file once; failures leave both
sections unchanged. Cancel discards both tabs' edits. Successful Save requests
fresh checks for both services. Superseded results cannot replace current results.

The main window has one Check Connections action and one Settings action. Status
areas remain separate. The shared check action is disabled until both main checks
finish; network failures remain service-specific.

A bounded pool runs at most two network jobs concurrently across NetBox, UniFi
and the active settings dialog; at most one job per runner is submitted. Main
window runners coalesce one requested recheck while busy. Settings fields and Save/Cancel are
disabled during a settings test; a window-close/Escape request is deferred until
both settings workers finish. Closing the main window also waits asynchronously rather
than destroying running Qt objects. No force termination of a network worker is
attempted. The UI stays responsive, but shutdown is not an immediate cancellation
of an in-flight socket request. See the timeout limitations above.

NetBox and UniFi each own their loader, immutable settings, runner and status.
An invalid section affects that connection only (invalid whole-file TOML affects
both). Saving either section preserves the other. Results for previous settings
cannot overwrite newer connection states. Closing waits for both main runners.

The UniFi tab discovers sites through the shared Check Connections command. Its editable
menu permits a site ID, name or internal reference; selecting a discovered item
persists its ID. Discovery does not save settings or initiate inventory writes.

Remote exception bodies and tokens are never displayed. Recover malformed TOML by
moving the file to a private backup and restarting; it is not silently overwritten.