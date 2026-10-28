# Changelog

All application changes are documented here. Versions use `vx.y.z`: patch for
ordinary code commits, minor for an approved functional milestone merge, major
only on explicit user instruction. Documentation-only changes have no release tag.

## Unreleased

## v0.3.2

### Added

- Add explainable Device Type suggestions for unmatched UniFi observations only.
- Rank suggestions by manufacturer/model similarity against existing NetBox
	manufacturer/model combinations.
- Keep suggestions read-only and exclude already matched observations.

### Validation

- Focused offline suite passes: `tests/test_matching.py`.
- Ruff checks pass for updated matching service and tests.

## v0.3.1

### Added

- Add an identity deduplication service for cross-source NetBox/UniFi matching.
- Add confirmed mapping support with explicit conflict detection for duplicate
	targets and missing mapping endpoints.
- Add ambiguity diagnostics when one UniFi observation matches multiple NetBox
	candidates by identity evidence.

### Validation

- Focused offline suite passes: `tests/test_matching.py`.
- Ruff checks pass for `matching.py` and matching tests.

## v0.3.0

### Summary

- Third functional milestone: inventory snapshots and diagnostics foundations.

### Added

- Read-only paginated NetBox/UniFi inventory readers with normalized timestamped
	snapshot models.
- Versioned SQLite snapshot state with current/previous records and refresh
	service foundations.
- Stale/offline cache browsing plus partial-read diagnostics without write paths.
- Explicit opt-in sanitized fixture/report export with deterministic
	pseudonymization for sensitive identifiers.
- Installed-version capability matrix for ports, profiles, overrides, VLAN,
	PoE, speed/duplex, LAG and LLDP.

### Validation

- Milestone-wide offline gate: 130 passed, 1 skipped, 0 failed.
- Ruff lint and format checks pass for the full workspace.

### Compatibility

- Existing settings and snapshot schema remain compatible without migration.
- Linux and exact target-platform verification remain unreported.

## v0.2.5

### Added

- Add an installed-version capability matrix builder for ports, profiles,
	overrides, VLAN, PoE, speed/duplex, LAG and LLDP.
- Add per-field status mapping (`Verified`, `Unverified`, `Missing`) with
	UniFi evidence hints and intended NetBox targets.
- Add markdown rendering support for capability-matrix reporting.

### Validation

- Focused offline suite passes: `tests/test_capabilities.py`.
- Ruff checks pass for `capabilities.py` and matrix tests.

## v0.2.4

### Added

- Add an explicit opt-in snapshot fixture/report export service for target-PC sharing.
- Add deterministic pseudonymization for source IDs, names, serials, MAC addresses,
  sites and snapshot scope in exported fixtures.
- Add export controls for including or omitting previous snapshots per source.

### Validation

- Focused offline suite passes: `tests/test_reporting.py`.
- Ruff checks pass for `reporting.py` and export tests.

## v0.2.3

### Added

- Add stale/offline cache browsing based on stored current/previous snapshots.
- Add partial-refresh diagnostics that preserve and reuse the last successful
	cached snapshot when a source refresh fails.
- Add freshness checks for cached snapshots and expose stale indicators in the
	refresh/browse service results.

### Validation

- Focused offline suite passes: `tests/test_refresh.py` and `tests/test_snapshots.py`.
- Ruff checks pass for updated refresh/snapshot services and tests.

## v0.2.2

### Added

- Add a versioned SQLite snapshot store for per-source current/previous inventory snapshots.
- Add an internal refresh service that persists successful reads and reports per-source failures.
- Add offline contract tests for schema checks, current/previous rollover and refresh behavior.

### Validation

- Focused offline suite passes: `tests/test_snapshots.py` and `tests/test_refresh.py`.
- Ruff checks pass for `snapshots.py`, `refresh.py` and the new tests.

## v0.2.1

### Added

- Add M3 inventory-reader foundations with normalized timestamped snapshot models.
- Add read-only paginated NetBox and UniFi Network inventory readers with bounded
	pagination checks and schema validation.
- Add offline contract tests for normalized pagination reads and failure handling.

### Validation

- Focused offline suite passes: `tests/test_inventory.py`, `tests/test_netbox.py`
	and `tests/test_unifi.py` (51 tests).
- Ruff checks pass for the new inventory reader and its tests.

## v0.2.0 - 2026-10-28

### Summary

- Second approved functional milestone: UniFi Network connection status with the
	shared NetBox/UniFi Settings and Check Connections workflow.

### Changed

- Promote the accepted M2 milestone from development version 0.1.4 to 0.2.0.

### Documentation

- Record user-reported target-PC confirmation of the revised 0.1.4 unified
	Settings and shared Check Connections workflow on 2026-10-28.
- Record the approved M2 merge to main and v0.2.0 release preparation.

### Validation

- M2 local gates remained green at release preparation: 109 offline tests pass,
	optional native package test skipped by default.
- Fresh Windows standalone 0.1.4 startup/shutdown passed in its separately
	enabled native test.
- Ruff lint/format and editor diagnostics remained clean for the milestone slice.

### Compatibility

- Existing TOML files need no migration; API endpoints and authentication are unchanged.
- Linux and exact target-platform coverage remain unverified.

## v0.1.4

### Changed

- Replace separate service dialogs with one Settings dialog and NetBox/UniFi tabs.
- Use one Check Connections action in the main window and one shared test command
	in Settings; both test all connections while reporting separate results.
