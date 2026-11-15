# Files and data

All files live in one folder per user, outside the program folder:

- Windows: `%LOCALAPPDATA%\unifi2netbox`
- Linux: `~/.config/unifi2netbox`

| File | Content |
| --- | --- |
| `config.toml` | settings of all connections, **including tokens in plain text** |
| `snapshots.sqlite3` | the current and previous inventory of each source |
| `write-journal.sqlite3` | the write history |

`python -m unifi2netbox --config PATH` (or the installed program with
`--config PATH`) uses another configuration file; the two databases are
then kept next to it.

## Good practice

- Restrict access to the folder; it contains your tokens.
- Never commit these files to a repository or attach them to a ticket.
- Upgrades and uninstalling keep the folder. To remove everything, uninstall
  the app and delete the folder.
- A broken `config.toml` is reported and never overwritten. Move it to a
  private backup, restart and enter the settings again.

## Exports

**Export UniFi API dump** and **Export UniFi data** (detail panel) write the
raw UniFi answers to a file you choose. These files are not sanitized: they
contain names, MACs, serials and IPs of your network. Review them before
sharing. See [Diagnostics and export](05-diagnostics.md).
