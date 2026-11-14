# Testing

## UniFi Adapter Contracts

Local M2 evidence (2026-10-25, version 0.1.3): 101 offline tests passed, one opt-in
package test skipped by default. The separately enabled fresh Windows standalone
startup/shutdown test passed. Ruff lint/format and editor diagnostics passed.
Normal and compact Qt screenshots were checked using synthetic status results.

M2 uses synthetic `httpx.MockTransport` responses to exercise the official local
info, site-list and device-list requests. Tests cover API-key headers, read-only
methods, site pagination/selection, missing endpoints, invalid responses, denied
permissions, TLS/CA selection and timeouts. Published 10.6.106 schemas are used
as a reference; this is not live evidence for installed Network 10.6.100.
On 2026-10-25, the user reported the preceding M2 online tests passed. Exact
tested commit, execution form, Python/OS build and TLS mode were not supplied;
this is user feedback, not assistant-executed live evidence. Version 0.1.4 changes
the GUI only and needs the targeted confirmation below; the API adapter is unchanged.

## Unified Settings Confirmation

Local 0.1.4 checks passed on 2026-10-25: 109 offline tests, Ruff lint/format,
editor diagnostics and the separately enabled fresh Windows EXE startup/shutdown
test. The optional package test is skipped in the default offline suite. Both tabs
and the compact layout were inspected with synthetic results; no live API was
contacted during these development checks.

1. Start 0.1.4 with the existing configuration. Confirm only one Check Connections
	action and one Settings action appear in the main toolbar.
2. Open Settings. Confirm NetBox and UniFi Network are tabs of the same dialog,
	with both saved tokens masked and independent TLS/site settings retained.
3. Change values in both tabs and use the shared Check Connections button.
	Confirm both services report a result without saving or blocking the GUI.
4. Cancel. Reopen Settings and confirm neither tab's saved settings changed.
5. Enter valid values in both tabs and Save. Confirm both connections recheck and
	the values survive restart. Invalid values in either tab must prevent all saving.
6. Close during a shared check; confirm the application/dialog finishes both
	checks safely. Do not share real tokens or raw responses in the result report.

## UniFi Target PC Acceptance

Use the exact `feature/unifi-network-connection` commit, reinstall requirements
in `.venv`, and record `python -m unifi2netbox --version` before starting.

1. Confirm the previously configured NetBox connection still works unchanged.
2. Open Settings, then the UniFi Network page. Enter the local UDM base URL and
	local integration API key. Never use a cloud key or put a key in a report.
3. Configure TLS validation independently. Prefer the appropriate CA file; if
	explicitly disabled, verify the visible warning. Test before saving.
4. Confirm Network version 10.6.100 and successful site/device-read access. One
	accessible site works with Automatic; multiple sites require a unique choice.
5. Select a discovered site if needed, test again, then Save. Verify the selected
	site appears in the main window and survives restart along with both keys.
6. Test an invalid UniFi key: UniFi must report Unauthorized while NetBox remains
	independent. Restore the real key. Test Cancel without altering saved settings.
7. Test a closed port/unreachable console with a short timeout. UniFi reports
	Offline, the GUI stays responsive and NetBox's result remains visible.
8. Restart with both connections saved. Both checks run automatically. Close
	during checks and confirm safe completion without worker-related crashes.
9. If a required endpoint is missing or the response schema differs, report the
	status and versions only. Do not share keys, raw responses or private inventory.

All UniFi requests in this milestone are GET. No adopted-device operations, port
changes, cloud access or NetBox writes are part of these tests. Network 10.6.106
reference documentation is not a substitute for these installed-version checks.

## M3 Inventory Reader Contracts

Initial M3 groundwork adds internal read-only paginated inventory readers for
NetBox and UniFi Network, returning normalized timestamped snapshot models.
The current slice validates pagination metadata consistency, bounded page loops,
site selection behavior and normalized field extraction in synthetic tests.

Run the focused M3 contract checks:

```powershell
python -m pytest -q tests/test_inventory.py
```

