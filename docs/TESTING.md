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
- the optional Access connection reads devices with a Bearer token and GET
	only, never contacts a console while unconfigured, reports rejected tokens,
	missing APIs and error envelopes, and keeps its own config section;
	optional chips stay hidden until configured,
- the Access reader keeps name, model, MAC from the ID, kind and state,
	skips unadopted devices, rejects duplicates and malformed answers, is
	refreshed only when configured, keeps a stale snapshot on failure, and a
	rejected URL without a port points to 12445,
- `--smoke-test` shows the main window, prints its title and exits with 0;
	with `UNIFI2NETBOX_EXE` set on Linux, `tests/test_package.py` runs it
	against the standalone build or the installed launcher,
- the application icon bundles every PNG size, the `.ico` holds PNG
	entries for all sizes, title-bar caption colors follow the theme (the
	main window uses the header color) and theme changes restyle windows,
- the optional Drive connection reads only the public `/api/system` with GET
	and without sending the key, accepts UNAS models only, never contacts a
	console while unconfigured and keeps its own config section,
- the Drive reader returns the UNAS as one device plus allow-listed drive
	bays, sends the key only to the storage endpoint, keeps the device when
	the storage read fails, round-trips through the snapshot store, joins
	matching only when fresh and lists bays display-only without serials,
- drive inventory items are planned per bay (create, update, in sync,
	conflict, kept), never cleared by empty UniFi values, written after
	devices with a fresh bay check, duplicate-safe creates, interrupted-create
	lookup, drift-checked updates, read-back and no writes in dry runs,
- optional devices merge with precedence Network, Access, Protect; only
	fresh Access reads join the preview, the pre-write re-read includes
	Access and tolerates its failure, Access rows never get the default role
	and never match an "Access Point" role,
- fresh Protect devices join matching with prefixed IDs and MAC dedup
	against Network, stale ones never do, the pre-write re-read merges Protect
	and tolerates its failure, Protect creates never inherit the default role,
	unknown vendors get exact type matches only, and empty choices show a
	placeholder,
- the Protect reader keeps name, MAC, model, kind and state only, sets the
	Ubiquiti manufacturer only for known model prefixes, rejects malformed or
	duplicate entries and is refreshed only when configured; failures keep the
	last Protect snapshot without blocking NetBox or Network,
- the optional Protect connection reads info, NVRs and cameras with GET
	only, never contacts a console while unconfigured, reports HTML answers as
	unsupported, gates the 7.3 series and keeps its own config section,
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

On 2026-11-14 the assistant checked M7 (UniFi Protect) live on the developer
workstation. Read-only first: the Protect connection to the UNVR was Online
(Protect 7.3.74, own local API key); the reader returned 11 devices (1 NVR,
10 cameras) in 0.36 s; the UDM answered the Protect paths with HTML only. With
commit 2b60bd8 (application 0.7.3) the preview showed all 11 Protect devices as
create rows, 6 with a preselected device type and none with a role (NetBox had
no camera or NVR role). Then, with the user's explicit approval, a write test
against the NetBox developer instance passed 7/7 checks: a temporary role
`u2n-test-camera` was created and preselected for the camera "Hof" (UVC G6
Bullet, type "Unifi G6 Bullet"); the create ran through the real pipeline
including the Protect re-read and was read back as verified with the expected
name, role, type and site; a refreshed preview matched the new device as in
sync (model text and MAC differ but are not writable, as for Network devices);
the run was in the write history; the camera and the role were removed
afterwards (NetBox again had 4 devices and 5 roles). A failing Protect re-read
and stale Protect snapshots remain covered by offline tests.

On 2026-11-14 the assistant checked M8 (UniFi Access) live on the developer
workstation. Read-only first (application 0.8.1/0.8.2): Access runs on the
UDM; the developer API on port 12445 returned a UAH hub and a UA-Intercom,
both online, with IDs equal to their MACs (the intercom ID matches its Protect
MAC). A saved URL without `:12445` was rejected with 401 by UniFi OS, which
the check now explains. With commit 81235c8 (application 0.8.3) the preview
listed 31 UniFi devices (19 Network, 2 Access, 10 Protect); the intercom came
from Access and its Protect copy was dropped; a dry run of the hub create
passed the Access re-read and wrote nothing. Then, with the user's explicit
approval, a write test against the NetBox developer instance passed 7/7
checks: a temporary role `u2n test Access Control` and a temporary device type
`UAH` (Ubiquiti) were created and both preselected for the hub "Haustür Hub";
the create ran through the real pipeline including the Access re-read and
was read back as verified with the expected name, role, type and site; a
refreshed preview matched the new device as in sync (only the MAC differs,
which is not writable, as for Network devices); the run was in the write
history; device, type and role were removed afterwards (NetBox again had 4
devices, 5 roles and 374 device types). Failing Access re-reads and stale
Access snapshots remain covered by offline tests.

