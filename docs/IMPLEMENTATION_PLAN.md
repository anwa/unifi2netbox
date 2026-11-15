# Implementation Plan

Approved scope: Python desktop inventory comparison from UniFi to NetBox.
Implementation started on `feature/netbox-connection`. On 2026-10-25, the user
explicitly approved the M1 merge to main and the v0.1.0 release tag.
M1 is completed for release v0.1.0. The user reported all NetBox online tests
passed on 2026-10-25. Linux/exact-platform verification remains open.

## Requirements and Environment

- Python >=3.15.1; PySide6 Qt Widgets; English GUI, code and documentation.
- The installed UDM Pro Max reported Network 11.0.99 on 2026-11-14 (planned:
  10.6.100). Both the 10.6 and 11.0 stable series are accepted by the gate.
- Windows 11 25H2/26H2; Ubuntu and Kubuntu 26.04 LTS/26.10.
- One local UniFi site/controller initially. UDM Pro Max: OS 5.1.33,
  Network 10.6.100. UNVR: 6.0.11, Protect 7.3.70. Access: 4.3.22.
  UNAS Pro: 6.0.11, Drive 4.4.20. Applications may use separate consoles.
- NetBox Community 4.7.3, netbox-docker 5.1.1. Addresses, explicit HTTP/HTTPS
  schemes, tokens, site and role choices are runtime inputs, not hardcoded defaults.
- The developer workstation (from 2026-11-14) has direct access to NetBox and
  UniFi; live acceptance runs there. The external developer notebook used
  earlier has no access. Earlier "target PC" results were user-reported.
- UniFi is read-only. NetBox changes are selected and explicitly confirmed.
  No automatic deletion, automatic background writes or unapproved Custom Fields
  (the only approved one is `firmware`, created visibly on selection; see M11).
- Network first; later inventory of cameras, NVRs, Access hardware and UNAS.
  Exclude recordings, file contents, personal access data and device controls.

## Architecture

- `pynetbox` behind a NetBox adapter; `httpx` behind application-specific UniFi
  adapters. Avoid dynamic API records in GUI/domain models.
- Official local UniFi endpoints first. Add internal read endpoints only for
  required missing fields, documenting source precedence and version coverage.
- GUI-editable TOML using `tomllib` and `tomlkit`; atomic configuration writes.
  Use `platformdirs` for per-user configuration/data paths.
- SQLite snapshots, confirmed identity mappings and apply journal from M3 onward.
- Bounded Qt worker pool with queued result signals; no network calls in widgets.
- Separate configuration, adapters, connection services and GUI. Add modules
  when needed, rather than creating empty scaffolding for future milestones.
- One authoritative package version; pinned pip requirements and `.venv` workflow.

## Workflow Contracts

1. Startup loads settings and checks authenticated connectivity independently.
   Online means authenticated inventory reads work, not merely host reachability.
2. Later startup may show the last complete snapshot, clearly timestamped/stale.
   Refresh retrieves current data without writing. Failed/partial scans preserve
   the last complete baseline and never imply deletion.
3. Deduplicate cross-application observations per UniFi device in strict order:
  normalized name, then serial, then MAC. One nonempty criterion can yield a
  candidate; duplicate candidates in the active pass are ambiguity conflicts.
4. Only unmatched devices receive Device Type suggestions, ranked by manufacturer,
  exact model, aliases and explainable fuzzy similarity using NetBox Device
  Templates (dcim device types). No type match means an explicit missing-type
  state, not an invented type or external catalog import.
5. Select existing NetBox site, role, type, VLAN group and IP scope as needed.
   Missing prerequisite taxonomy blocks creation with an actionable message.
6. Keep configured values separate from operational values. Link down must not
   disable an interface; device offline must not change its lifecycle status.
   Unknown/unavailable, null, empty and present values are distinct.
7. Preview device/field/batch selections and dependencies. Confirm once for the
   displayed plan; no repeated confirmation for each field of an approved device.
8. Re-read affected source/target values before writes. Changed preview values
   block the operation until reviewed. Offline snapshots cannot authorize writes.
9. Order writes by dependencies; report success/failure/skipped per operation.
   Cross-object changes are not globally transactional. Never blindly retry a
   timed-out create: reconcile server identities first. Re-read successful writes.
