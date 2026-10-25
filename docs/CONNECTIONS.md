# Connection Behavior

The first milestone supports NetBox 4.7.x through pynetbox 7.9.0. It performs
GET requests only, first to `/api/status/`, then `/api/dcim/devices/?limit=1`.
The second request checks actual inventory access, including an empty inventory.
It does not verify future write permissions. No network request occurs without
both a base URL and a token.

| Status | Meaning |
| --- | --- |
| Unconfigured | URL or token is missing |
| Checking | A background read is in progress (GUI patch) |
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