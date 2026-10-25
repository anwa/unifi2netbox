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
UniFi target-PC acceptance remains pending; the M2 GUI is now available.

## UniFi Target PC Acceptance

Use the exact `feature/unifi-network-connection` commit, reinstall requirements
in `.venv`, and record `python -m unifi2netbox --version` before starting.

1. Confirm the previously configured NetBox connection still works unchanged.
2. Open File > UniFi Network Settings. Enter the local UDM console base URL and
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
2. Run `python -m unifi2netbox`; first start must open NetBox Settings.
3. Enter your NetBox base URL including its actual HTTP/HTTPS scheme and token.
	If necessary, choose the private CA file or explicitly disable TLS validation.
4. Use Test Connection before Save; it must not create/update the TOML file.
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