10. No hidden unrelated changes, automatic rollback, deletion or secret capture.
    Repeated refresh/apply with no differences must be idempotent.

## Milestones

Each milestone is one task branch with several small tested commits. Each release
below is created only after an approved merge. Finish M1 before starting M2.

### M1: NetBox Connection -> v0.1.0

Branch: `feature/netbox-connection`.

- [x] Inspect repository and preserve user-authored changes.
- [x] Resolve Windows Python 3.15 dependency packages without bypassing constraints.
- [x] Verify Python 3.15.1 imports, TOML roundtrip and a Qt Widgets startup/exit.
- [x] Record project rules and this implementation plan.
- [x] Add package metadata, pinned requirements and configuration tests.
- [x] Implement validated, atomically saved TOML and outside-repository defaults.
- [x] Implement authenticated NetBox read/version check with bounded timeouts.
- [x] Implement nonblocking status window and GUI-editable settings.
- [x] Cover first start, malformed configuration, masking, save/cancel, TLS,
  401/403, timeout, refusal, unsupported version, responsiveness and shutdown.
- [x] Update English README, changelog and testing/connection reference docs.
- [x] Verify a native packaging smoke build and its startup on available Windows.
- [x] Run target-PC NetBox acceptance; record missing Linux/OS verification
  (user-reported online test success on 2026-10-25; see `TESTING.md`).
- [x] Obtain explicit merge approval (2026-10-25); prepare version 0.1.0.
- [x] Complete the approved main merge and tag its resulting commit v0.1.0.

Acceptance: settings survive restart, valid authenticated inventory access reports
Online, failures are distinguishable, no GUI blocking and no API mutations.

### M2: UniFi Network Connection -> v0.2.0

Branch: `feature/unifi-network-connection`; depends on M1.

Status: the user reported the preceding M2 online tests passed on 2026-10-25.
On 2026-10-28, the user confirmed the revised 0.1.4 shared Settings and Check
Connections workflow on the target PC. The user then approved the M2 merge to
main and v0.2.0 release preparation.

- [x] Add independent UniFi TOML storage without changing existing NetBox settings
  (v0.1.1: 62 offline tests pass, optional package test skipped).
- [x] Add Network host/key/site/TLS settings and independent status checks.
- [x] Detect installed application version and authenticated endpoint capability
  (v0.1.2: local API adapter, 94 offline tests pass; live confirmation pending).
- [x] Use available published 10.6.106 schemas as a reference only; the 10.6.100
  documentation URL returned 404. Installed coverage requires target-PC checks.
- [x] Test independent failures, startup checks and read-only request behavior.
- [x] Run local M2 gates: 101 offline tests pass, optional package test skipped in
  the default run; Ruff lint/format and editor diagnostics pass. Normal/compact
  GUI screenshots reviewed with synthetic data. Fresh Windows standalone 0.1.3
  startup/shutdown passes in a separately enabled native test.
- [x] Record user-reported target-PC online test success for the preceding M2
  workflow (2026-10-25; exact artifact and environment details not supplied).
- [x] Implement shared settings/check actions and atomic combined saving in 0.1.4:
  109 offline tests, Ruff lint/format and editor diagnostics pass; fresh native
  Windows startup/shutdown passes separately. Both tabs/compact layout reviewed.
- [x] Confirm the revised 0.1.4 shared Settings and Check Connections workflow on
  the target PC (user-reported pass on 2026-10-28). Keep independent TLS/site
  settings and atomic combined saves.
- [x] Obtain explicit merge approval (2026-10-28); prepare version 0.2.0.
- [x] Complete the approved main merge and tag its resulting commit v0.2.0.

Acceptance: NetBox and Network independently display authenticated connectivity.

### M3: Inventory, Snapshots and Diagnostics -> v0.3.0

Branch: `feature/inventory-snapshots`; depends on M2.

Status: completed for release v0.3.0 (merge commit 17f5fc3, tag v0.3.0).

- [x] Read paginated inventories into normalized, timestamped domain models
  (initial internal NetBox/UniFi readers plus offline contract tests on
  2026-10-28).
- [x] Add versioned SQLite state, current/previous complete snapshots and
  internal Refresh service foundations (offline contract tests on 2026-10-28).
- [x] Add stale/offline browsing and partial-read diagnostics, without writes
  (cache browse service and refresh diagnostics with offline contract tests on
  2026-10-28).