This test slice remains fully offline and does not contact live infrastructure.

## M3 Snapshot State and Refresh Contracts

The second M3 slice adds a versioned SQLite snapshot store with per-source
current/previous records and an internal refresh service that writes successful
reads while preserving prior good snapshots for failed reads.

Run the focused snapshot-state checks:

```powershell
python -m pytest -q tests/test_snapshots.py tests/test_refresh.py
```

These tests remain fully offline and use synthetic readers/transports only.

## M3 Stale Browse and Partial Diagnostics Contracts

The third M3 slice adds stale/offline cache browsing and partial-refresh
diagnostics without write paths. On refresh failures, the service reports the
error, keeps the last successful snapshot available for browsing, and annotates
the result as cached/stale. Freshness checks are based on snapshot timestamps.

Run the focused diagnostics checks:

```powershell
python -m pytest -q tests/test_refresh.py tests/test_snapshots.py
```

These checks remain fully offline and use synthetic fixtures only.

## M3 Sanitized Fixture and Report Export Contracts

The fourth M3 slice adds an explicit opt-in export service for sanitized
snapshot fixtures/reports. Exports include timestamped source snapshots and
deterministically pseudonymized identifiers so fixtures remain useful while
avoiding direct leakage of source IDs, serials, MAC addresses or site labels.

Run the focused export checks:

```powershell
python -m pytest -q tests/test_reporting.py
```

This slice remains fully offline and does not contact live infrastructure.

## M3 Capability Matrix Contracts

The final M3 slice adds an installed-version field capability matrix for ports,
profiles, overrides, VLAN, PoE, speed/duplex, LAG and LLDP. Tests validate that
the matrix:

- includes all required field groups,
- defaults to `Unverified` without sampled payload evidence,
- marks evidence-backed fields as `Verified`,
- renders a stable markdown table for report output.

Run the focused matrix checks:

```powershell
python -m pytest -q tests/test_capabilities.py
```

This matrix slice remains fully offline and uses synthetic evidence only.

## M4 Matching Core Contracts

The first M4 slice adds a matching core for identity conflict handling,
confirmed mapping support and cross-source deduplication between UniFi and
NetBox observations.

The focused tests validate that:

- unique identity evidence produces one deterministic pair,
- ambiguous identity evidence is reported as an explicit conflict,
- confirmed mappings can pair observations without identity evidence,
- duplicate or missing confirmed mapping targets are reported as conflicts.

Run the focused matching checks:

```powershell
python -m pytest -q tests/test_matching.py
```

This slice remains fully offline and uses synthetic fixtures only.

## M4 Device Type Suggestion Contracts

The second M4 slice adds explainable Device Type suggestions for unmatched
UniFi observations only. Suggestions are ranked by manufacturer/model evidence
against existing NetBox manufacturer/model combinations and remain read-only.

The focused tests validate that:

- the Cables view lists links with evidence and change, offers a checkbox
	only for creatable cables and passes selected cables to the run,
- cable creates re-check UniFi evidence and both interfaces, treat an
	existing joining cable as done, never replace other cables, look up
	interrupted creates, read back every cable and write nothing in dry runs,
- link evidence comes from wired uplinks and LLDP of known UniFi devices;
	the cable plan suggests only agreeing, unclaimed, fully mapped links,
	preselects two-source evidence, never replaces cables and keeps unmatched
	devices reference-only,
- the Interfaces view lists paired ports with field checkboxes, keeps VLAN
	fields tied to the mode, counts interface writes and passes them to the run,
- interface writes patch only selected fields, skip on NetBox or UniFi drift,
	read back every write, write nothing in dry runs and run between network
	and device writes,
- the interface plan compares enabled, mode, untagged and tagged VLANs per
	paired port, uses only the site VLAN group, turns missing VLANs into notes,
	never expands `tagged-all`, never clears values for unknown configurations,
	keeps LAG display-only and ties VLAN fields to the mode selection,
- the detail panel shows port name and effective configuration per port,
	the profile as tooltip, resolution notes and why configuration is missing,
