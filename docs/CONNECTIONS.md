# Connection Behavior

## UniFi Configuration Preparation

The independent `[unifi_network]` TOML section stores a console base URL, local
API key in `token`, optional site ID/name, TLS verification, private CA path and
request timeout. Omitted UniFi settings leave NetBox-only configuration working.
Each service's save preserves the other service and unrelated tables/comments.
Version 0.1.1 prepares storage only; API and GUI checks are the next M2 slice.

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
The settings test uses its current unsaved values without touching the file.
Save persists validated settings atomically, clears the old status and requests a
fresh check. Results for superseded settings cannot replace the current result.

A bounded pool runs at most two checks: main window and settings test. A runner
does not queue repeated requests while busy. Settings fields and Save/Cancel are
disabled during a settings test; a window-close/Escape request is deferred until
the worker finishes. Closing the main window also waits asynchronously rather
than destroying running Qt objects. No force termination of a network worker is
attempted. The UI stays responsive, but shutdown is not an immediate cancellation
of an in-flight socket request. See the timeout limitations above.

Remote exception bodies and tokens are never displayed. Recover malformed TOML by
moving the file to a private backup and restarting; it is not silently overwritten.