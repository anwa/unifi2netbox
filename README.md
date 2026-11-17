# unifi2netbox

Latest main release: **v1.2.0** (M12 device types: picker, editor, local
folder and devicetype-library, import). Download the Windows installer or the
Ubuntu `.deb` from the
[GitHub releases](https://github.com/anwa/unifi2netbox/releases).

Release **v1.2.0** compares UniFi Network inventory with NetBox in a modern
review window (light and dark mode), explains matches, conflicts and Device
Type suggestions, and applies selected, confirmed changes to NetBox with
re-reads before writing, read-back verification afterwards and a saved write
history. Beyond devices it covers VLANs and prefixes, switch port
configuration on NetBox interfaces, cable suggestions from LLDP and,
optionally, the NVR and cameras of UniFi Protect, the hubs, readers and
intercoms of UniFi Access and a UNAS with its drives (UniFi Drive), plus
firmware (Custom Field `firmware`), management IPs, port details, SFP
modules, wireless LANs, DHCP ranges and reservations. UniFi stays read-only.
See [API capabilities](docs/API_CAPABILITIES.md) for the reference schemas and
version-specific verification limits.

Python desktop application for reviewing UniFi inventory differences before
applying selected changes to NetBox. The capabilities below are part of
release v1.2.0; see [CHANGELOG.md](CHANGELOG.md) for the version-by-version
history.

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
- The **Networks** filter lists the UniFi networks and plans NetBox IPAM for
  the configured NetBox site: a VLAN group "UniFi <site>", one VLAN per enabled
  network and a site-scoped prefix per subnet linked to its VLAN. Existing VLAN
  names are aligned and missing prefix VLANs filled in; conflicts (a prefix
  linked to another VLAN, duplicate prefixes or VLAN IDs) are shown but never
  written. Disabled networks are reference-only. Network writes use the same
  re-read, read-back and history safeguards as device writes.
- With UniFi Network 11.0 the port list also shows each port's name and
  effective configuration (mode, native and tagged VLANs, profile, LAG), read
  from internal Network endpoints with GET only. All-VLAN trunks stay
  `tagged-all`; unknown profiles or networks are reported, never guessed.
- With UniFi Protect configured, the NVR and cameras appear as devices in the
  same review (marked "from UniFi Protect"). Devices also seen in UniFi Network
  are taken from Network. Cameras and NVRs never get the default network role:
  create a fitting NetBox role (for example "Camera", "NVR") or choose one per
  device. Third-party cameras get a device type only on an exact model match.
- With UniFi Access configured, hubs, readers and intercoms appear the same
  way (marked "from UniFi Access"). For the same MAC, Network wins over
  Access and Access over Protect. Access reports no serial numbers.
- The **Interfaces** filter compares the effective UniFi port configuration
  with the paired NetBox interfaces of matched devices and offers field-level
  writes for enabled state, 802.1Q mode, untagged and tagged VLANs, the
  description (UniFi port name), a fixed speed and duplex (only without
  auto-negotiation) and the PoE mode and type. Other existing NetBox values
  are shown but only replaced when checked. VLANs come
  from the site's "UniFi <site>" VLAN group, so write the networks first and
  refresh. Interfaces are only updated, never created or deleted; LAGs and
  cables are not changed, and a second apply after a refresh writes nothing.
- The **Cables** filter lists links that UniFi reports between devices
  (wired uplinks and LLDP). A NetBox cable is suggested only when the evidence
  agrees on both ports, both ends are interfaces of matched devices and neither
  has a cable; suggestions seen twice are preselected. Existing cables are
  never changed or deleted.
- For matched switches, the detail panel lists each UniFi port with its
  NetBox interface (paired by connector kind and number), connector and speed,
  live link state and PoE, plus notes for speed or PoE differences and
  unpaired ports or interfaces. Link state and speed are never written.
  Plugged SFP modules (part number, tooltip with vendor and serial) and
  configured fixed speeds are shown as well. SFP modules of matched devices
  can be written as NetBox inventory items `Transceiver <interface>` linked
  to their interface (create and update only, never deleted).
- Firmware is a device field: the version UniFi reports is written into the
  NetBox Custom Field `firmware`. If NetBox has no such field, the detail panel
  offers "Create the NetBox Custom Field 'firmware'" (preselected, created once
  before any device write); unchecking it also unchecks firmware. An existing
  field of another type is never changed and blocks firmware writes.
- The management IP that UniFi reports becomes the NetBox primary IPv4 of a
  matched device (checkbox in the detail panel). The IP is put on the
  management-only interface, or on a virtual `Management` interface that is
  created when missing; the prefix length comes from the UniFi network. An
  existing other primary IPv4, an IP assigned elsewhere and public (WAN)
  addresses are never written.
- The **Wireless** filter lists the UniFi wireless LANs as NetBox wireless
  LANs for the configured site: SSID, status, authentication type and cipher
  and the VLAN of the site VLAN group (passphrases are never read). Disabled
  WLANs are shown but not preselected.
- The **Addresses** filter lists management IPs, DHCP pools as NetBox IP
  ranges (`DHCP <network>`) and fixed client IPs as reserved, unassigned IP
  addresses (DNS name only from an enabled local DNS record, description
  from the client name). Existing objects are only completed; a different
  VLAN, site, DNS name or description, overlapping ranges and duplicates
  are conflicts and never written.
- The **Modules** filter lists the SFP modules of matched devices.
- In these lists each entry has a checkbox; the detail panel shows the
  planned fields with names instead of NetBox IDs. **Select all** and
  **Select none** act on the visible list.
- NetBox-only devices (delete proposals) are limited to the active UniFi site
  by default; a setting includes all NetBox devices. Nothing is deleted.

### Main window

The window follows the system light or dark mode and is organized around one
workflow: connect, refresh, review, apply. The moon/sun button next to
**Settings** switches between light and dark; its arrow menu offers **Follow
system**. The choice is saved as `[ui] theme` (`system`, `light` or `dark`).
On Windows the native title bars of all windows follow the theme too (dark
in dark mode; on Windows 11 in the app's own colors, blending into the
header), and the app has its own icon in title bars, taskbar and executable.

- The header shows a status chip per connection (green online, amber online
  with a security warning, red on errors). Click a chip for endpoint, version,
  last check and **Check again**. **Refresh** (F5) reads both inventories;
  **Manual** (F1), **Settings** and a **More** menu (write history, UniFi API
  dump, copy summary) sit next to it.
- **Device types** opens the device type editor: the local type folder
  (`device-types/<Manufacturer>/<model>.yaml`, devicetype-library form,
  extended by every NetBox device type field) as a tree, each definition as a
  table with field explanations or raw YAML, validated against the library
  schema plus the NetBox fields and `CONTRIBUTING.md`; Ubiquiti models
  can be completed from techspecs.ui.com. New devices choose their type in a
  picker modeled on NetBox's (filters, search across NetBox, the local folder
  and netbox-community/devicetype-library, **New** from UniFi data); a chosen
  definition that NetBox lacks is imported as a visible write step with all
  NetBox fields, template kinds and images. Owner, platform, tags,
  manufacturer and inventory item roles are drop-downs read from NetBox;
  **New...** creates such an object in NetBox after you confirm the small
  dialog (never sites or device roles).