- [x] Provide opt-in sanitized fixture/report export for the target PC
  (deterministic pseudonymization and offline contract tests on 2026-10-28).
- [x] Build an installed-version field capability matrix for ports, profiles,
  overrides, VLANs, PoE, speed/duplex, LAG and LLDP (service-level matrix
  builder and offline contract tests on 2026-10-28).
- [x] Obtain explicit merge approval; complete version-only release preparation
  for 0.3.0 on main.
- [x] Complete the approved main merge and tag its resulting commit v0.3.0.

Acceptance: complete reads are repeatable; failures preserve a good baseline;
exports contain no credentials/personal data and remain useful as test fixtures.

### M4: Matching and Difference Preview -> v0.4.0

Branch: `feature/diff-and-device-matching`; depends on M3.

Status: completed for release v0.4.0. On 2026-11-14 the user explicitly
approved the merge to main and the v0.4.0 release. The branch also contains
early M5 write slices; M5 stays open (source-side re-read before writes).

- [x] Implement identity conflicts, confirmed mappings and cross-source
  deduplication (service-level matching core and offline contract tests on
  2026-10-28).
- [x] Suggest existing manufacturer/model Device Types only for missing devices
  (read-only ranked suggestions and offline contract tests on 2026-10-28).
- [x] Display source/target values, provenance, operational/configured category,
  unsupported fields and field/device/batch checkboxes (service-level preview
  model and offline contract tests on 2026-10-28).
- [x] Create immutable change previews with explicit dependencies, without writes
  (service-level dependency model and offline contract tests on 2026-10-28).
- [x] Match UniFi models to NetBox device types by part number and alias, and
  map the UniFi site to a NetBox site (offline tests and live read-only checks
  on 2026-11-14).
- [x] Run live acceptance on the developer workstation (read-only checks and an
  approved NetBox developer-instance write test on 2026-11-14).
- [x] Obtain explicit merge approval (2026-11-14); prepare version 0.4.0.
- [x] Complete the approved main merge and tag its resulting commit v0.4.0.

Acceptance: ambiguous matches never auto-apply; unavailable values never erase
targets; selecting a device selects eligible displayed fields, with exceptions.

### M4.5: GUI Redesign -> v0.5.0

Branch: `feature/gui-redesign`; depends on M4. Added on 2026-11-14 at the
user's request before continuing M5; later milestones shift by one minor
version.

Status: completed for release v0.5.0. On 2026-11-14 the user approved the look
on the developer workstation and explicitly approved the merge to main and the
v0.5.0 tag.

- [x] Modern look: Fusion-based theme that follows the system light/dark mode,
  status colors and native Windows icons where available.
- [x] Review-centric main window: connection chips, summary cards, filterable
  review table with device selection, a detail panel with per-device choices
  and field-level selection, and an apply bar. Replaces the `Show all rows`
  dialog and the highlight list.
- [x] Apply flow: one confirmation summary, optional dry run first, per-row
  results in the table.
- [x] Settings dialog grouped into NetBox, UniFi Network and sync defaults.
- [x] Keep every existing capability (exports, single-row execution, copy of
  details) reachable; update GUI tests and documentation (0.4.1, 2026-11-14;
  offscreen light/dark screenshots reviewed; Windows desktop rendering
  approved by the user).
- [x] Add a light/dark theme button next to Settings (0.4.2).
- [x] Obtain explicit merge approval (2026-11-14); prepare version 0.5.0.
- [x] Complete the approved main merge and tag its resulting commit v0.5.0.

Acceptance: the workflow connect -> refresh -> review -> apply works in one
window without extra dialogs except confirmation and settings; light and dark
mode render legibly; no service-layer behavior changes.

### M5: Approved NetBox Inventory Writes -> v0.6.0

Branch: `feature/approved-netbox-writes`; depends on M4.

Status: completed for release v0.6.0. On 2026-11-14 the user explicitly
approved the merge to main and the v0.6.0 tag.

- [x] Implement creation prerequisites and selected standard inventory updates
  (service-level write-plan model and offline contract tests on 2026-11-01).
- [x] Add preflight conflicts, one summary confirmation and ordered execution
  (service-level preflight blockers, deterministic operation ordering and
  immutable plan summaries with confirmation readiness on 2026-11-01).