On 2026-11-14 the assistant checked M9 (UniFi Drive / UNAS) live on the
developer workstation. Read-only first (applications 0.9.0 to 0.9.2): the
developer portal lists no Drive API; the UNAS Pro (one device with a 1G
management and a 10G SFP+ data interface) answers the public `/api/system`;
with its local API key the internal `/proxy/drive/api/v2/storage` endpoint
returned 7 drive bays (5 HDDs, 2 empty) and one pool. The preview showed the
UNAS as a create row with the NetBox type "UNAS Pro" preselected. Then, with
the user's explicit approval and commit 6c38286 (application 0.9.3), a write
test against the NetBox developer instance passed 9/9 checks: a temporary
role `u2n test Storage` was created and preselected; the UNAS device
"HG-DG-R1-NAS" was created through the real pipeline including the Drive
re-read and verified; a refreshed preview matched it and planned one create
per populated bay (5); a dry run checked all five and wrote nothing; the real
run created `Disk 1` to `Disk 5` with part ID, serial and `discovered`, all
read back as verified; a further refresh showed all five in sync; the three
runs were in the write history. Items, device and role were removed
afterwards (NetBox again had 4 devices, 5 roles and 0 inventory items).
Serial numbers were not printed in the test log.

On 2026-11-14 the assistant ran the M10 acceptance on the developer
workstation (Windows 11). The per-user installer for 0.10.3 was installed to
`%LOCALAPPDATA%\Programs\unifi2netbox` (Start menu entry, Apps entry); the
0.10.4 installer, built by `tools/build_windows.ps1` from commit 45eb26d,
upgraded it in place (one Apps entry "unifi2netbox 0.10.4", bundled package
metadata 0.10.4, native smoke test of the installed exe passed); the per-user
configuration folder kept its files, sizes and timestamps. The installed app
then started with the real configuration: all five connections (NetBox
4.7.3, UniFi Network 11.0.99, Protect 7.3.74, Access, Drive) were online with
the expected TLS warning tone, a read-only refresh showed 32 UniFi devices
(4 in sync, 28 new, 19 interface changes, 1 cable suggestion), and the app
closed with exit code 0. All 28 new devices reported "Site 'Default' does not
exist" because the real configuration has no NetBox site mapping (Sync
defaults); this is configuration, not a defect. On the real screen the UniFi
chip overlapped the Protect chip; fixed in 0.10.5 and rechecked on screen.
Linux was verified only by the GitHub Actions Packages workflow (offscreen).

On 2026-11-15 the assistant checked M11 slice 1 read-only on the developer
workstation (application 1.0.1 on top of commit f2de96f, CPython 3.15.1,
Windows 11 10.0.26200), calling the inventory readers directly so the snapshot
database was not changed; only counts were printed. UniFi Network 11.0.99: 19
devices, all with management IP and firmware; 195 port configurations, 18 with
a fixed speed; 23 SFP modules; 15 DHCP ranges; 6 wireless LANs; 139
reservations; no secrets (`x_passphrase`, `x_password`, `x_authkey`) in the
models. NetBox 4.7.3: 26 devices without primary IPv4 or firmware, 3
manufacturers, 0 IP addresses, 0 IP ranges, 0 wireless LANs, 0 Custom Fields;
all optional reads succeeded. No writes were made.

On 2026-11-15 the assistant ran a live dry run of M11 slice 2 (application
1.0.2 working tree on top of commit b4fe839) with snapshots in a scratch
folder and no write history: the plan proposed creating the Custom Field
`firmware` (NetBox had none) and 19 firmware-only updates of matched devices;
the dry run re-read UniFi and NetBox, passed every check and wrote nothing
(20 operations skipped as dry run).

