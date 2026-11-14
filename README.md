# unifi2netbox

Latest main release: **v0.4.0**, the matching and difference preview
milestone (M4), including early approved-write (M5) slices.

Release **v0.4.0** compares UniFi Network inventory with NetBox, explains
matches, conflicts and Device Type suggestions, and lets you apply selected,
confirmed changes to NetBox. UniFi stays read-only.
See [API capabilities](docs/API_CAPABILITIES.md) for the reference schemas and
version-specific verification limits.

Python desktop application for reviewing UniFi inventory differences before
applying selected changes to NetBox. The capabilities below are part of
release v0.4.0; see [CHANGELOG.md](CHANGELOG.md) for the version-by-version
history. Approved writes (M5) are still being completed.

## Current Capabilities

### Inventory and snapshots

- Read-only, paginated NetBox and UniFi Network inventory readers normalize
  devices plus NetBox device types, roles, sites and device statuses.
- Snapshots are stored in a local SQLite file next to the configuration, with
  current/previous versions per source. Failed or partial refreshes keep the
  last good snapshot, mark it stale and report diagnostics.
- Missing UniFi vendor values default to `Ubiquiti`. If NetBox's device status
  choices endpoint is unavailable to a restricted token, statuses are inferred
  from existing devices.
- Opt-in sanitized fixture/report export pseudonymizes IDs, serials, MAC
  addresses and site labels. A capability matrix tracks which port, profile,
  override, VLAN, PoE, speed/duplex, LAG and LLDP fields are verified.

### Matching and preview

- Matching uses confirmed mappings first, then ranked passes per UniFi device:
  normalized name, serial number, MAC address. Multiple hits in one pass are an
  ambiguity conflict and are never auto-matched.
- Unmatched UniFi devices get ranked, explainable Device Type suggestions from
  existing NetBox device types, using model names, part numbers and common
  UniFi aliases. Candidates with a different port count or only a matching
  manufacturer are not suggested. An unambiguous match is preselected as the
  create row's `Device type`.
- The difference preview shows source/target values with provenance,
  configured vs. operational fields and unsupported-field markers, with batch,
  device and field selection plus explicit write dependencies.
- **NetBox site for UniFi devices** in Settings maps the UniFi site to an
  existing NetBox site for matching, creates and delete scoping. Without it, a
  UniFi site name that does not exist in NetBox is never written by updates and
  create rows show a warning until a `Device site` is chosen.
- Update rows preselect only fields the update executor can write (`name`,
  `serial`, `site`). Other differences, such as UniFi model names versus NetBox
  device types, are shown as preview-only. Empty UniFi values never clear
  NetBox values.
- NetBox-only devices (delete proposals) are limited to the active UniFi site
  by default; a setting includes all NetBox devices. Nothing is deleted.

### Main window

- **Refresh Inventory Preview** shows counts and clickable highlight lines
  (matches, conflicts, planned operations, fallback explanations), with a
  detail field and **Copy selected** / **Copy all**.
- **Show all rows** lists every preview row with action and executable-only
  filters, a `Reason` for blocked rows and `Suggested Device Types`. Create rows
  offer `Device role`, `Device site`, `Device status` and `Device type`
  dropdowns fed from the NetBox catalogs; the chosen values (including the exact
  device-type ID) are used for the create.
- **Export UniFi API dump** saves the raw UniFi API responses and device rows
  of the current preview as JSON; **Show all rows** can also export the raw
  UniFi payload of one selected row. Dumps contain unsanitized inventory data;
  never commit or share them unreviewed.

### Approved NetBox writes

- Selected previews become an ordered write plan (creates before updates) with
  preflight blockers and one summary confirmation. Creates need a default
  NetBox device role in Settings or a per-row role.
- **Execute write plan** asks once, then writes; **Dry run only** records the
  outcomes without changing NetBox. A single executable row can also be run from
  **Show all rows** when other rows block the full plan.
- Before each write, NetBox is re-read: an update is skipped if the target
  device was deleted or a selected field changed since the preview, and a
  create is skipped if a device with the same name or serial appeared
  meanwhile. Refresh the preview and review the row before retrying.
- Every operation is journaled as success, failed or skipped. NetBox rejections
  include parsed field-level details. Ambiguous creates are flagged for manual
  reconciliation and read-back requests are planned for successful writes.

## Goals

 - Read local UniFi APIs; never modify UniFi.
 - Display and approve individual fields, devices or batches before NetBox writes.
	 Approving a device does not prompt again for every field.
 - Match UniFi devices against NetBox in ranked order (name, serial, MAC), expose
	 ambiguity conflicts and suggest NetBox Device Templates (Device Types) only
	 for devices not already mapped.
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
| Network | Network 11.0.99 live-verified read-only on the developer workstation (2026-11-14); 10.6 series accepted per M2 user-reported tests |
| Protect | UNVR 6.0.11 / Protect 7.3.70; later milestone |
| Access | 4.3.22; later milestone |
| Drive | UNAS Pro 6.0.11 / Drive 4.4.20; later capability gate |

Future Python versions are not automatically certified. The user reported all
NetBox online tests passed on 2026-10-25; see the
[acceptance record](docs/TESTING.md#acceptance-record) for evidence and limitations.
Native Windows standalone startup is verified locally; Linux and exact target-OS
coverage remain unverified. Default tests use fixtures and block live sockets;
live checks run only on the developer workstation with access to NetBox and
UniFi, as explicitly opted-in `integration` tests or manual application runs.

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
live acceptance workflow on the developer workstation. Return only sanitized reports including exact
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
