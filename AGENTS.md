# Project Rules

## Inherited Rules

This repository lives in a rule hierarchy. Apply these files in addition to the rules below, in this order of increasing precedence:

| Level | File |
|---|---|
| Global | `../../AGENTS.md` |
| Tools | `../AGENTS.md` |

They define language, Git authority, branches, commit format, versioning principles, documentation style, evidence and the shared Python tool conventions (venv, checks, offline tests, configuration, GUI threading, release builds). This file contains only what is specific to this repository and takes precedence over the inherited files.

If the inherited files are not present, for example in a fresh clone: write all repository content in English, never commit secrets, and never push, tag or publish without the user's approval.

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
- Do not implement automatic deletions or silently create Custom Fields or
  device types. The only Custom Field the app may create is `firmware`;
  device types are created only from a chosen local or devicetype-library
  definition, as a visible, selected and confirmed write step. Existing
  device types are updated only through the editor's confirmed **Sync with
  NetBox** (preflight, dry run, drift check, read-back, write history);
  a template that exists only in NetBox is deleted only when the user
  chooses **Delete in NetBox** for that row (never preselected, preflight
  and read-back as for every sync step), and existing devices are not
  changed.
  Manufacturers, owners, owner groups, tags, platforms and inventory item
  roles are created only through an explicit "New" dialog the user confirms
  (immediate write, journaled, read back). Never create sites or device
  roles, except when restoring a backup.
- Backup and restore (M15): a backup only reads. A restore writes only after
  the confirmed restore dialog (target, mode, selection, dry run available)
  into the target chosen there. Empty NetBox first is the only bulk delete
  the app may do: only after an automatic backup of the target, a dry run
  and typing the target host name. Users, tokens and permissions are never
  read into a backup, restored or deleted; secrets are left out of backups.
- The netbox-community devicetype-library is only read. Local device type
  files keep its form (layout, file names, slugs) but may carry every field
  NetBox supports.
- Public internet sources (techspecs.ui.com, the GitHub devicetype-library)
  are read-only, used only on a user action or a Settings opt-in, and never
  receive data about the user's network beyond a model name or slug.
- Separate configuration from observed operational state. Missing source fields
  must not clear NetBox values. Conflicting identifiers require manual resolution.
- Prefer official local UniFi APIs. Internal endpoints require a demonstrated
  coverage gap and version-specific tests. Do not assume one Network API covers
  Protect, Access or Drive.

## Security and Configuration

- Initial plaintext local token storage is accepted, not considered encryption.
- The developer workstation has direct access to NetBox and UniFi; the external
  developer notebook has none. Live checks run only on the workstation and only
  as explicitly opted-in `integration` tests or manual app runs. Live reads are
  allowed there; every live NetBox write needs explicit user approval for that
  test, limited to dedicated test objects. Never write to UniFi.

## Git and Versions

- Each functional milestone gets its own `feature/...` branch, named in
  `docs/IMPLEMENTATION_PLAN.md`.
- A completed milestone merge into `main` is a release step: it increments `y`,
  resets `z`, gets a tag and a Windows build. Merge a milestone only when the
  user confirms that the milestone is complete; starting implementation does
  not mean the milestone may be merged.
- Version format: `vx.y.z`; numeric package metadata omits `v`. Start from
  `0.0.0`. Version-only release preparation is release metadata, not another
  patch change. Tag the resulting main release; do not tag every development
  commit.
- Every minor or major release also gets a Windows standalone build: after
  tagging, build `dist/unifi2netbox` from the tagged commit with the pinned
  recipe in `docs/DEPLOYMENT.md`, run the native smoke test
  (`tests/test_package.py`) and record version, commit and result there.

## Documentation and Validation

- GUI labels are English.
- Maintain README.md, CHANGELOG.md and relevant reference docs alongside every
  behavior change. Keep milestone checkboxes and verification evidence current.
- Preserve the decisions supplied in the original README questionnaire when
  turning it into application documentation.
- Never claim live API verification without evidence.
- Stop for a decision if Python/PySide6 compatibility requires relaxing an
  explicit requirement.