Then, with the user's explicit approval, the assistant ran the slice 2 write
test against the NetBox developer instance (commit 63ce9b0, application
1.0.2) through the real pipeline, with firmware selected for exactly one
device; UniFi was only read. Results, all passed (6/6): the Custom Field
`firmware` (text, `dcim.device`) was created and read back as verified; the
firmware of `HG-DG-Technik-SW11` (empty in NetBox, 7.5.15 in UniFi) was
written as `custom_fields.firmware` and verified; a refreshed preview showed
the field as present, the device in sync and the other 18 firmware changes
still pending; a second apply of the device had nothing to write. The run is
in the write history. As approved, the Custom Field and the firmware value
stay in NetBox (real data, not a test object).

On 2026-11-15 the assistant ran a live dry run of M11 slice 3 (application
1.0.3 working tree on top of commit 3d5f70f) with snapshots in a scratch
folder and no write history: 19 matched devices carry a UniFi IP; 18 were
planned (17 with a new virtual `Management` interface, the RPS reusing its
existing management interface; all /24 from the UniFi management network)
and 1, the UDM, only got a note because UniFi reports its public WAN address.
The dry run re-read UniFi and NetBox, passed every check for all 18 and wrote
nothing.

Then, with the user's explicit approval, the assistant ran the slice 3 write
test against the NetBox developer instance (commit 14427d8, application
1.0.3) through the real pipeline for exactly one device; UniFi was only read.
Results, all passed (6/6): for `HG-DG-Technik-SW11` the virtual,
management-only interface `Management`, the IP 10.10.0.11/24 on it and the
primary IPv4 were written and read back as verified; a refreshed preview
showed the row in sync with one `Management` interface and the primary IPv4
10.10.0.11, the other 17 devices still pending, and a second apply had
nothing to write. The run is in the write history. As approved, the
interface, IP and primary IPv4 stay in NetBox (real data, not test objects).

On 2026-11-15 the assistant ran a live dry run of M11 slice 4 (application
1.0.4 working tree on top of commit d51f164) with snapshots in a scratch
folder and no write history: of 194 paired interfaces, 96 had changes, all
preselected (87 descriptions from UniFi port names, 18 fixed 10 Gbps speeds
with full duplex; no PoE change because the NetBox device types already
carry the same PoE values; the VLAN modes were already in sync). The dry run
passed the UniFi and NetBox re-read checks for all 96 and wrote nothing.

Then, with the user's explicit approval, the assistant ran the slice 4 write
test against the NetBox developer instance (commit 7f7d313, application
1.0.4) through the real pipeline for exactly one interface; UniFi was only
read. Results, all passed (4/4): `NG-DG-R1-SW11 SFP+ 7` got the description
"Uplink", speed 10 Gbps (10000000 kbps) and full duplex in one PATCH, read
back as verified; a refreshed preview showed the interface in sync and the
other 95 interfaces still pending, and a second apply had nothing to write.
The run is in the write history; the values stay in NetBox as approved. PoE
writes are covered by offline tests because no live interface needed one.

On 2026-11-15 the assistant ran a live dry run of M11 slice 5 (application
1.0.5 working tree on top of commit 9dd833a) with snapshots in a scratch
folder and no write history: all 23 SFP modules sat in ports paired with a
NetBox interface and were planned as creates of `Transceiver <interface>`
items; 19 got the NetBox manufacturer Ubiquiti (vendors `UBNT` and
`Ubiquiti Inc.`), 4 `H3C-OEM` modules none, because NetBox has no matching
manufacturer. The dry run passed the UniFi and NetBox re-read checks for all
23 and wrote nothing.

Then, with the user's explicit approval, the assistant ran the slice 5 write
test against the NetBox developer instance (commit 5cbc35b, application
1.0.5) through the real pipeline for exactly one module; UniFi was only
read. Results, all passed (5/5): the item `Transceiver SFP+ 7` of
`NG-DG-R1-SW11` was created with part ID `UF-MM-10G`, its serial, the
description "10G BASE-SR", manufacturer Ubiquiti and a link to the
interface `SFP+ 7`, read back as verified; a refreshed preview showed
exactly one item of that name, in sync, the other 22 modules still pending,
and a second apply had nothing to write. The run is in the write history;
the item stays in NetBox as approved.

On 2026-11-15 the assistant ran a live dry run of M11 slice 6 (application
1.0.6 working tree on top of commit ec93204) with snapshots in a scratch
folder and no write history: 6 wireless LANs (all with their VLAN from the
site VLAN group), 15 DHCP IP ranges and 139 reserved IP addresses (3 with a
DNS name) were planned as preselected creates; NetBox 4.7.3 had none of
them. The dry run passed the UniFi and NetBox re-read checks for all 160 and
wrote nothing.

