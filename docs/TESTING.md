# Testing

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