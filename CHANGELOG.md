# Changelog

All application changes are documented here. Versions use `vx.y.z`: patch for
ordinary code commits, minor for an approved functional milestone merge, major
only on explicit user instruction. Documentation-only changes have no release tag.

## Unreleased

### Documentation

- Record binding project rules, milestone branches and acceptance criteria.
- Document the agreed read-only UniFi and explicitly approved NetBox workflow.

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