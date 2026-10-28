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
2. Open File > Settings, then the UniFi Network tab. Enter the local UDM base URL and
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

## Offline Suite

Use Python >=3.15.1 in `.venv` and install `requirements-dev.txt`.

```powershell
python -m pytest -m "not integration"
python -m ruff check .
python -m ruff format --check .
```

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