- [x] Journal outcomes, reconcile ambiguous creates and read back successful writes.
  (journal outcome model, ambiguous-create reconcile helper, read-back planner
  and offline contract tests implemented on 2026-11-01)
- [x] Test zero writes on Cancel, partial failures, concurrent edits and idempotence
  (service-level journal/read-back/write-plan contract tests on 2026-11-01).
- [x] Add service-level device write executor for create/update with dry-run and
  deterministic outcome journaling (offline contract tests on 2026-11-01).
- [x] Map the UniFi site to a configured NetBox site and guard against writing
  site names that do not exist in NetBox (offline tests and live read-only
  check on 2026-11-14).
- [x] Re-read NetBox targets before each write and skip operations whose preview
  baseline changed (deleted/changed update targets, newly appeared create
  duplicates by name/serial; offline contract tests and approved live write
  test against the NetBox developer instance on 2026-11-14). The source-side
  UniFi re-read followed in 0.5.3.

- [x] Read back successful writes and mark them verified, mismatch or
  unverified, without automatic rewrites (offline tests, 0.5.1, 2026-11-14).
- [x] Reconcile timed-out creates against NetBox before reporting failure
  (offline tests, 0.5.2, 2026-11-14).
- [x] Re-read affected UniFi source devices before writes (offline tests,
  0.5.3, 2026-11-14).
- [x] Persist write journals in SQLite and show recent runs (offline tests,
  0.5.4, 2026-11-14).
- [x] Live acceptance of read-back, UniFi re-read and write history on the
  developer workstation (read-only checks plus an approved NetBox developer-
  instance write test, 6/6, 2026-11-14).
- [x] Obtain explicit merge approval (2026-11-14); prepare version 0.6.0.
- [x] Complete the approved main merge and tag its resulting commit v0.6.0.

Acceptance: exactly the confirmed changes are attempted; dependent failures are
visible; live write tests require explicit narrow test scope and separate opt-in.
For delete proposals, default scope remains safety-first (site-scoped NetBox-only
devices), with an explicit user setting to include all NetBox devices when needed.

### M6: Switch Ports and VLANs -> v0.7.0

Branch: `feature/ports-and-vlans`; depends on M5 and M3 capabilities.

Status: completed for release v0.7.0. On 2026-11-14 the user explicitly
approved the merge to main and the v0.7.0 tag.

Decision (2026-11-14, user-approved): the official Network 11.0 Integration
API exposes per port only index, link state, connector, speeds and PoE, so it
cannot provide port names, configured enable state, port profiles, native or
tagged VLANs, LAG membership or LLDP (see `API_CAPABILITIES.md`). Internal
Network endpoints fill that gap and are used read-only: GET only, enabled for
the validated 11.0 series, an explicit field allow-list (secrets such as WAN
passwords are never read into models, stored or exported), marked as
`internal` provenance, and the official data keeps working when they fail.

Slices, in this order:

- [x] 1. Read UniFi ports and NetBox interfaces; match ports to interfaces of
  matched devices by connector family and numbering; show them per device.
  Operational state (link, speed) is display-only and never written.
  (0.6.1, 2026-11-14: offline tests and live read-only check; the UDM Pro Max
  pairs 11/11 ports, a USW Aggregation shows 24 surplus NetBox interfaces.)
- [x] 2. Create NetBox VLANs (in a site-scoped VLAN group) and prefixes from
  UniFi networks, with preview and approval.
  (0.6.5, 2026-11-14: offline tests, live dry run of 31 operations and an
  approved live write of one network: group, VLAN and prefix verified, second
  apply a no-op, test objects removed.)
- [x] 3. Read internal port configuration: names, configured enable state,
  profiles plus overrides resolved to effective native/tagged VLANs (all-VLAN
  trunks stay explicit `tagged-all`, never expanded), LAG membership.
  (0.6.7, 2026-11-14: offline tests and live read-only check, 195 of 195 ports
  resolved without notes; no LAG configured live, so LAG is offline-tested.)
- [x] 4. Write interface configuration (enabled, mode, untagged/tagged VLANs,
  LAG) with field-level preview and approval; a second apply is a no-op.
  (0.6.10, 2026-11-14: offline tests, live dry run of 19 interfaces and an
  approved live write of two interfaces, verified, second apply a no-op, all
  restored. Decision: LAG membership stays display-only because NetBox needs
  separate LAG interfaces that are not created automatically; no LAG exists
  live.)