Then, with the user's explicit approval, the assistant ran the slice 6 write
test against the NetBox developer instance (commit 65243a7, application
1.0.6) through the real pipeline for exactly one object of each kind; UniFi
was only read. Results, all passed (6/6): the wireless LAN `Amazon` (status,
WPA personal with AES, its VLAN from the site VLAN group and the site scope),
the IP range `10.10.0.200-10.10.0.250` (`DHCP Default`) and the reserved IP
address `10.10.0.2` were created and read back as verified; a refreshed
preview showed all three in sync, the other 157 objects still pending, and a
second apply had nothing to write. The run is in the write history; the
objects stay in NetBox as approved.

On 2026-11-17 the assistant checked M14 slices 1 to 5 (application 1.3.8
working tree on `feature/netbox-type-sync`). Offline: tree refresh (show,
Refresh, file watcher, changed open file), the bulk read and conversion of
NetBox types, the comparison of every template kind, a round trip
definition → import → read back → equal, tree colors, cell marks and
**Use NetBox value**, NetBox-only rows, Copy YAML, New from NetBox and the
library, the sync plan and execution (overwrite, per value, dry run, drift,
missing references, interrupted create, read-back) against an API-shaped
fake, the preflight (rack overlap, leaving the rack, 0 U, child role,
model conflict, warnings) and the dialogs. Read-only live checks against
the developer NetBox 4.7.3 (counts and statuses only): 377 types read in
1.4 s, all converted to valid definitions; of 4 local files 2 equal and 2
with real differences; a dry-run sync of both (a wrapper refused any write)
planned 4 and 2 steps with warnings only, no blockers, nothing written.
Found and fixed on the way: the theme style sheet hid cell backgrounds (a
delegate paints the marks), and decimal weights failed the schema's
`multipleOf` in floating point.

Then, with the user's explicit approval, the assistant ran the M14 write test
on test device type 378 (`u2n Test Box`, no devices) in the developer NetBox
4.7.3 (commit 4b3fc8b, application 1.3.8); a guard refused any write outside
type 378 and its templates, UniFi was not touched. The type was read from
NetBox into a temporary local folder (compared equal). Results, all passed:
**Overwrite NetBox** with a new description, weight 1.6 kg and a new
interface `eth1` patched the type and created the template, read back as
verified; **per value** with `eth0` `mgmt_only` set to Local and `comments`
set to NetBox patched one interface template (verified) and changed only the
local file's comments; a 2 U height produced no preflight finding (no
devices) and its dry run wrote nothing; a second comparison of the saved
file was equal to NetBox. Writes made: one PATCH of the type, one interface
template created, one interface template patched; both runs are in the
write history. The changes stay on type 378.

On 2026-11-17 the assistant checked M13 slices 1 to 4 (application 1.2.5
working tree on `feature/netbox-device-types`). Offline: the extended schema
accepts every NetBox 4.7 device type and template field and rejects wrong
types, choices and component references; library files still round-trip
byte-identical; the catalog reader and the New dialogs (no duplicates,
interrupted create looked up, read-back, write history) use fake
transports; the editor's drop-downs, New..., tags, custom fields, images
(copy, rename, remove) and component reference lists are driven through the
widgets; the import sends all fields, resolves references by name or slug,
creates every template kind in dependency order with port mappings,
interface parents and bridges and inventory hierarchies, uploads images as
multipart and stops before any write when a reference is missing.
Read-only live check against the developer NetBox 4.7.3 (counts only): the
catalog read all six lists and the custom field definitions without errors
(3 manufacturers; no platforms, owners, owner groups, tags, inventory item
roles or device type custom fields yet). Manual screenshots come from demo
data.

Then, with the user's explicit approval, the assistant ran the M13 write test
against the developer NetBox 4.7.3 (commit 6c6737c, application 1.2.6); UniFi
was not touched. Through the functions behind the New dialogs: owner group
`u2n test group`, owner `u2n test owner` (in that group) and tag `u2n-test`
were created, read back as verified and saved to the write history. A test
definition `u2n Test Box` (Ubiquiti, slug `ubiquiti-u2n-test-box`) with owner,
tag, cooling method, end of life, exclude from utilization, a power port
feeding an outlet, `eth0` with child `eth0.10`, a rear and a front port with a
port mapping and a generated front image validated without errors. Results,
all passed: the dry run wrote nothing; the import created type 378 with 6
templates and 1 image, verified; an independent read-back showed the owner,
the tag, `air`, `2035-12-31`, `exclude_from_utilization` true and a front
image, 1 power port, 1 outlet fed by `PSU 1`, 2 interfaces with `eth0.10`
parented to `eth0`, rear port `Rear 1` of type 378 mapped 1:1 to `Front 1`;
a second run reused the slug and created nothing. The test objects stay in
NetBox (the app never deletes); no device was created.