- internal port configuration resolves profiles before overrides, keeps
	all-VLAN trunks as explicit `tagged-all`, separates disabled from down,
	reports unknown profiles, networks and rules, groups LAG members, is only
	read for UniFi Network 11.0, never keeps network secrets and leaves the
	official inventory intact when the internal endpoints fail,
- the Networks view lists networks with separate VLAN and prefix checkboxes,
	counts selected network writes in the apply bar and passes them to the run,
- network writes run group -> VLANs -> prefixes with UniFi/NetBox re-reads,
	no duplicates for objects that appeared, lookup of interrupted creates,
	read-back and dry runs without writes,
- the network plan creates a site-scoped VLAN group, VLANs and prefixes,
	completes existing ones and never selects conflicts or disabled networks,
- UniFi networks carry VLAN ID and IPv4 subnet; NetBox VLAN groups, VLANs and
	prefixes are read, and missing IPAM rights are recorded instead of failing,
- UniFi ports pair with NetBox interfaces by exact connector kind, then by
	copper/optical family, in numbering order; speed, PoE and unpaired entries
	become notes, and devices without UniFi ports show no comparison,
- only unmatched UniFi observations receive suggestions,
- UniFi model names resolve to NetBox library types by model, part number or
	alias (`AC Pro` -> `UAP-AC-PRO`, `US 16 PoE 150W` -> `US-16-150W`),
- different port counts and manufacturer-only candidates are never suggested,
- only a single top exact/part-number/alias candidate is preselected,
- suggested candidates are ranked and include explainable reasons,
- no suggestions are emitted when no target catalog evidence exists.

Run the focused suggestion checks:

```powershell
python -m pytest -q tests/test_matching.py
```

This slice remains fully offline and uses synthetic fixtures only.

## M4 Difference Preview Contracts

The third M4 slice adds a service-level difference preview model that includes:

- source/target field values with explicit provenance,
- configured versus operational field categories,
- unsupported field markers for preview-only visibility,
- immutable batch/device/field selection helpers.

The focused tests validate matched/create/target-only rows and selection state
transitions without write paths.

Run the focused preview checks:

```powershell
python -m pytest -q tests/test_preview.py
```

This slice remains fully offline and uses synthetic fixtures only.

## M4 Immutable Change Preview Contracts

The fourth M4 slice adds immutable change-preview summaries with explicit
dependencies and write-readiness states, still without any write execution.

The focused tests validate that:

- target-only rows are always non-executable,
- create actions require selected non-empty `name` and `site` values,
- a configured NetBox site replaces UniFi site names before matching; without
	it, sites missing in NetBox are never selected for updates and create rows
	get an `unknown_netbox_site` warning,
- update rows only preselect writable fields (`name`, `serial`, `site`) with
	non-empty source values; other changed fields are preview-only,
- selected `model` updates depend on selected `manufacturer` updates.

Run the focused dependency checks:

```powershell
python -m pytest -q tests/test_preview.py
```

This slice remains fully offline and uses synthetic fixtures only.

## M5 Write-Plan Contracts

The first M5 slice adds a read-only write-planning layer that converts selected
immutable change previews into ordered write operations with preflight blockers,
without executing NetBox API mutations.

The focused tests validate that:

- create operations are ordered before updates,
- dependency-blocked selections are not considered executable,
- duplicate create/update targets are surfaced as explicit blockers,
- one immutable summary confirmation is generated per plan with stable counts,
- target-only rows never produce write operations,
- repeated planning over identical inputs is idempotent.

Run the focused write-plan checks:

```powershell
python -m pytest -q tests/test_write_plan.py
```

This slice remains fully offline and uses synthetic fixtures only.

## M5 Write-Journal Contracts

The next M5 micro-slice adds an immutable write-journal model for operation
outcomes and run summaries, still without executing NetBox writes.

The focused tests validate that:

