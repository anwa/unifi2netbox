# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read First

`AGENTS.md` holds the binding project rules (branching, versioning, commit format,
security, documentation duties). Read it and `docs/IMPLEMENTATION_PLAN.md` before
starting work. Key points that are easy to miss:

- Communicate with the user in **German**; code, GUI labels, commits and docs are English.
- Never implement on `main`; each milestone has its own `feature/...` branch
  (listed in the implementation plan). Merging into `main` needs explicit approval.
- Every ordinary code-changing commit bumps the patch version in `pyproject.toml`
  (`version = "x.y.z"`, the only version source; read at runtime via
  `importlib.metadata`). Doc-only commits do not bump. Never `git add .`.
- Keep README.md, CHANGELOG.md, `docs/TESTING.md` and the milestone checkboxes in
  `docs/IMPLEMENTATION_PLAN.md` current with every behavior change.
- This dev machine cannot reach the user's NetBox/UniFi. Never claim live API,
  Linux or packaged-app verification; record user-reported results as such.

## Commands

Python >=3.15.1 in a local `.venv` (Windows: `.\.venv\Scripts\Activate.ps1`).
`requirements.txt` installs the package editable (`-e .`); reinstall after a version
bump so `--version` and the window title match.

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -m "not integration"          # offline suite (CI runs this)
python -m pytest -q tests/test_matching.py      # one file
python -m pytest -q tests/test_gui.py -k rows   # single test / pattern
python -m ruff check .
python -m ruff format --check .
python -m unifi2netbox [--config PATH] [--version]
```

CI (`.github/workflows/tests.yml`) runs ruff + offline pytest on Windows and Ubuntu
with `QT_QPA_PLATFORM=offscreen`. `tests/conftest.py` autouse-blocks all socket
connects, so tests must use synthetic transports (`httpx.MockTransport` for UniFi,
a fake requests transport for pynetbox/NetBox). `tests/test_package.py` is skipped
unless `UNIFI2NETBOX_EXE` points at a PyInstaller build (see `docs/DEPLOYMENT.md`).

## Architecture

Package in `src/unifi2netbox/`, PySide6 Qt Widgets desktop app. Entry point
`app.py:main` builds a `QThreadPool` (max 2 threads) and passes it into
`gui.MainWindow`. All network work runs in `QRunnable` jobs that emit a result
object through a `Signal`; widgets are only touched in the slot on the GUI thread.
Runner objects (`ConnectionRunner`, `InventoryPreviewRunner`, `WriteExecutionRunner`)
own one in-flight job each and reject concurrent starts.

Layers (service modules are Qt-free and work on frozen dataclasses):

- **Config** (`config.py`): TOML via `tomllib` + `tomlkit` (comment-preserving,
  atomic writes). Sections `[netbox]`, `[unifi_network]`, plus behavior settings.
  Default path from `platformdirs.user_config_path`, outside the repo.
- **Connection checks** (`netbox.py`, `unifi.py`, `connections.py`): NetBox via
  pynetbox over a `ReadOnlySession` that only permits GET; UniFi via httpx against
  the official local Network integration API (read-only, no proxy env, no redirect
  or login fallback). "Online" means authenticated inventory reads succeed.
- **Inventory + snapshots** (`inventory.py`, `snapshots.py`, `refresh.py`):
  paginated readers normalize both sources into `InventorySnapshot` /
  `InventoryDevice` (plus NetBox catalogs: device types, roles, sites, statuses).
  `SnapshotStore` is SQLite (`snapshots.sqlite3` next to the config file) with
  current/previous per source; failed refreshes keep the last good snapshot and
  mark it stale.
- **Matching** (`matching.py`): confirmed mappings first, then ranked passes per
  UniFi device: normalized name → serial → MAC. Multiple hits within one pass are
  an ambiguity conflict, never auto-matched. Device Type suggestions only for
  unmatched devices, from existing NetBox manufacturer/model combos.
- **Preview** (`preview.py`): `DifferencePreview` (create / update / target-only
  rows with field provenance and configured vs. operational categories, immutable
  batch/device/field selection) → `ChangePreview` with dependency/readiness checks.
- **Writes** (`write_plan.py` → `write_execute.py` → `write_journal.py` →
  `write_readback.py`): selected previews become an ordered `WritePlan` (creates
  before updates, preflight blockers), executed against NetBox via
  `RequestsNetBoxWriteBackend` (supports dry run), outcomes recorded in an
  immutable journal, then read-back requests planned for successful operations.
  GUI-side per-row overrides (role, site, status, device-type ID) are passed into
  execution for create rows.
- **GUI** (`gui.py`, large): settings dialog with NetBox/UniFi tabs, connection
  panels, Inventory Preview section, the `Show all rows` dialog and write execution.
  `InventoryPreviewJob.run` is the end-to-end pipeline: refresh → match → preview →
  plan.
- **Diagnostics** (`capabilities.py`, `reporting.py`): installed-version field
  capability matrix and opt-in sanitized (pseudonymized) fixture/report export.

Domain invariants to preserve: UniFi is never written; no automatic deletions
(NetBox-only delete proposals are scoped to the active UniFi site by default);
no silently created Custom Fields; missing source values must not clear NetBox
values; offline/stale snapshots cannot authorize writes; never blindly retry a
timed-out create.