- [x] 5. Suggest cables only from unambiguous LLDP/uplink evidence, with
  explicit approval.
  (0.6.13, 2026-11-14: offline tests, live dry run and an approved live write
  of one cable, verified, second apply a no-op, cable removed.)
- [x] Test disabled versus down, unknown profiles, VLAN collisions and
  numbering; live read-only checks and an approved dev-instance write test.
  (Offline: `test_port_config.py`, `test_networks.py`, `test_ports.py`; live
  read-only checks and approved write tests for networks, interfaces and
  cables are recorded in `TESTING.md`.)

- [x] Obtain explicit merge approval (2026-11-14); prepare version 0.7.0.
- [x] Complete the approved main merge and tag its resulting commit v0.7.0.

Acceptance: correct effective configuration, no lifecycle/operational confusion,
no unsupported writes and no redundant changes on a second apply.

### M7: Protect Inventory -> v0.8.0

Branch: `feature/protect-inventory`; follows M6.

Status: completed for release v0.8.0. On 2026-11-14 the user explicitly
approved the merge to main and the v0.8.0 tag.

Decision (2026-11-14, user-approved): Protect gets its own optional connection
(`[unifi_protect]`, URL and local API key of the console running Protect,
edited in Settings); the Network key is not reused. Scope: cameras and the NVR;
other Protect hardware (lights, sensors, chimes, viewers) may follow later.
Live probe: the UDM serves no Protect API (HTML answer).

Slices:

- [x] 1. Optional Protect connection: config section, settings page, header
  chip and read-only check of info, NVRs and cameras (0.7.1).
- [x] 2. Read NVR and cameras into a Protect snapshot after verifying the
  7.3.70 fields live. (0.7.2, 2026-11-14: live 7.3.74, 11 devices.)
  Decision (user-approved): third-party cameras are read and shown, but only
  proposed for creation when NetBox already has a device type with exactly
  that model; the manufacturer is never assumed. The Access intercom listed by
  Protect is treated as a camera and noted for M8.
- [x] 3. Match and preview Protect devices with the existing flow,
  deduplicated by MAC against Network devices. (0.7.3, 2026-11-14: live
  preview with 11 Protect create rows, 6 with a device type; roles open.)
- [x] 4. Approved NetBox writes for Protect devices and live acceptance.
  (0.7.4, 2026-11-14: approved live create of one camera with a test role,
  verified, matched after refresh, removed; 7/7.)

- [x] Verify Protect 7.3.70 inventory/NVR endpoints and credentials per console.
  (2026-11-14: installed 7.3.74 on the UNVR, Online with its own local API key;
  fields recorded in `API_CAPABILITIES.md`.)
- [x] Add camera/NVR hardware inventory, status, matching and approved NetBox flow.
  (Slices 2 to 4; the Protect state is shown, never written.)
- [x] Deduplicate devices also visible in Network; never collect recordings/streams.
  (MAC dedup in favor of Network; only `meta/info`, `nvrs` and `cameras` are
  requested, no snapshot, recording or stream endpoints.)

- [x] Obtain explicit merge approval (2026-11-14); prepare version 0.8.0.
- [x] Complete the approved main merge and tag its resulting commit v0.8.0.

Acceptance: camera/NVR fixtures and target-PC read verification; existing common
approval and conflict handling remains effective.

### M8: Access Inventory -> v0.9.0

Branch: `feature/access-inventory`; follows M7.

Status: completed for release v0.9.0. On 2026-11-14 the user explicitly
approved the merge to main and the v0.9.0 tag.

Decision (2026-11-14, user-approved): Access gets its own optional connection
(`[unifi_access]`: Access API URL with port 12445 and an Access API token with
device-read permission). Source precedence for the same MAC: Network, then
Access, then Protect. Live probe: Access runs on the UDM; the UNVR has none.

Slices:

- [x] 1. Optional Access connection: config section, settings page, chip and
  read-only device check (0.8.1).
- [x] 2. Verify the Access device fields live and read hubs, readers and other
  hardware into an Access snapshot; never users, logs or door control (0.8.2).