- journal initialization creates pending outcomes for planned operations,
- per-operation updates are immutable and sequence-safe,
- unknown operation sequence updates fail fast,
- ambiguous successful creates are flagged when object IDs are missing or duplicated,
- finalization marks a run as completed/cancelled with stable summaries.

Run the focused journal checks:

```powershell
python -m pytest -q tests/test_write_journal.py
```

This slice remains fully offline and uses synthetic fixtures only.

## M5 Read-back Planner Contracts

The next M5 micro-slice adds a read-only read-back planner for successful
operations, still without executing NetBox writes.

The focused tests validate that:

- successful create outcomes with object IDs produce read-back requests,
- successful updates derive target object IDs deterministically from device keys,
- successful create outcomes without object IDs are skipped explicitly,
- partial-failure journals generate read-back requests only for successful
	operations,
- cancelled runs without successful outcomes produce zero read-back requests,
- missing operation sequences are skipped explicitly (concurrent-edit safety).

GUI/config coverage also validates the delete-scope behavior toggle in Settings
and the default site-scoped filtering of NetBox-only delete proposals.
GUI coverage now also validates apply-flow behavior: enabling write execution
for executable plans, confirmation-triggered runner start and visible write
result rendering in preview highlights.
Rows-dialog coverage also validates single-row execution for selected executable
entries.

Run the focused read-back checks:

```powershell
python -m pytest -q tests/test_write_readback.py
```

This slice remains fully offline and uses synthetic fixtures only.

## M5 Write-Executor Contracts

The next M5 micro-slice adds a service-level NetBox write executor for
create/update operations with immutable journal outcomes and a dry-run mode.

The focused tests validate that:

- matched update operations produce deterministic NetBox patch payloads,
- create execution requires an explicit default NetBox device role setting,
- create execution succeeds with resolvable site/role/device-type references,
- dry-run execution records skipped outcomes without backend writes,
- mixed create/update runs continue and record partial failures per operation,
- each run is saved to the local write journal and listed in the write
	history; a failed save is reported without affecting the writes,
- UniFi is re-read before writing; changed or vanished source devices are
	skipped and an unreadable UniFi blocks all writes,
- interrupted creates are looked up by name instead of retried: one match is
	created, none is safe to retry, several or a failed lookup need review,
- successful writes are read back and marked verified, mismatch or unverified;
	read-back problems never cause another write and dry runs are not read back.
- every operation re-reads NetBox first: updates are skipped when the target
	was deleted or a selected field changed since the preview, creates are skipped
	when a device with the same name or serial now exists, and a failing re-read
	marks the operation as failed without writing.

Run the focused executor checks:

```powershell
python -m pytest -q tests/test_write_execute.py
```

This slice remains fully offline and uses synthetic fixtures only.

## Preview Pipeline Contracts

The Qt-free `pipeline` module orchestrates refresh, matching, delete scoping,
difference preview and write planning. Its tests patch the inventory readers
and validate ready and partial results without a GUI:

```powershell
python -m pytest -q tests/test_pipeline.py
```

## Offline Suite

Use Python >=3.15.1 in `.venv` and install `requirements-dev.txt`.

```powershell
python -m pytest -m "not integration"
python -m ruff check .
python -m ruff format --check .
```

The redesigned review window (M4.5) keeps its logic in the Qt-free `review`
module. `tests/test_review.py` covers categories, counts, device and field
selection, create choices, blockers and write outcomes; `tests/test_gui.py`
covers the window: cards and filters, row checkboxes, detail field selection,
create choices, confirmation blockers, per-row results, banners, copy, exports,
connection chips and the light/dark theme.

For GUI checks, run:

```powershell
python -m pytest -q tests/test_gui.py
```

Service-level coverage behind the GUI includes NetBox role, site, status and
device-type catalog ingestion, the status fallback when the NetBox
`dcim/devices/_choices/` endpoint is unavailable, explicit device-type ID
overrides for creates, and UniFi raw API capture with the row/source-id helpers
used by the dump exports.
Matching coverage now includes ordered criteria evaluation (name -> serial ->
MAC), ambiguity handling per active criterion and NetBox device-type catalog
ingestion for unmatched create suggestions.

