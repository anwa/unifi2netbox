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
- Every approved minor/major release also gets a Windows exe build from the
  tagged commit plus the native smoke test (`docs/DEPLOYMENT.md`); record it there.
- Keep README.md, CHANGELOG.md, `docs/TESTING.md` and the milestone checkboxes in
  `docs/IMPLEMENTATION_PLAN.md` current with every behavior change.
- Two machines use this repo: the **developer workstation** (direct access to
  the user's NetBox and UniFi) and an **external developer notebook** (no
  access). On the workstation you may run the app and opt-in live tests against
  the real systems: reads freely, NetBox writes only after the user approves that
  specific test and only on dedicated test objects. Never write to UniFi. The
  real config (`%LOCALAPPDATA%\unifi2netbox\config.toml`) holds tokens: use it,
  never print, copy or commit it. Record live evidence with date, commit,
  version and observed results; never claim Linux or packaged-app verification
  without running it.

## Commands

Python >=3.15.1 in a local `.venv` (Windows: `.\.venv\Scripts\Activate.ps1`).
`requirements.txt` installs the package editable (`-e .`); reinstall after a version
bump so `--version` and the window title match.

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -m "not integration"          # offline suite (CI runs this)
python -m pytest -m integration                # live tests, workstation only (*)
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

(*) No `integration` tests exist yet, and the conftest socket block currently
applies to them too. Adding the first live test means exempting that marker in
`tests/conftest.py` and reading the real config without logging secrets.

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
  Optional `[unifi_protect]` (own console URL and key) for UniFi Protect and
  `[unifi_access]` (Access API URL with port 12445 and Access token) and
  `[unifi_drive]` (UNAS console URL and local key for the internal storage
  endpoint).
- **Connection checks** (`netbox.py`, `unifi.py`, `protect.py`, `access.py`,
  `drive.py`, `connections.py`): NetBox via pynetbox over a `ReadOnlySession` that only
  permits GET; UniFi Network and Protect via httpx against the official local
  integration APIs (read-only, no proxy env, no redirect or login fallback).
  "Online" means authenticated inventory reads succeed.
- **Access inventory** (`access.py`): optional; hubs, readers and intercoms
  (name, MAC from the device ID, model, kind, state) into a `unifi_access`
  snapshot; users, logs and doors are never read. **Drive inventory**
  (`drive.py`): the UNAS as one device plus allow-listed drive bays
  (`InventoryDisk`) in a `unifi_drive` snapshot; file contents never. Optional devices join
  matching via `merge_optional_devices` (prefixes `access:`, `protect:`,
  `drive:`; precedence Network > Access > Protect > Drive by MAC).
- **Protect inventory** (`protect.py`): optional; NVR and cameras (name, MAC,
  model, kind, state) into a separate `unifi_protect` snapshot; failures never
  block NetBox or Network.
- **Inventory + snapshots** (`inventory.py`, `snapshots.py`, `refresh.py`):
  paginated readers normalize both sources into `InventorySnapshot` /
  `InventoryDevice` (plus NetBox catalogs: device types, roles, sites, statuses).
  `SnapshotStore` is SQLite (`snapshots.sqlite3` next to the config file) with
  current/previous per source; failed refreshes keep the last good snapshot and
  mark it stale.
- **Networks** (`networks.py`, `network_execute.py`): plan and write a
  site-scoped VLAN group, VLANs and prefixes from UniFi networks with the same
  re-read, reconciliation and read-back safeguards as device writes; network
  writes run before device writes in one run.
- **Port configuration** (`port_config.py`): resolves the effective UniFi
  port configuration (name, enable, profile, mode, native/tagged VLANs, LAG)
  from allow-listed fields of internal Network endpoints, read GET-only and
  only for UniFi Network 11.0; all-VLAN trunks stay `tagged-all`.
- **Interfaces** (`interface_plan.py`, `interface_execute.py`): field-level
  plan (enabled, mode, untagged/tagged VLANs from the site VLAN group) for
  paired ports of matched devices, written by PATCH between network and device
  writes with drift checks and read-back; LAG stays display-only.
- **Cables** (`links.py`, `cables.py`, `cable_execute.py`): link evidence
  from internal uplink/LLDP data; cables are suggested only from agreeing,
  unclaimed evidence between interfaces of matched devices and only created,
  never replaced or deleted.
- **Drive items** (`disks.py`, `disk_execute.py`): drive bays of a matched
  UNAS become NetBox inventory items `Disk <slot>` (create/update only),
  written after device writes with a fresh bay check and read-back.
- **Ports** (`ports.py`): pairs UniFi ports with NetBox interfaces of a
  matched device by connector kind, then family, in numbering order; link
  state and speed are operational and display-only.
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
  immutable journal, read back and marked verified/mismatch/unverified.
  Interrupted creates are reconciled by name, never retried; UniFi sources are
  re-read before writing. Runs are saved by `journal_store.py` to
  `write-journal.sqlite3` next to the config.
  GUI-side per-row overrides (role, site, status, device-type ID) are passed into
  execution for create rows.
- **Pipeline** (`pipeline.py`): Qt-free orchestration. `build_inventory_preview`
  runs refresh → match → delete scoping → preview → plan and returns an
  `InventoryPreviewResult`; `run_write_execution` executes a plan and returns a
  `WriteExecutionReport`. Test end-to-end behavior here, not through the GUI.
- **Review state** (`review.py`): Qt-free state behind the review window
  (device/field selection, per-row create choices, write outcomes); rebuilds
  the change preview and write plan on every selection change.
- **GUI** (`gui.py`, `gui_review.py`, `theme.py`): review-centric main window
  (connection chips, summary cards, review table, detail panel, apply bar),
  settings dialog with NetBox/UniFi/sync pages, and a Fusion theme that follows
  the system light/dark mode. Worker jobs only call pipeline functions. Widgets
  opt into styles via dynamic properties (`variant`, `chip`, `badge`, `banner`,
  `role`); use `theme.set_variant` when changing them at runtime.
  `window_frame.py` sets the app icon (`resources/`, rebuilt by
  `tools/build_icons.py`) and themes native Windows title bars via DWM. Render the
  GUI offscreen for screenshots with `QT_QPA_FONTDIR=C:/Windows/Fonts`.
- **Diagnostics** (`capabilities.py`, `reporting.py`): installed-version field
  capability matrix and opt-in sanitized (pseudonymized) fixture/report export.

Domain invariants to preserve: UniFi is never written; no automatic deletions
(NetBox-only delete proposals are scoped to the active UniFi site by default);
no silently created Custom Fields; missing source values must not clear NetBox
values; offline/stale snapshots cannot authorize writes; never blindly retry a
timed-out create.
