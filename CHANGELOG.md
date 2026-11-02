# Changelog

All application changes are documented here. Versions use `vx.y.z`: patch for
ordinary code commits, minor for an approved functional milestone merge, major
only on explicit user instruction. Documentation-only changes have no release tag.

## Unreleased

## v0.3.33

### Added

- Add export of full UniFi Network API feedback from the current preview state
	as JSON dump (`api_feedback` plus raw device rows).
- Add per-row UniFi raw payload export in `Show all rows` for selected
	UniFi-backed preview rows.

### Changed

- UniFi inventory snapshots now retain raw API page payloads and raw device
	entries to support post-refresh dump export workflows.

### Validation

- Extended inventory, snapshot and GUI tests for raw payload persistence and
	UniFi row/source-id mapping helpers used by row-level dump export.

## v0.3.32

### Changed

- NetBox create payload now uses `role` (NetBox API field) instead of
	`device_role`, improving compatibility with NetBox 4.x create validation.
- Create/update failures now include parsed NetBox response details in error
	messages (for example field-level validation output), not just HTTP status.

### Validation

- Updated write-execution tests to assert the `role` payload field and reran
	focused write-execution checks.

## v0.3.31

### Added

- Add a per-row `Device type` dropdown for create rows in `Show all rows`,
	sourced from the current NetBox device-type catalog and including type IDs.

### Changed

- Create execution now accepts row-level device-type ID overrides; selected
	values are written directly into the create payload and bypass ambiguous
	manufacturer/model auto-resolution.

### Validation

- Extended GUI and write-execution tests for device-type dropdown rendering and
	create execution with explicit device-type ID overrides.

## v0.3.30

### Changed

- Keep NetBox inventory refresh successful when `dcim/devices/_choices/` is
	unavailable or restricted; treat status-choice loading as optional enrichment.
- Infer available device status values from NetBox device rows as a fallback,
	so the create-row `Device status` selector can still be populated in
	read-only/restricted API setups.

### Validation

- Added regression coverage for unavailable status-choice endpoint with
	successful refresh and inferred status catalog fallback.

## v0.3.29

### Added

- Read NetBox device status choices from `dcim/devices/_choices/` during
	inventory refresh and persist them in snapshot state.
- Add a per-row `Device status` dropdown for create rows in `Show all rows`,
	populated from the current NetBox status choices.

### Changed

- Use the selected row status for create execution as an explicit override;
	fallback to NetBox API defaults when no row-specific status is set.

### Validation

- Extended inventory, GUI and write-execution tests for status ingestion,
	row-level status selection and create-status override execution.

## v0.3.28

### Added

- Read NetBox sites from `dcim/sites` during inventory refresh and persist
	them in snapshot state.
- Add a per-row `Device site` dropdown for create rows in `Show all rows`,
	populated from the current NetBox site catalog.

### Changed

- Use the selected row site for create execution as an explicit override;
	fallback to the preview source site when no row-specific site is set.

### Validation

- Extended inventory, GUI and write-execution tests for site ingestion,
	row-level site selection and create-site override execution.

## v0.3.27

### Added

- Read NetBox device roles from `dcim/device-roles` during inventory refresh
	and persist them in snapshot state.
- Add a per-row `Device role` dropdown for create rows in `Show all rows`,
	populated from the current NetBox role catalog.

### Changed

- Use the selected row role for create execution as an explicit override;
	fallback to the configured default role when no row-specific role is set.

### Validation

- Extended inventory, GUI and write-execution tests for role ingestion,
	row-level role selection and create-role override execution.

## v0.3.26

### Changed

- Default UniFi device manufacturer values to `Ubiquiti` when the local API
	payload does not provide a manufacturer field, preventing false
	`missing manufacturer` create blockers.

## v0.3.25

### Changed

- Improve non-executable row diagnostics to prefer row-specific dependency
  context (for example missing required identity fields) over generic plan
  blocker wording.

### Added

- Add per-row `Suggested Device Types` output for create rows in the
  `Show all rows` dialog, based on unmatched UniFi observations and the current
  NetBox device-type catalog.

## v0.3.24

### Added

- Add a `Reason` column in the `Show all rows` dialog so non-executable preview
	rows explain why execution is blocked.
- Show the same row-specific reason in the status bar when executing a selected
	non-executable row is attempted.

### Validation

- Extended GUI coverage for blocked-row reason rendering in
	`tests/test_gui.py`.