On 2026-11-17 the assistant checked the resizable editor sections
(application 1.2.1 working tree on `feature/editor-layout`): offline tests
cover the three-section splitter, the validation splitter, restoring window
size and section heights from `[ui]` and keeping them when the theme is
saved; offscreen rendering shows the grab lines. Not checked on a real
desktop with several screens.

On 2026-11-16 the assistant checked M12 (application 1.1.9 working tree on
`feature/device-types`) read-only against the live systems, nothing written:
the devicetype-library index was read from GitHub (14,433 files, 455
manufacturers); techspecs lookups resolved the real models listed in
`API_CAPABILITIES.md`; a refresh found 6 create rows without a NetBox type
(UA-Intercom, UAH, UVC G5 Bullet, three third-party CAM-PT2), none in the
library; drafts came from techspecs for UA-Intercom and UVC G5 Bullet; the
import dry run passed the NetBox re-read for all four definitions (Ubiquiti
exists as manufacturer). Offline: library files round-trip byte-identical,
schema and CONTRIBUTING validation, search and filters, techspecs parsing,
drafts, editor views, picker, import plan and execution (reuse, blockers,
interrupted creates, template failures, read-back), skipped dependent device
creates, the pipeline order and the compact header. Screenshots for the manual
chapter come from demo data only.

Then, with the user's explicit approval (role Camera chosen by the user), the
assistant ran the M12 write test against the NetBox developer instance
(commit 128e479, application 1.1.9) through the real pipeline; UniFi was only
read. A techspecs draft for UA-Intercom (part number UA-Intercom, one PoE
powered `eth0`, weight, techspecs link) was saved to the local type folder
without validation errors. Results, all passed (5/5): the device type was
imported with its one interface template and read back as verified; the
UniFi device "Haustür" was created with that type and verified; after a
refresh NetBox had exactly one type with part number UA-Intercom, the device
was matched (in sync) and a second apply had nothing to write for it. The
type, the device and the local file stay as real data, as approved.

On 2026-11-15 the assistant checked the reopened-window title bar fix
(application 1.1.2 working tree on top of v1.1.1) natively on the developer
workstation (Windows 11, Qt windows platform): opening the manual window,
closing it and opening it again showed, before the fix, that the second
opening gets a new native window while `QWidget.winId()` still returned the
destroyed one (`IsWindow` 0), so no theme was applied. With the fix the
DWM dark-mode attribute read back as 1 (dark theme) and 0 (light theme) on
both openings.

On 2026-11-15 the assistant added the user manual (application 1.1.1
working tree on top of v1.1.0): `tests/test_manual.py` checks the chapter
structure, that every page has a title, that every link and image resolves
and every screenshot is used, and drives the manual window (overview first,
tree and link navigation, Back, Overview, opening from the main window). The
screenshots were rendered offscreen with `tools/build_manual_screenshots.py`
from fictional demo data and reviewed visually; no real system data or local
path appears in them. Not verified: the manual window in a packaged build.

On 2026-11-15 the assistant checked M11 slice 7 (application 1.0.7 working
tree on top of commit d2f40ad) with live read data and nothing written. The
review window rendered offscreen (`QT_QPA_FONTDIR=C:/Windows/Fonts`) with the
new filters Addresses 173 (17 management IPs, 15 ranges, 139 reservations,
plus in-sync and note rows), Wireless 6 and Modules 23; the detail panel
showed the planned fields with VLAN and interface names. A dry run over every
kind together (no write history) skipped 95 interfaces, 17 management IPs,
14 ranges, 138 reservations, 22 SFP modules and 5 wireless LANs with
"Dry-run mode", so all passed the UniFi and NetBox re-read checks; device
writes stayed pending because six device creates still need a device type
and role (preflight blocker, as before). No network or cable change was
pending, and the Custom Field `firmware` already exists.
