# unifi2netbox

Latest main release: **v0.2.0**, the UniFi Network connection milestone.

Release **v0.2.0** adds UniFi Network connectivity alongside NetBox with one
unified Settings dialog and one shared Check Connections action. Both services
are checked independently, results remain separate, and the local Network API
adapter stays read-only.
See [API capabilities](docs/API_CAPABILITIES.md) for the reference schemas and
version-specific verification limits.

Python desktop application for reviewing UniFi inventory differences before
applying selected changes to NetBox. This release checks both API connections;
actual inventory comparison and writes are not implemented yet.

M3 foundation work has started on `feature/inventory-snapshots`: internal
read-only paginated inventory readers and normalized timestamped snapshot models
now exist for NetBox and UniFi Network. GUI refresh/snapshot browsing and
diagnostics integration follow in later M3 slices.

## Goals

 - Read local UniFi APIs; never modify UniFi.
 - Display and approve individual fields, devices or batches before NetBox writes.
	 Approving a device does not prompt again for every field.
 - Match stable identities and expose conflicts; suggest manufacturer/model-based
	 NetBox Device Types only for devices not already mapped.
 - Cover port profiles/overrides, native/tagged VLANs, interfaces, IP/MAC, PoE,
	 LAG and LLDP where verified API data and standard NetBox fields allow it.
 - Separate configuration from operational state. No automatic deletions or
	 unapproved Custom Fields. Network first, then Protect, Access and Drive.
 - Show last successful snapshots when offline; startup checks and Refresh never
	 imply permission to write. Apply requires a confirmed current preview.

Initially support one controller/site. Equipment inventory includes cameras,
NVRs, Access hardware and UNAS where their separate APIs allow it. Recordings,
file content and personal access records are excluded. All UI/code/docs are English.

## Compatibility

| Component | Target / Evidence |
| --- | --- |
| Python | >=3.15.1; standard CPython 3.15.1 verified locally |
| GUI | PySide6 6.12.0; basic Windows startup verified |
| NetBox | Community 4.7.x; target 4.7.3 / netbox-docker 5.1.1 |
| Client | pynetbox 7.9.0 |
| Windows | Windows 11 25H2/26H2 acceptance targets |
| Linux | Ubuntu/Kubuntu 26.04 LTS/26.10; not yet tested |
| Network | UDM Pro Max OS 5.1.33 / Network 10.6.100 target; preceding M2 online tests reported passed by the user |
| Protect | UNVR 6.0.11 / Protect 7.3.70; later milestone |
| Access | 4.3.22; later milestone |
| Drive | UNAS Pro 6.0.11 / Drive 4.4.20; later capability gate |

