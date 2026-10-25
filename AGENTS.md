# Project Rules

## Scope and Architecture

- Read this file and `docs/IMPLEMENTATION_PLAN.md` before starting work.
- Implement one approved functional milestone at a time. Start with NetBox
  connection status, then UniFi Network connection status.
- Use Python >=3.15.1, PySide6 Qt Widgets, pynetbox for NetBox, httpx for UniFi,
  and GUI-editable TOML configuration. Use a local `.venv`.
- Target Windows 11 25H2/26H2 and Ubuntu/Kubuntu 26.04 LTS/26.10.
  Report actual verification separately from intended support.
- Keep network operations outside the GUI thread; update widgets only on the
  GUI thread. Bound concurrency and network timeouts.
- UniFi is read-only. NetBox mutations require an explicit preview and approval.
  Support field, device and batch approval without per-field repeated prompts.
- Do not implement automatic deletions or silently create Custom Fields.
- Separate configuration from observed operational state. Missing source fields
  must not clear NetBox values. Conflicting identifiers require manual resolution.
- Prefer official local UniFi APIs. Internal endpoints require a demonstrated
  coverage gap and version-specific tests. Do not assume one Network API covers
  Protect, Access or Drive.

## Security and Configuration

- Read all hosts, tokens and connection settings from configuration, not code.
  Allow editing through the GUI. Default configuration lives outside the repo.
- TLS verification defaults on and can be disabled independently per connection.
  Support private CA certificates and warn about disabled TLS checks/plain HTTP.
- Initial plaintext local token storage is accepted, not considered encryption.
  Never log secrets or commit real configuration, cache, raw captures or reports.
- Do not contact the user's infrastructure from default tests. This development
  machine has no access to it. Live tests require explicit opt-in on the target PC.

## Git and Versions

- Each functional milestone gets its own branch; do not implement on `main`.
- Preserve user changes. Stage only reviewed, intended files. Do not use `git add .`.
- Direct commits are authorized. Merging into `main` requires explicit approval;
  starting implementation does not grant merge approval.
- Use small commits with an English type-prefixed subject (<=72 characters)
  and a short, meaningful bullet list.
- Version format: `vx.y.z`; numeric package metadata omits `v`.
- Every ordinary code-changing commit increments `z`. Start from `0.0.0`.
  Pure documentation commits do not change versions or create tags.
- An approved completed milestone merge increments `y` and resets `z` to zero.
  Version-only release preparation is release metadata, not another patch change.
  Tag the resulting approved main release; do not tag every development commit.
- Only the user may authorize a major version increment.

## Documentation and Validation

- Write code, GUI labels, commit messages and repository documentation in English.
  Communicate with the user in German.
- Maintain README.md, CHANGELOG.md and relevant reference docs alongside every
  behavior change. Keep milestone checkboxes and verification evidence current.
- Preserve the decisions supplied in the original README questionnaire when
  turning it into application documentation.
- Run focused tests after each substantive change, then milestone-wide checks.
  Never claim live API, Linux or packaged-app verification without evidence.
- Before committing, review the staged diff, check for secrets, check version
  consistency and run the relevant tests. Do not commit failing code as complete.
- Use `python -m pytest`, `python -m ruff check .` and
  `python -m ruff format --check .` once the development environment exists.
- Stop for a decision if Python/PySide6 compatibility requires relaxing an
  explicit requirement. Do not bypass dependency version constraints.