Default tests block socket connections. API tests exercise the real pynetbox
request construction against a synthetic requests transport. No infrastructure
tokens, live hosts or external services are needed. Test credentials are synthetic.

## Target PC Acceptance

Clone/check out the exact feature branch and record `git rev-parse HEAD`.
Create `.venv` with Python >=3.15.1 and install the pinned requirements. Do not
copy your configuration or tokens into the repository or test reports.

The adapter currently supports NetBox 4.7.x and requires authenticated device read
permission. A web page or status endpoint alone is not proof of connectivity.
No live write test is part of this milestone; the application only permits GET.

1. Run `python -m unifi2netbox --version` and record the version/commit.
2. Run `python -m unifi2netbox`; first start must open Settings with both service tabs.
3. Enter your NetBox base URL including its actual HTTP/HTTPS scheme and token.
	If necessary, choose the private CA file or explicitly disable TLS validation.
4. Use Check Connections before Save; it must not create/update the TOML file.
5. Save; the main window must show Online and 4.7.3 after a successful read.
6. Restart; the token remains masked and a startup check runs automatically.
7. Test a deliberately invalid token: expect Unauthorized, not Online. Restore
	the valid token through settings. Do not include either token in your report.
8. Test an unreachable host or closed port with a short timeout: expect Offline;
	the window must remain responsive. Restore valid settings afterward.
9. Cancel changed settings and verify the saved connection is unchanged. Close
	during a check and confirm safe completion rather than a crash.

Offline GUI tests cover masking/showing, Save/Cancel, invalid configuration,
test-without-save, first startup, saved startup checks, stale result rejection,
background responsiveness and closing while workers are active.

Report commit, application/Python/OS/NetBox versions and observed results without
tokens, raw responses or private inventory. Linux and live checks are not passed
until executed on the corresponding systems.

## Pre-write Re-read Live Acceptance

Version 0.3.34 and later re-read NetBox before each write. This check uses
live NetBox writes, so limit it to one dedicated test device and run it only
with explicit opt-in. Use a UniFi device whose NetBox counterpart you may
change, or a test site. Never use production records you cannot restore.

Use the exact branch commit, reinstall requirements in `.venv` and record
`python -m unifi2netbox --version` (expect 0.3.36 or later) and
`git rev-parse HEAD`.

1. Refresh. Filter **Changed** and pick a device with a checked field (for
	example `serial`) in the detail panel. Note the NetBox device ID.
2. Without refreshing, change that field for the device in the NetBox web UI.
3. Enable **Dry run (no changes)** and use **Apply this device**. Expect
	`Skipped` with "NetBox values changed since the preview (serial)". NetBox
	stays unchanged.
4. Disable the dry run and apply the same device. Expect the same `Skipped`
	result and no change in NetBox (check the device changelog).
5. Refresh the preview. The row now shows the new NetBox value. Executing it
	writes normally and reports `success`.
6. Pick one create row. Before executing, create a NetBox device with the same
	name manually. Execute the row: expect `skipped` with "A NetBox device with
	name '...' now exists (ID ...)" and no second device. Delete your manual test
	device afterwards in NetBox yourself; the application never deletes.
7. Optional: for an update row, delete the target device in NetBox before
	executing. Expect `skipped` with "no longer exists".

Report version, commit and the observed status/message per step. Do not share
tokens, raw dumps or private inventory in the report.

## Acceptance Record

On 2026-10-25, the user reported that all online tests passed for the NetBox
connection milestone. Record the target-environment online acceptance as passed
on that basis; the development assistant did not contact the infrastructure.

The confirmation did not specify the exact tested commit/application version,
source versus packaged execution, Python version, OS build or TLS mode. These
details are not inferred. The configured project target remains NetBox Community
4.7.3 / netbox-docker 5.1.1. Linux and exact target-platform acceptance remain
unverified. This confirmation does not authorize a merge, release tag or API writes.