- [x] 3. Match and preview Access devices (precedence Network, Access,
  Protect) and record unsupported hardware fields (0.8.3).
- [x] 4. Approved NetBox writes for Access devices and live acceptance
  (0.8.3, live write test 7/7).

- [x] Validate Access 4.3.22 API documentation, console placement and token scopes.
- [x] Add supported hubs/readers/equipment, never users, access logs or door control.
- [x] Record unsupported hardware fields instead of promising complete coverage.
- [x] Obtain explicit merge approval (2026-11-14); prepare version 0.9.0.
- [x] Complete the approved main merge and tag its resulting commit v0.9.0.

Acceptance: version-specific fixtures and target-PC read verification; source is
read-only even when the API token itself has broader permissions.

### M9: Drive/UNAS Inventory -> v0.10.0

Branch: `feature/drive-inventory`; follows M8.

Status: completed for release v0.10.0. On 2026-11-14 the user explicitly
approved the merge to main and the v0.10.0 tag.

Gate finding (2026-11-14, read-only): Ubiquiti's developer portal lists no
Drive or UNAS API. The UNAS Pro (one device: management 1G and data 10G SFP+
interfaces, both visible as UniFi Network clients) answers the public UniFi OS
`/api/system` with model and system MAC; `/proxy/drive/...` answers 401 for
any path; the Network and Protect integration paths return HTML only.

Decision (2026-11-14, user): add a UniFi Drive settings page with URL and
local API key like Access, so a future Drive API can be used; until then
only the public system information is read.

Slices:

- [x] 1. Optional Drive connection: config section, settings page, chip and
  read-only system-information check; key stored, not sent (0.9.1).

Finding (2026-11-14, read-only with the stored key): the UNAS accepts its
local API key (unknown `/proxy/drive/...` paths then answer 404 instead of
401); there is no integration path, but the internal
`/proxy/drive/api/v2/storage` endpoint returns drive bays (model, serial,
firmware, type, size, state, temperature, health, pool) and pools.

Decision (2026-11-14, user): drives become NetBox inventory items of the UNAS
device (create and update only, never delete); operational values stay
display-only.

- [x] 2. Read the UNAS (public system information) and its drive bays
  (internal storage endpoint, GET, allow-listed fields) into a Drive
  snapshot; match and preview the UNAS; show bays display-only (0.9.2).
- [x] 3. Plan and write drives as NetBox inventory items of the matched UNAS
  (name, part ID, serial, description) with re-read, drift checks and
  read-back; never delete (0.9.3).
- [x] 4. Approved NetBox write test and live acceptance (0.9.3, 9/9).

- [x] Verify Drive 4.4.20 / UNAS Pro 6.0.11 inventory APIs and authentication.
- [x] Add verified chassis/interface/hardware inventory with cross-source matching.
- [x] Keep unsupported storage metrics display-only; never access file contents.
- [x] Obtain explicit merge approval (2026-11-14); prepare version 0.10.0.
- [x] Complete the approved main merge and tag its resulting commit v0.10.0.

Gate: suitable Drive API coverage is not yet established. Network client visibility
is not full hardware inventory. Stop for a decision if no suitable endpoint exists;
do not substitute SSH or scraping without approval.

### M10: Deployment and Platform Acceptance -> v1.0.0

Branch: `feature/deployment`; follows supported prior milestones.

Status: completed for release v1.0.0. On 2026-11-14 the user explicitly
approved the merge to main, authorized the major version (v1.0.0 instead of
the planned v0.11.0) and a public GitHub release with the installers.

Decisions (2026-11-14, user): Windows ships as a per-user Inno Setup installer
(Start menu entry, in-place upgrades, uninstaller that keeps the per-user
configuration and data). Linux (`.deb` plus standalone build) is built and
smoke-tested offscreen by a GitHub Actions workflow on Ubuntu; a real Linux
desktop check stays explicitly unverified until the user runs it. WSL is not
installed on the developer workstation.

Slices:

- [x] 1. Windows installer: Inno Setup script (per-user install under
  `%LOCALAPPDATA%\Programs\unifi2netbox`, Start menu shortcut, icon, license,
  upgrade by AppId, uninstall keeps `%LOCALAPPDATA%\unifi2netbox`) and one
  build script for exe plus installer (0.10.2/0.10.3; silent install,
  upgrade and uninstall tested on the workstation).