- **Manual** opens the user manual from [`manual/`](manual/index.md): the
  chapter tree on the left, the page with screenshots on the right, starting
  at the overview. The same Markdown pages can be read on GitHub.
- Summary cards count new devices, devices with changes, devices in sync,
  devices that need attention and NetBox-only devices; clicking a card filters
  the table. Filter chips and a name/model search narrow the list further.
- The review table lists one device per row with a checkbox, the change type,
  the UniFi model, the NetBox match or chosen device type and a status
  (Ready, Needs attention, Not selected, Written, Skipped, Failed).
- The detail panel for the selected device shows its fields side by side. For
  changed devices, a checkbox per writable field selects what is written. For
  new devices, it offers NetBox device type, role, site and status; unambiguous
  type suggestions are preselected. It also offers **Apply this device**,
  **Export UniFi data** and **Copy details**.
- The apply bar shows the selection, **Select all** / **Select none**,
  **Dry run (no changes)** and **Apply N changes**. Results appear in the table
  and in a banner, with **Refresh now** after real writes.
- UniFi dumps contain unsanitized inventory data; never commit or share them
  unreviewed.

### Approved NetBox writes

- Selected previews become an ordered write plan (creates before updates) with
  preflight blockers and one summary confirmation. Creates need a default
  NetBox device role in Settings or a per-row role.
- **Apply N changes** asks once, then writes; **Dry run (no changes)** records
  the outcomes without changing NetBox. **Apply this device** in the detail
  panel runs a single device, for example when other rows block the full plan.
- Right before writing, UniFi is re-read: a device whose selected UniFi
  values changed since the preview, or that UniFi no longer reports, is
  skipped. If UniFi cannot be read, nothing is written.
- Before each write, NetBox is re-read: an update is skipped if the target
  device was deleted or a selected field changed since the preview, and a
  create is skipped if a device with the same name or serial appeared
  meanwhile. Refresh the preview and review the row before retrying.
- If a create is interrupted (timeout, dropped connection, HTTP 502/503/504),
  the app never retries it blindly: it looks the device up in NetBox and
  reports it as created (with ID), safe to retry after a refresh, or in need of
  a manual check.
- After writing, each successful device is read back from NetBox and marked
  **Verified**, **Mismatch** (NetBox holds other values) or **Not verified**
  (read-back failed). The app never writes again on its own.
