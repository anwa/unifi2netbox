# Diagnostics and export

## Copy summary

**⋯ More > Copy summary** copies the counts of the last refresh (new,
changed, in sync, attention, NetBox only, network, interface and cable
changes) and its notes to the clipboard. The notes can name devices; read the
text before sharing it.

## Copy details

**Copy details** in a device's detail panel copies that device's fields as
text, for example for a ticket.

## Export UniFi data

- **Export UniFi data** in the detail panel saves the raw UniFi record of
  the selected device.
- **⋯ More > Export UniFi API dump** saves the raw answers of the last UniFi
  read.

These exports are **not sanitized**. They contain names, MAC addresses,
serial numbers and IP addresses. Review and redact them before sharing, and
never commit them to a repository.

## Reporting a problem

Include:

- the app version (window title, or `unifi2netbox --version`),
- the NetBox and UniFi versions shown in the connection chips,
- the operating system,
- what you did, what you expected and the exact message (the detail panel
  and the [write history](../04-applying/03-write-history.md) show messages).

Never include `config.toml`, tokens or unreviewed exports.