- Validate both tabs before a single atomic save; Cancel preserves both sections.
- Wait for both settings checks before enabling controls or completing a close.

### Documentation

- Record user-reported success of the preceding M2 online tests on 2026-10-25.
- Update the unified-settings workflow and targeted confirmation checklist.

### Validation

- 109 offline tests pass; the optional native package test is skipped by default.
- Fresh Windows standalone 0.1.4 passes its separately enabled startup/shutdown test.
- Ruff lint/format and editor diagnostics pass; both tabs and compact layout reviewed.

### Compatibility

- Existing TOML files need no migration; API endpoints and authentication are unchanged.
- The user reported revised GUI target-PC acceptance passed on 2026-10-28.
- Linux remained unverified at this development patch level.

## v0.1.3

### Added

- Independent NetBox/UniFi status areas, startup checks and settings actions.
- UniFi API-key masking, independent TLS/CA settings and editable discovered-site selection.
- Shared status workflow with stale-result rejection and shutdown of both workers.

### Documentation

- Document both GUI workflows and the UniFi target-PC acceptance checklist.

### Validation

- 101 offline tests pass; the optional native package test is skipped by default.
- A fresh Windows standalone 0.1.3 build passes its separately enabled startup/shutdown test.
- Ruff lint/format and editor diagnostics pass; normal/compact Qt screenshots reviewed.

### Compatibility

- The user subsequently reported the M2 online tests passed on 2026-10-25.
- Linux remains unverified; M2 is not merged or tagged.

## v0.1.2

### Added

- Read-only local UniFi Network API checks for version, sites and device access.
- Bounded site discovery, explicit multi-site selection and endpoint capability errors.
- Independent TLS/timeout handling and synthetic HTTP contract tests; no login fallback.

### Validation

- 94 offline tests pass, including both API adapters; optional package test skipped.
- TLS configuration, private CA, pagination limits and sanitized failures covered.

### Compatibility

- Target Network 10.6 with live 10.6.100 verification still pending. Public 10.6.106
	schemas are a reference only. GUI integration follows in the next patch.

## v0.1.1

### Added

- Independent UniFi Network TOML settings for console URL, API key, site and TLS.
- Preserve NetBox settings, unknown tables and comments when editing either service.

### Validation

- 62 offline tests pass; the optional native package test is skipped by default.
- Ruff lint/format and editor diagnostics pass for the configuration slice.

### Compatibility

- Existing NetBox-only configuration works without migration. UniFi GUI/API follow
	in the next M2 patch; no UniFi live connectivity is claimed yet.

## v0.1.0 - 2026-10-25

### Summary

- First approved functional milestone: NetBox connection status in a desktop GUI.

### Added

- Authenticated read-only NetBox checks, editable TOML settings and background jobs.
- TLS/CA options, masked tokens, startup/manual checks and a Windows build recipe.

### Changed

- Promote the accepted NetBox milestone from development version 0.0.2 to 0.1.0.

### Fixed

- No additional behavior fixes in this release-preparation change.

### Documentation

- Record binding project rules, milestone branches and acceptance criteria.
- Document the agreed read-only UniFi and explicitly approved NetBox workflow.
- Record the user's successful NetBox online acceptance on 2026-10-25.
- Keep unreported environment details and pending Linux coverage explicit.

### Validation

- Release 0.1.0: 50 offline tests passed; the opt-in package test is skipped by default.
- The separately enabled native Windows EXE startup/shutdown test passed for 0.1.0.
- Release metadata, Ruff lint and Ruff format checks passed.
- NetBox online acceptance passed according to the user on 2026-10-25.

### Compatibility

- Python >=3.15.1, PySide6 6.12.0, pynetbox 7.9.0 and the NetBox 4.7 API.
- Linux and exact target-OS coverage remain unverified. UniFi is not implemented.
- The user explicitly approved the main merge and v0.1.0 release on 2026-10-25.

## v0.0.2

### Added

- PySide6 window showing NetBox status, endpoint, version and last check.
- Editable settings with masked tokens, CA file selection, TLS warnings and timeout.
- Test unsaved connections, save atomically or cancel without changing settings.
- Background startup/manual checks, stale-result protection and safe worker shutdown.
- Module and installed command entry points, including explicit config path/version.
- Pinned Windows standalone build recipe, license notices and opt-in native smoke test.
- Windows/Linux offline CI definition; no infrastructure credentials required.

### Documentation

- Describe GUI startup, configuration recovery and target-PC acceptance steps.

### Validation

- 50 offline tests pass; opt-in package test is skipped in the normal suite.
- Native Windows standalone EXE window startup and graceful shutdown pass separately.
- Ruff lint/format and editor diagnostics pass. GUI screenshots checked with synthetic data.

### Compatibility

- Python 3.15.1 / Qt 6.12 source and standalone checks on local Windows 11.
- NetBox online acceptance reported passed by the user on 2026-10-25.
- Linux and exact target-OS coverage remain unverified; no merge/tag created.

## v0.0.1

### Added

- Validated NetBox settings with atomic TOML saves and per-user configuration paths.
- Read-only authenticated NetBox 4.7 inventory check with timeouts and redirect refusal.
- Explicit connection outcomes and independent TLS/CA configuration.

### Documentation

- Document the isolated environment, offline tests and target-PC acceptance process.

### Validation

- Add synthetic adapter and configuration tests; default tests forbid live sockets.

### Compatibility

- Python >=3.15.1, PySide6 6.12.0 and pynetbox 7.9.0. GUI arrives in the next patch.