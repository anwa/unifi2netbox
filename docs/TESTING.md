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
GUI instructions will be added with the GUI commit. No live write test is part
of this milestone; the application only permits GET requests.

Report commit, application/Python/OS/NetBox versions and observed results without
tokens, raw responses or private inventory. Linux and live checks are not passed
until executed on the corresponding systems.