# Changelog

All application changes are documented here. Versions use `vx.y.z`: patch for
ordinary code commits, minor for an approved functional milestone merge, major
only on explicit user instruction. Documentation-only changes have no release tag.

## Unreleased

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