- [x] 2. Linux packaging: PyInstaller standalone build and `.deb` (`/opt`,
  launcher, `.desktop` entry, icons) built by a GitHub Actions workflow with
  an offscreen smoke test; artifacts only, no public release without approval
  (0.10.4; CI on Ubuntu 24.04, real desktop unverified).
- [x] 3. License notices and bundle hygiene check (no settings, cache or
  tokens in any package); uninstall and upgrade data policy documented
  (both build scripts check the bundle; Qt platform, image-format, style and
  TLS plugins are bundled; notices list PyInstaller and Inno Setup).
- [x] 4. Acceptance on the workstation: install, start, settings, read and
  preview from the installed Windows app; upgrade over a previous install
  (0.10.3 -> 0.10.4 on Windows 11; chip overlap found and fixed in 0.10.5).

- [x] Finalize native Windows executable and Ubuntu-compatible package (proposed
  `.deb` plus standalone build). Packaging feasibility is checked already in M1.
- [x] Include Qt plugins/license notices; never bundle real settings/cache/tokens.
- [x] Preserve per-user settings on upgrades and document uninstall data policy.
- [x] Run source and packaged GUI checks on available requested OS versions
  (Windows 11 on the workstation; Ubuntu only offscreen in CI, real Linux
  desktops and Ubuntu/Kubuntu 26.04 stay unverified).
- [x] Obtain explicit merge approval (2026-11-14); prepare version 1.0.0.
- [x] Complete the approved main merge and tag its resulting commit v1.0.0.

Acceptance: verified install/start/settings/read/preview workflows. Unavailable
platforms stay explicitly unverified rather than being marked supported by CI.

### M11: Extended UniFi Details -> v1.1.0

Branch: `feature/unifi-details`; follows M10.

Gate finding (2026-11-15, read-only with the stored API key): the internal
Network endpoints used by the earlier script project still answer with the
local API key on Network 11.0 (`stat/device`, `stat/sta`, `rest/user`,
`rest/networkconf`, `rest/portconf`, `rest/wlanconf` and others: HTTP 200;
`rest/tag`: 400; `rest/firewallrule` is empty under zone-based firewalls).
The official Integration API already returns `firmwareVersion` and
`ipAddress` per device, which the app did not keep.

Decisions (2026-11-15, user):

- Scope: management IP and firmware, port details, SFP modules, wireless LANs
  plus DHCP ranges and reservations.
- The management IP is assigned to an existing management-only interface; if
  there is none, a virtual `Management` interface (management only) is planned
  as a visible, selectable create.
- Firmware goes into the device Custom Field `firmware` (label "Firmware",
  text, `dcim.device`). If it is missing, the app plans its creation as a
  separate, visible and selectable first operation; a field with an
  incompatible type or object type blocks firmware writes. This is the only
  Custom Field the app creates, and never silently.
- Unchanged: UniFi is read with GET and field allow-lists only (no `x_*`
  secrets, no WLAN passphrases); internal fields stay limited to the validated
  11.0 series; nothing is deleted; missing source values never clear NetBox
  values; re-read, drift skip, read-back and journal for every write.

Slices:

- [ ] 1. Read and show: device IP and firmware (official API); SFP, configured
  speed/duplex and PoE per port, DHCP ranges, wireless LANs (no secrets) and
  fixed-IP reservations (internal API); NetBox primary IPv4, firmware Custom
  Field, interface description/duplex, IP addresses, IP ranges, wireless LANs
  and manufacturers. Snapshot fields with defaults; pseudonymized export.
- [ ] 2. Firmware: plan and create the `firmware` Custom Field when missing;
  firmware as a device field for updates and creates.
- [ ] 3. Management IP: IP address on the management interface (create the
  virtual interface when needed) and primary IPv4; conflicts never overwrite.
- [ ] 4. Port details: description from the UniFi port name, speed/duplex
  only when auto-negotiation is off, PoE mode/type as port capability.
- [ ] 5. SFP modules as inventory items linked to their interface (create and
  update only), sharing the inventory-item logic of the drive items.
- [ ] 6. Wireless LANs (SSID, VLAN, status, authentication type/cipher, site
  scope), DHCP IP ranges and reserved IP addresses.