- Every run is saved to `write-journal.sqlite3` next to the configuration;
  **More > Write history** shows recent runs with per-device results.
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
	 unapproved Custom Fields (the only one is `firmware`, created visibly on
	 selection). Network first, then Protect, Access and Drive.
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
| Windows | Windows 11; installer, upgrade and read-only workflow accepted on the developer workstation (2026-11-14) |
| Linux | Ubuntu/Kubuntu 26.04 LTS/26.10 targeted; `.deb` and tarball built and smoke-tested offscreen on Ubuntu 24.04 in CI; real desktop not verified |
| Network | Network 11.0.99 live-verified read-only on the developer workstation (2026-11-14); 10.6 series accepted per M2 user-reported tests |
| Protect | UNVR 6.0.11 / Protect 7.3 series; 7.3.74 live-verified read-only plus an approved NetBox write test (2026-11-14) |
| Access | 4.3.22 (user-reported; the API reports no version); developer API live-verified read-only plus an approved NetBox write test (2026-11-14) |
| Drive | UNAS Pro 6.0.11 / Drive 4.4.20; no documented API, public system info and internal storage endpoint live-verified read-only plus an approved NetBox write test (2026-11-14) |

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
`--break-system-packages`. On Windows the app can also be installed per user
with the installer built by `tools/build_windows.ps1`
(`unifi2netbox-<version>-setup.exe`, no administrator rights); upgrades and
uninstall keep your settings in `%LOCALAPPDATA%\unifi2netbox`. For Ubuntu, a
`.deb` and a standalone tarball are built by the **Packages** workflow
(CI-tested offscreen only; a real Linux desktop is not verified yet). See [deployment instructions](docs/DEPLOYMENT.md); real
settings/tokens are never bundled.

## Start

After activating `.venv` and installing the requirements:

```powershell
python -m unifi2netbox
```

Alternatively run `unifi2netbox`, or `python -m unifi2netbox --config PATH` to use
an explicit local TOML file. `python -m unifi2netbox --version` prints the installed
version. Reinstall requirements after checking out a new commit so package metadata
and the displayed version stay current.

First start opens **Settings** with three pages: **NetBox**, **UniFi Network**
and **Sync defaults**. Enter each service's URL and token/key and choose its
independent TLS/CA options. **Check connections** tests both pages' current
unsaved values; it does not save. **Save** validates both connections and
atomically writes all sections together, then rechecks both saved connections.
If validation or saving fails, nothing is written. **Cancel** discards all
changes. Tokens remain masked by default.

On the **UniFi Network** page, enter the console base URL and a local
integration API key. If the key exposes one site, Automatic selects it.
Otherwise, choose a discovered site from the editable Site menu or enter its
unique ID/name/internal reference, then test again and Save. Selecting a
discovered entry saves its ID, not its display label. Device inventory read
access is required for Online; a reachable console, an offline switch or an
invalid key are different conditions.

**Sync defaults** holds the NetBox site for UniFi devices, the default device
role for new devices and whether NetBox-only devices from all sites are listed.

Both saved connections are checked independently at startup and shown as
header chips. One failing service does not hide the other's result. Only
**Apply** writes to NetBox. A close request waits asynchronously for all active
checks to finish; the window stays responsive and each request keeps its
configured timeout.

## Configuration and Security

Default local TOML configuration, outside the repository:

NetBox uses `[netbox]`; UniFi Network uses `[unifi_network]` with its own `url`,
`token` (local API key), `site`, `verify_tls`, `ca_bundle` and `timeout`. An absent
UniFi section is unconfigured and does not affect an existing NetBox connection.
The dialog saves both sections together and preserves unrelated settings/comments.
A blank site permits discovery of a single accessible site; multiple sites require
explicit selection. UniFi Protect is optional and uses `[unifi_protect]` with the
`url`, `token` (local API key of the Protect console), `verify_tls`, `ca_bundle`
and `timeout` of the console running Protect, which may differ from the Network
console. UniFi Access is optional too and uses `[unifi_access]` with the Access
API URL (port 12445 of the console running Access) and an Access API token
with device-read permission. UniFi Drive is optional as well and uses
`[unifi_drive]` with the UNAS console URL and a local API key; until Ubiquiti
documents a Drive API only the public system information and the internal
storage endpoint (drive bays: model, serial, firmware, size, state) are read.
The UNAS appears as one device; its drive bays are listed in the details.
Once the UNAS exists in NetBox, its drives can be written as inventory items
(`Disk <slot>`: part ID, serial, description); items are never deleted.
Optional services show a header chip once set.

- Windows: `%LOCALAPPDATA%\unifi2netbox\config.toml`.
- Linux: `${XDG_CONFIG_HOME:-~/.config}/unifi2netbox/config.toml`.

[config.example.toml](config.example.toml) contains placeholders. Enter an explicit
`http://` or `https://` base URL without `/api`, credentials, query or fragment.
Reverse-proxy subpaths are supported; port 8000 does not determine the scheme.

TLS verification defaults on. Use a private CA file or explicitly disable checks
per connection. Self-signed certificates can be trusted with the correct CA.
HTTP transmits tokens unencrypted; disabled verification weakens authentication.
Tokens are initially plaintext locally, not encrypted. Restrict file access.
Never commit real configuration, tokens, logs, raw captures, inventory caches
or the write journal.

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