On 2026-10-28, the user reported the targeted 0.1.4 unified Settings and shared
Check Connections confirmation passed on the target PC. Reported outcomes include
single shared actions, tabbed unified settings, separate service outcomes, Cancel
preserving both tabs, atomic combined save behavior and safe close handling while
checks were active. This is user feedback; the assistant did not execute live tests
against the infrastructure.

On 2026-11-14, the assistant ran a read-only live check on the developer
workstation (commit b1b087f, application 0.3.36, CPython 3.15.1, Windows 11
10.0.26200) with the saved configuration. No writes were made; snapshots went
to a scratch directory instead of the real snapshot database.

- NetBox 4.7.3: Online. Read 4 devices, 374 device types, 5 roles, 1 site and
  1 device status. Plain HTTP with TLS verification not applicable.
- UniFi Network 11.0.99 (not the planned 10.6.100): the connection check reports
  `Unsupported` because of the 10.6 version gate, while the inventory reader
  succeeded with 19 devices over 3 API pages. TLS verification is disabled.
- Field coverage: UniFi provides name, model, manufacturer, MAC and site for all
  devices but no serial numbers; NetBox devices have no serial or primary MAC.
- Preview: 4 matched, 15 unmatched UniFi devices, no conflicts; 15 create and
  4 update rows. 3 update rows are blocked by `model_requires_manufacturer`
  (UniFi model names differ from NetBox device-type models while manufacturers
  match), so the full write plan is not executable. No default device role is
  configured, so creates need a per-row role.

After 0.3.37 (update selection limited to writable fields) the same live
preview became executable: 15 creates and 4 updates without blockers. All 4
updates only change `site`, and the UniFi site name does not exist in NetBox,
so executing them (and the creates) would fail at site lookup until a NetBox
site is chosen per row or a site mapping exists. No write was attempted.
After 0.3.38 the UniFi connection check reports Online for Network 11.0.99
(0.47 s first run, 0.02 s second run); the earlier 9.3 s first check did not
recur.
After 0.3.39 the same live preview without a site mapping plans 15 creates with
`unknown_netbox_site` warnings and no site updates; with the mapping set to the
only NetBox site it plans 15 creates without warnings. The mapping was passed in
the check script; the saved configuration was not changed.

On 2026-11-14, with the user's explicit approval, the assistant ran the
pre-write re-read acceptance as a scripted live write test against the NetBox
developer instance (commit 89397de, application 0.3.39). The script used the
same pipeline and executor as the GUI, with the site mapping and one NetBox
role passed in; UniFi was only read. Results, all passed (9/9):

- T1: a device with the same name created after the preview made the create
	operation `skipped` ("now exists"); no second device was created.
- T2: after a refresh the create succeeded; read-back confirmed name, site,
	device type and role.
- T3: an unselected field change (serial) did not block a site update, which
	succeeded and was read back.
- T4: a site change after the preview made both the dry run and the real run
	`skipped` ("changed since the preview (site)"); NetBox kept the new value.
- T5: deleting the target after the preview made the update `skipped`
	("no longer exists").

All test objects (one duplicate device, the created device and two test sites)
were removed afterwards; NetBox again held 4 devices and 1 site. The GUI itself
was not driven in this test.

Observed limitation: only 1 of 11 UniFi model names in this installation
(`U6 Lite`) matches a NetBox device-type model exactly. Device-type suggestions
rank manufacturer-only candidates (score 20) and partial matches such as
`USW-Pro-8-PoE` for `USW Pro 24 PoE`, so creates currently need a manually
chosen `Device type` per row.
After 0.3.40 a read-only live preview preselects the correct NetBox device type
for all 11 UniFi models in this installation (15 of 15 create rows): one by
exact model, seven by part number and three by alias. 203 of 210 Ubiquiti
device types in this NetBox carry a part number.

