# Implementation Plan

Approved scope: Python desktop inventory comparison from UniFi to NetBox.
Implementation started on `feature/netbox-connection`. No merge is authorized.
M1 is implemented and locally tested. The user reported all NetBox online tests
passed on 2026-10-25. Linux/exact-platform verification and merge approval remain open.

## Requirements and Environment

- Python >=3.15.1; PySide6 Qt Widgets; English GUI, code and documentation.
- Windows 11 25H2/26H2; Ubuntu and Kubuntu 26.04 LTS/26.10.
- One local UniFi site/controller initially. UDM Pro Max: OS 5.1.33,
  Network 10.6.100. UNVR: 6.0.11, Protect 7.3.70. Access: 4.3.22.
  UNAS Pro: 6.0.11, Drive 4.4.20. Applications may use separate consoles.
- NetBox Community 4.7.3, netbox-docker 5.1.1. Addresses, explicit HTTP/HTTPS
  schemes, tokens, site and role choices are runtime inputs, not hardcoded defaults.
- This development PC cannot reach the infrastructure. The user can clone the
  exact branch/commit and execute documented acceptance tests on the target PC.
- UniFi is read-only. NetBox changes are selected and explicitly confirmed.
  No automatic deletion, automatic background writes or unapproved Custom Fields.
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
3. Normalize serial/MAC/source IDs and deduplicate cross-application observations.
   One nonempty identity can find a candidate, but contradictory/duplicate
   identities block automatic matching. Names/IP/model similarity are suggestions.
4. Only unmatched devices receive Device Type suggestions, ranked by manufacturer,
   exact model, aliases and explainable fuzzy similarity. No type match means an
   explicit missing-type state, not an invented type or external catalog import.
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
- [ ] Obtain explicit merge approval; prepare minor version and release tag.

Acceptance: settings survive restart, valid authenticated inventory access reports
Online, failures are distinguishable, no GUI blocking and no API mutations.

### M2: UniFi Network Connection -> v0.2.0

Branch: `feature/unifi-network-connection`; depends on M1.

- [ ] Add Network host/key/site/TLS settings and independent status checks.
- [ ] Detect installed application version and authenticated endpoint capability.
- [ ] Use controller-specific documentation for 10.6.100; published 10.6.106
  documentation does not establish installed endpoint coverage.
- [ ] Test independent failures, startup checks and read-only request behavior.
- [ ] Perform target-PC read acceptance and document capability gaps.

Acceptance: NetBox and Network independently display authenticated connectivity.

### M3: Inventory, Snapshots and Diagnostics -> v0.3.0

Branch: `feature/inventory-snapshots`; depends on M2.

- [ ] Read paginated inventories into normalized, timestamped domain models.
- [ ] Add versioned SQLite state, current/previous complete snapshots and Refresh.
- [ ] Add stale/offline browsing and partial-read diagnostics, without writes.
- [ ] Provide opt-in sanitized fixture/report export for the target PC.
- [ ] Build an installed-version field capability matrix for ports, profiles,
  overrides, VLANs, PoE, speed/duplex, LAG and LLDP.

Acceptance: complete reads are repeatable; failures preserve a good baseline;
exports contain no credentials/personal data and remain useful as test fixtures.

### M4: Matching and Difference Preview -> v0.4.0

Branch: `feature/diff-and-device-matching`; depends on M3.

- [ ] Implement identity conflicts, confirmed mappings and cross-source deduplication.
- [ ] Suggest existing manufacturer/model Device Types only for missing devices.
- [ ] Display source/target values, provenance, operational/configured category,
  unsupported fields and field/device/batch checkboxes.
- [ ] Create immutable change previews with explicit dependencies, without writes.

Acceptance: ambiguous matches never auto-apply; unavailable values never erase
targets; selecting a device selects eligible displayed fields, with exceptions.

### M5: Approved NetBox Inventory Writes -> v0.5.0

Branch: `feature/approved-netbox-writes`; depends on M4.

- [ ] Implement creation prerequisites and selected standard inventory updates.
- [ ] Add preflight conflicts, one summary confirmation and ordered execution.
- [ ] Journal outcomes, reconcile ambiguous creates and read back successful writes.
- [ ] Test zero writes on Cancel, partial failures, concurrent edits and idempotence.

Acceptance: exactly the confirmed changes are attempted; dependent failures are
visible; live write tests require explicit narrow test scope and separate opt-in.

### M6: Switch Ports and VLANs -> v0.6.0

Branch: `feature/ports-and-vlans`; depends on M5 and M3 capabilities.

- [ ] Resolve profile inheritance and per-port overrides into effective settings.
- [ ] Map native/tagged VLANs with correct groups/scopes and explicit all-VLAN
  semantics; do not silently expand unrestricted VLANs to a current finite list.
- [ ] Map interfaces, MAC/IP associations, management primary IP and LAG according
  to the real NetBox 4.7 schema. PoE/speed need verified standard target fields.
- [ ] Suggest cables only with unambiguous physical endpoint evidence/approval.
- [ ] Test disabled versus down, unknown profiles, VLAN collisions and numbering.

Acceptance: correct effective configuration, no lifecycle/operational confusion,
no unsupported writes and no redundant changes on a second apply.

### M7: Protect Inventory -> v0.7.0

Branch: `feature/protect-inventory`; follows M6.

- [ ] Verify Protect 7.3.70 inventory/NVR endpoints and credentials per console.
- [ ] Add camera/NVR hardware inventory, status, matching and approved NetBox flow.
- [ ] Deduplicate devices also visible in Network; never collect recordings/streams.

Acceptance: camera/NVR fixtures and target-PC read verification; existing common
approval and conflict handling remains effective.

### M8: Access Inventory -> v0.8.0

Branch: `feature/access-inventory`; follows M7.

- [ ] Validate Access 4.3.22 API documentation, console placement and token scopes.
- [ ] Add supported hubs/readers/equipment, never users, access logs or door control.
- [ ] Record unsupported hardware fields instead of promising complete coverage.

Acceptance: version-specific fixtures and target-PC read verification; source is
read-only even when the API token itself has broader permissions.

### M9: Drive/UNAS Inventory -> v0.9.0

Branch: `feature/drive-inventory`; follows M8.

- [ ] Verify Drive 4.4.20 / UNAS Pro 6.0.11 inventory APIs and authentication.
- [ ] Add verified chassis/interface/hardware inventory with cross-source matching.
- [ ] Keep unsupported storage metrics display-only; never access file contents.

Gate: suitable Drive API coverage is not yet established. Network client visibility
is not full hardware inventory. Stop for a decision if no suitable endpoint exists;
do not substitute SSH or scraping without approval.

### M10: Deployment and Platform Acceptance -> v0.10.0

Branch: `feature/deployment`; follows supported prior milestones.

- [ ] Finalize native Windows executable and Ubuntu-compatible package (proposed
  `.deb` plus standalone build). Packaging feasibility is checked already in M1.
- [ ] Include Qt plugins/license notices; never bundle real settings/cache/tokens.
- [ ] Preserve per-user settings on upgrades and document uninstall data policy.
- [ ] Run source and packaged GUI checks on available requested OS versions.

Acceptance: verified install/start/settings/read/preview workflows. Unavailable
platforms stay explicitly unverified rather than being marked supported by CI.

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
- Target-PC workflow: clone exact commit, install pinned requirements in `.venv`,
  configure through GUI, perform read-only checks, return a sanitized report with
  application/commit/Python/OS/API versions. Write tests are separately opted in.
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