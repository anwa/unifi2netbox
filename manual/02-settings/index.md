# Settings

Open **Settings** with the settings button in the header, right of
**Manual**. The dialog has one page per service plus the sync defaults:

- [NetBox](01-netbox.md): required.
- [UniFi Network](02-unifi-network.md): required.
- [UniFi Protect](03-unifi-protect.md), [UniFi Access](04-unifi-access.md)
  and [UniFi Drive](05-unifi-drive.md): optional.
- [Sync defaults](06-sync-defaults.md): NetBox site, default role and the
  scope of NetBox-only devices.

## Buttons

- **Check connections** tests the values currently entered on all pages,
  without saving.
- **Save** checks the connections and writes all pages together. If a check
  or the write fails, nothing is saved.
- **Cancel** discards all changes.

## Common fields

Every connection page has the same basic fields:

| Field | Meaning |
| --- | --- |
| Base URL | `https://host` or `https://host:port`, optionally with a reverse-proxy path; without `/api`, user, query or fragment |
| Token / API key | the secret of that service; hidden unless **Show** is checked |
| Verify TLS certificate | on by default; switch off only for testing (the chip turns amber) |
| CA bundle | a private CA file to trust a self-signed certificate instead of switching verification off |
| Request timeout | 1 to 60 seconds per request |

Use `https://` wherever possible: with `http://` tokens travel unencrypted.

## Where the settings are stored

- Windows: `%LOCALAPPDATA%\unifi2netbox\config.toml`
- Linux: `~/.config/unifi2netbox/config.toml`

Tokens are stored there in plain text. Protect the file and never share it.
See [Files and data](../05-reference/03-files-and-data.md).