## v0.3.22

### Added

- Integrate write execution into the main GUI preview section with a dedicated
	"Execute write plan" action, one confirmation dialog and optional dry-run mode.
- Surface write execution outcomes directly in preview highlights so success,
	failure and skipped operations are visible without leaving the main window.
- Add per-row execution from the `Show all rows` dialog for selected executable
	rows, enabling targeted writes when full-batch execution is blocked.

### Validation

- GUI apply-flow coverage added in `tests/test_gui.py`.

## v0.3.21

### Added

- Add a service-level NetBox write executor for device create/update operations
	with immutable journal outcomes and optional dry-run mode.
- Add behavior setting `default_device_role_name` to support create execution
	with explicit NetBox role resolution.

### Validation

- Added focused executor/config/GUI tests:
	`tests/test_write_execute.py`, `tests/test_unifi_config.py`,
	`tests/test_gui.py`.

### Added

- Extend M5 offline contract coverage for write-plan/read-back behavior:
	idempotent planning, partial-failure read-back filtering, zero read-back on
	cancel without successes, and explicit skips for missing operation sequences.
- Add a behavior setting to include all NetBox devices for delete proposals;
	default behavior keeps NetBox-only delete candidates limited to UniFi site
	scope for safer device-lifecycle review.

### Documentation

- Update implementation/testing docs to mark the M5 cancel/partial-failure/
	concurrent-edit/idempotence test item as completed with focused offline tests.

## v0.3.19

### Changed

- Change deduplication pass order for UniFi observations to strict candidate
	lookup by name, then serial, then MAC (after optional confirmed mappings).
- Treat duplicate candidates inside the active pass as ambiguity conflicts and
	stop fallback escalation for that observation.
- Extend NetBox inventory reads to include paginated `dcim/device-types` data
	and use that template catalog for unmatched create suggestions.

### Validation

- Matching/preview/inventory/snapshot suites cover ordered matching reasons,
	ambiguity behavior and device-type ingestion:
	`tests/test_matching.py`, `tests/test_preview.py`, `tests/test_inventory.py`,
	`tests/test_snapshots.py`.

## v0.3.18

### Added

- Extend deduplication with a normalized-name fallback pass for still-unpaired
	UniFi observations after confirmed and serial/MAC identity passes.
- Keep fallback safe by emitting ambiguity conflicts instead of auto-pairing
	when multiple NetBox devices share the same normalized name.

### Validation

- Matching and GUI suites pass with new name-fallback tests:
	`tests/test_matching.py`, `tests/test_gui.py`.
- Ruff checks pass for matching and GUI modules/tests.

## v0.3.17

### Fixed

- Fix preview-row generation in the GUI by using executable state from
	change-preview items instead of a non-existent write-plan attribute.
- Restore row results in the `Show all rows` dialog after the previous commit
	regression that could suppress all matches/rows.

### Validation

- GUI suite passes with dedicated regression coverage: `tests/test_gui.py`.
- Ruff checks pass for `gui.py` and GUI tests.

## v0.3.16

### Added

- Add filtering controls to the `Show all rows` dialog: action filter
	(`All/Create/Update/Target only`) and `Executable only` toggle.
- Keep filtering local to the dialog so users can quickly narrow larger
	preview tables without refreshing inventory data.

### Validation

- GUI suite passes with row-filter behavior checks: `tests/test_gui.py`.
- Ruff checks pass for `gui.py` and GUI tests.

## v0.3.15

### Added

- Add a non-modal `Show all rows` dialog for inventory preview data.
- Display complete preview rows in a table with device key, action, labels,
  selected fields and executable state.

### Validation

- GUI suite passes with dialog/table checks: `tests/test_gui.py`.
- Ruff checks pass for `gui.py` and GUI tests.

## v0.3.14

### Added

- Add `Copy selected` and `Copy all` actions for inventory preview highlights.
- Write copied highlight text directly to the system clipboard and report the
	action in the status bar for immediate feedback.

### Validation

- GUI suite passes with clipboard interaction tests: `tests/test_gui.py`.
- Ruff checks pass for `gui.py` and GUI tests.

## v0.3.13

### Added

- Ensure inventory preview highlights always include at least one visible detail
	line for `Partial`/`Unavailable` states.
- Add explicit empty-NetBox guidance and unmatched/plan-issue fallback lines so
	users see why no direct matches are shown yet.