Future Python versions are not automatically certified. The user reported all
NetBox online tests passed on 2026-10-25; see the
[acceptance record](docs/TESTING.md#acceptance-record) for evidence and limitations.
Native Windows standalone startup is verified locally; Linux and exact target-OS
coverage remain unverified. The development PC cannot reach the infrastructure;
default tests use fixtures and block live sockets.

## Installation

Install Python >=3.15.1 and check `python --version` inside `.venv`.

Windows PowerShell, with the Python launcher:

```powershell
py -3.15 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Alternatively, with uv: `uv venv --python 3.15.1 --seed .venv`, then activate and
install as above. Ubuntu/Kubuntu with a separately installed Python 3.15:

```bash
python3.15 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Install the matching venv package if required. Never replace system Python or use
`--break-system-packages`. A native Windows standalone smoke build is verified;
final installers and Linux packages remain later milestones. See
[deployment instructions](docs/DEPLOYMENT.md). Distribute the entire standalone
directory, not only the executable; real settings/tokens are never bundled.

## Start

After activating `.venv` and installing the requirements:

```powershell
python -m unifi2netbox
```

Alternatively run `unifi2netbox`, or `python -m unifi2netbox --config PATH` to use
an explicit local TOML file. `python -m unifi2netbox --version` prints the installed
version. Reinstall requirements after checking out a new commit so package metadata
and the displayed version stay current.

First start opens **Settings**, containing **NetBox** and **UniFi Network** tabs.
Enter each service's URL and token/key and choose its independent TLS/CA options.
**Check Connections** tests both tabs' current unsaved values; it does not save.
**Save** validates both tabs and atomically writes both sections together, then
rechecks both saved connections. If validation or saving fails, neither section
is written. **Cancel** discards changes in both tabs. Tokens remain masked by default.

The main window displays separate NetBox and UniFi Network status, endpoint,
version, last check and security warnings. The toolbar has one **Check Connections**
action and one **Settings** action (identified by tooltips). **File > Settings**
opens the same dialog. A shared check runs both services independently; the action
is disabled until both finish. One failing service does not hide the other's result.

Open **File > Settings > UniFi Network**, enter the console base URL and a local
integration API key, and select independent TLS/CA options. Use **Check Connections**
without saving. If the key exposes one site, Automatic selects it. Otherwise,
choose a discovered site from the editable Site menu or enter its unique ID/name/
internal reference, then test again and Save. Selecting a discovered entry saves
its ID, not its display label. Device inventory read access is required for Online;
a reachable console, an offline switch or an invalid key are different conditions.

Both saved connections are checked independently at startup. No button writes
inventory. A close request waits asynchronously for all active checks to finish;
the window remains responsive and each request still has its configured timeout.

## Configuration and Security

Default local TOML configuration, outside the repository:

NetBox uses `[netbox]`; UniFi Network uses `[unifi_network]` with its own `url`,
`token` (local API key), `site`, `verify_tls`, `ca_bundle` and `timeout`. An absent
UniFi section is unconfigured and does not affect an existing NetBox connection.
The dialog saves both sections together and preserves unrelated settings/comments.
A blank site permits discovery of a single accessible site; multiple sites require
explicit selection.

- Windows: `%LOCALAPPDATA%\unifi2netbox\config.toml`.
- Linux: `${XDG_CONFIG_HOME:-~/.config}/unifi2netbox/config.toml`.

[config.example.toml](config.example.toml) contains placeholders. Enter an explicit
`http://` or `https://` base URL without `/api`, credentials, query or fragment.
Reverse-proxy subpaths are supported; port 8000 does not determine the scheme.

TLS verification defaults on. Use a private CA file or explicitly disable checks
per connection. Self-signed certificates can be trusted with the correct CA.
HTTP transmits tokens unencrypted; disabled verification weakens authentication.
Tokens are initially plaintext locally, not encrypted. Restrict file access.
Never commit real configuration, tokens, logs, raw captures or inventory caches.

Use dedicated tokens/keys with the minimum available inventory-read permissions.
NetBox Online requires authenticated status/version and device inventory reads.
UniFi Online additionally requires an accessible, unambiguously selected site.
An empty device inventory is valid. No redirect, login or internal API fallback is
performed. The UniFi local adapter ignores environment proxies. See
[connection behavior](docs/CONNECTIONS.md) for outcomes and timeout semantics.
Malformed configuration is reported without overwriting it. Move the broken file
to a private backup outside the repository, then restart and re-enter settings.

## Development and Testing

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -m "not integration"
python -m ruff check .
python -m ruff format --check .
```

[Testing instructions](docs/TESTING.md) cover offline tests and the separate
target-PC acceptance workflow. Return only sanitized reports including exact
commit/application/Python/OS/API versions. No live writes run by default.

## Roadmap and Rules

See [the detailed plan](docs/IMPLEMENTATION_PLAN.md), [project rules](AGENTS.md)
and [changelog](CHANGELOG.md). M1 is NetBox connectivity; M2 adds independent
Network status. Inventory/snapshots, matching, approved writes, ports/VLANs,
Protect, Access, Drive and deployment follow as separate functional milestones.

Each milestone gets one branch and small commits. Ordinary code commits increment
patch; approved milestone merges increment minor and reset patch. Major changes
require user instruction. Documentation-only commits have no version/tag.
Commit messages have an English subject plus short bullets. Direct commits are
authorized; every merge to main needs explicit approval.

## License

MIT; see [LICENSE](LICENSE). Dependencies retain their respective licenses.