On 2026-11-14 the assistant checked the M5 additions live on the developer
workstation (commit 4a5b07d, application 0.5.4). Read-only first: the UniFi
re-read took 0.04 s and found all 15 planned devices; a real dry run of all 15
creates passed the UniFi and NetBox re-read checks and was saved to a scratch
write journal. Then, with the user's explicit approval, an approved write test
against the NetBox developer instance passed 6/6 checks: a create through the
real pipeline was written and read back as verified, a site update via a
temporary test site was written and verified, both runs appeared in the write
history, and the test device and test site were removed afterwards (NetBox
again held 4 devices and 1 site). Interrupted creates and changed UniFi values
cannot be produced safely on live systems and remain covered by offline tests.

On 2026-11-14 the assistant checked M6 slice 2 (UniFi networks to NetBox VLANs
and prefixes) live on the developer workstation (commit c71d1ad, application
0.6.5). Read-only first: UniFi Network 11.0.99 returned 16 networks (15
enabled, VLANs 1-300, all with subnets); NetBox IPAM was empty, and the plan
for site "Wiesenthau" held 1 VLAN group, 15 VLANs and 15 prefixes (31
operations). A real dry run of all 31 operations passed the UniFi and NetBox
re-read checks in 0.68 s without writing. Then, with the user's explicit
approval, a write test against the NetBox developer instance passed 10/10
checks: with one network selected (VLAN 2, 10.10.1.0/24) the real pipeline
created the site-scoped VLAN group "UniFi Wiesenthau", the VLAN and the prefix
linked to it, all three read back as verified; a fresh plan showed the network
in sync with nothing selected, a second apply wrote nothing, both runs appeared
in the write history, and the prefix, VLAN and group were removed afterwards
(NetBox IPAM empty again). VLAN name alignment, prefix conflicts and
interrupted creates remain covered by offline tests.

On 2026-11-14 the assistant checked M6 slices 3 and 4 live on the developer
workstation. Read-only first (application 0.6.6): the internal port
configuration resolved 195 of 195 UniFi ports on 17 devices without notes
(90 `tagged-all`, 46 `access`, 57 `disabled`, 2 `tagged`; no LAG configured).
With commit 67d5a3e (application 0.6.10) the interface plan held 19 paired
interfaces on the UDM Pro Max and one USW (13 mode, 6 enabled changes; VLAN
fields waited for the missing VLAN group), and a real dry run of all 19 passed
the UniFi and NetBox re-read checks in 5.1 s without writing. Then, with the
user's explicit approval, a write test against the NetBox developer instance
passed 8/8 checks: the VLAN group "UniFi Wiesenthau" and VLAN 1 were created
and verified through the network plan; after a refresh, UDM `port.1` was set
to `tagged-all` with untagged VLAN 1 and USW `SFP+ 1` was disabled, both read
back as verified; a fresh plan showed both interfaces in sync, a second apply
wrote nothing, all three runs were in the write history, and afterwards both
interfaces were restored and the VLAN and group removed (all NetBox interfaces
equal to before, IPAM empty). Tagged VLAN lists, drift skips and LAG remain
covered by offline tests.

On 2026-11-14 the assistant checked M6 slice 5 (cable suggestions) live on the
developer workstation (commit e43a5c0, application 0.6.13). Read-only first:
UniFi reported 53 link observations (35 LLDP, 18 uplink) on 18 device pairs
without disagreement; the plan suggested one cable, UDM `port.5` to RPS
`Port 1` (LLDP from the UDM and uplink from the RPS, preselected), and kept 17
pairs reference-only because one device is not in NetBox. A real dry run passed
the UniFi and NetBox re-read checks in 3.8 s without writing. Then, with the
user's explicit approval, a write test against the NetBox developer instance
passed 7/7 checks: the cable was created with status connected between both
interfaces and read back as verified, a fresh plan showed it in sync, a second
apply wrote nothing, both runs were in the write history, and the cable was
deleted afterwards (NetBox again had 0 cables). A first attempt of this test
created the same cable but the test script read the wrong outcome field and
skipped its cleanup; the assistant confirmed that the leftover cable joined
exactly the two test interfaces, deleted it, and repeated the test. Disagreeing
evidence, occupied interfaces and interrupted creates remain covered by
offline tests.