- [ ] 7. GUI filters, write order (custom field, networks, ranges and
  wireless, interfaces, cables, devices, IP addresses, inventory items),
  documentation, live read-only check, dry run and an approved write test on
  dedicated test objects.

- [ ] Obtain explicit merge approval; prepare version 1.1.0.
- [ ] Complete the approved main merge and tag its resulting commit v1.1.0;
  build the Windows exe and installer from the tag.

Acceptance: every new field is previewed with provenance, written only when
selected, verified by read-back, and a second apply is a no-op.

## Security and Configuration

Explicit URL schemes; no HTTP downgrade. TLS verification defaults on, with per-
service opt-out and optional private CA file. HTTP and disabled verification have
persistent warnings. Tokens are masked in the GUI and excluded from diagnostics.
Plaintext local storage is accepted initially; optional OS keyring is later work.
Atomic saves preserve unrelated TOML fields and the previous file on failure.
Settings changes invalidate old status/jobs/previews. Cache identity includes the
source environment, avoiding accidental reuse across hosts/sites.

## Git and Documentation

Every ordinary code commit increments patch from initial numeric `0.0.0`.
Pure documentation changes get neither bump nor tag. Completed approved merges
increment minor and reset patch; release preparation is version-only metadata.
Tag the resulting main release, not each development patch. Major is user-only.
Commit subject: English, type-prefixed, <=72 characters, followed by short bullets.
Commits are authorized; merges require explicit approval. Do not stage user data.

Maintain README, CHANGELOG and relevant reference docs with behavior changes.
Create testing, API capability, mapping and deployment references as those slices
are implemented. Update milestone checkboxes with evidence, not intentions.

## Verification

- Focused offline tests after each substantive edit; full suite at milestone end.
- Block accidental live network in default tests; use synthetic or reviewed,
  consistently pseudonymized fixtures. Keep raw exports outside version control.
- Test GUI persistence, first-run errors, selection, signal handling and shutdown.
- Live workflow on the developer workstation: exact commit, pinned requirements
  in `.venv`, configuration through the GUI, read-only checks first; record
  application/commit/Python/OS/API versions. Live NetBox write tests need
  separate explicit approval and dedicated test objects. Opt-in live pytest
  checks use the `integration` marker and never run by default or in CI.
- Correct activation: Windows `.\.venv\Scripts\Activate.ps1`; Linux
  `source .venv/bin/activate`. Do not use system-wide pip or break system packages.
- Before each commit: tests, lint, format, staged diff, secret check and version.

### Evidence

- Windows Python 3.15.1 was installed user-locally through uv; existing Python 3.13
  was not replaced. Dry-run resolution succeeded for PySide6 6.12.0 and pynetbox
  7.9.0. A real Qt Widgets show/start/exit returned zero; TOML and API imports passed.
- Linux and exact target-OS coverage remain unverified. Native Windows packaged
  startup passed locally; live NetBox acceptance is user-reported below.
- v0.0.1: 36 offline configuration/adapter tests passed; Ruff lint passed.
- v0.0.2: 50 offline tests passed, optional package test skipped by default.
  The explicitly enabled native Windows windowed-EXE smoke test passed separately.
  Lint and editor diagnostics passed; synthetic-data Qt screenshots were reviewed.
  The real entrypoint is covered after finding/correcting a QLocale enum mismatch.
- A Windows/Linux CI definition exists but has not been executed remotely here.
- Release 0.1.0: all 50 offline tests passed (optional native package test skipped
  in the default run), Ruff lint/format passed, and a fresh Windows windowed build
  passed the separately enabled versioned-window startup/shutdown test.
- On 2026-10-25, the user confirmed all online tests passed for the current NetBox
  milestone. This is target-environment feedback, not assistant-executed live
  verification. Exact tested commit/version, source versus packaged execution,
  OS build and TLS mode were not supplied. No Linux acceptance or merge approval
  is inferred from this confirmation.
- [Qt release notes](https://doc.qt.io/qtforpython-6/release_notes/pyside6_release_notes.html)
  document initial Python 3.15 support in 6.12.
- [pynetbox](https://github.com/netbox-community/pynetbox) lists 7.9.0 / NetBox 4.7.
- [Network documentation](https://developer.ui.com/network) and
  [Protect documentation](https://developer.ui.com/protect/) are references; installed
  controller schemas/fixtures decide supported fields.