- Set a minimum list height for preview highlights to avoid collapsed rendering.

### Validation

- GUI suite passes with new fallback-detail test: `tests/test_gui.py`.
- Ruff checks pass for `gui.py` and GUI tests.

## v0.3.12

### Added

- Replace the inventory preview action icon with a clearer info-style symbol to
	distinguish it from connection checks.
- Add a clickable inventory highlight list with a dedicated detail field so
	users can inspect preview items directly in the main window.

### Validation

- GUI suite passes with interactive highlight selection checks:
	`tests/test_gui.py`.
- Ruff checks pass for `gui.py` and GUI tests.

## v0.3.11

### Added

- Extend the GUI inventory preview with structured highlight lines for matched
	pairs, detected conflicts and planned write operations.
- Keep preview highlights read-only and capped to concise top entries so results
	remain scannable in the main window.

### Validation

- GUI suite passes with highlight rendering checks: `tests/test_gui.py`.
- Ruff checks pass for `gui.py` and GUI tests.

## v0.3.10

### Added

- Add a visible Inventory Preview section in the main GUI with counts for
	NetBox/UniFi devices, matches, conflicts, preview rows and executable
	operations.
- Add a background "Refresh Inventory Preview" action that reads snapshots,
	computes dedup/preview/write-plan summaries and updates UI state safely.

### Validation

- GUI suite passes with new preview-state tests: `tests/test_gui.py`.
- Ruff checks pass for `gui.py` and GUI tests.

## v0.3.9

### Added

- Add a read-only read-back planner for successful M5 operations that resolves
	NetBox object IDs for create/update verification reads.
- Skip successful create outcomes without object IDs so unresolved results stay
	explicit and can be reconciled manually.

### Validation

- Focused offline suite passes: `tests/test_write_readback.py`.
- Ruff checks pass for `write_readback.py` and read-back tests.

## v0.3.8

### Added

- Add a write-journal reconcile helper that flags ambiguous successful create
	outcomes when NetBox object IDs are missing or duplicated.
- Keep reconcile evaluation read-only and deterministic for later manual
	resolution and read-back slices.

### Validation

- Focused offline suite passes: `tests/test_write_journal.py`.
- Ruff checks pass for `write_journal.py` and journal tests.

## v0.3.7

### Added

- Add an immutable write journal model for M5 operation outcomes (`pending`,
	`success`, `failed`, `skipped`) without introducing API write execution.
- Add journal initialization, per-operation result updates, finalization and
	summary counters for later M5 execution/reconciliation slices.

### Validation

- Focused offline suite passes: `tests/test_write_journal.py`.
- Ruff checks pass for `write_journal.py` and journal tests.

## v0.3.6

### Added

- Add a write-plan confirmation summary model with operation totals, blocker
	counts, blocked device keys and a single user-facing confirmation message.
- Keep M5 execution planning immutable and read-only while making confirmation
	readiness explicit (`requires_confirmation` vs `executable`).

### Validation

- Focused offline suite passes: `tests/test_write_plan.py`.
- Ruff checks pass for `write_plan.py` and write-plan tests.

## v0.3.5

### Added

- Add a read-only write-planning service model that derives ordered create/update
	operations from immutable M4 change previews.
- Add M5 preflight blockers for dependency failures, duplicate create labels and
	duplicate update targets before any write execution layer exists.
- Add deterministic operation sequencing (create before update) to prepare a
	single summary confirmation flow in later M5 slices.

### Validation

- Focused offline suite passes: `tests/test_write_plan.py`.
- Ruff checks pass for `write_plan.py` and write-plan tests.

## v0.3.4

### Added

- Add immutable change-preview summaries with explicit dependency contracts per
	device action.
- Add create prerequisites (`name`, `site`) and model/manufacturer dependency
	rules without introducing write paths.
- Add executable versus blocked change state to expose write readiness decisions.

### Validation

- Focused offline suite passes: `tests/test_preview.py`.
- Ruff checks pass for `preview.py` and preview tests.

## v0.3.3

### Added

- Add a difference-preview service model with source/target values and explicit
	provenance for matched, create and target-only device views.
- Add configured/operational field categories and unsupported field markers for
	preview-only visibility.
- Add batch, device and field selection helpers for immutable preview state.

### Validation

- Focused offline suite passes: `tests/test_preview.py`.
- Ruff checks pass for `preview.py` and preview tests.

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