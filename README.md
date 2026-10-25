# unifi2netbox

Python desktop application for reviewing UniFi inventory differences before
applying selected changes to NetBox. This branch currently implements NetBox
configuration and a read-only connection layer. The GUI follows in the next patch.

## Goals

 - Read local UniFi APIs; never modify UniFi.
 - Display and approve individual fields, devices or batches before NetBox writes.
	 Approving a device does not prompt again for every field.
 - Match stable identities and expose conflicts; suggest manufacturer/model-based
	 NetBox Device Types only for devices not already mapped.
 - Cover port profiles/overrides, native/tagged VLANs, interfaces, IP/MAC, PoE,
	 LAG and LLDP where verified API data and standard NetBox fields allow it.
 - Separate configuration from operational state. No automatic deletions or
	 unapproved Custom Fields. Network first, then Protect, Access and Drive.
 - Show last successful snapshots when offline; startup checks and Refresh never
	 imply permission to write. Apply requires a confirmed current preview.

Initially support one controller/site. Equipment inventory includes cameras,
NVRs, Access hardware and UNAS where their separate APIs allow it. Recordings,
file content and personal access records are excluded. All UI/code/docs are English.

## Compatibility

| Component | Target / Evidence |
| --- | --- |
| Python | >=3.15.1; standard CPython 3.15.1 verified locally |
| GUI | PySide6 6.12.0; basic Windows startup verified |
| NetBox | Community 4.7.x; target 4.7.3 / netbox-docker 5.1.1 |
| Client | pynetbox 7.9.0 |
| Windows | Windows 11 25H2/26H2 acceptance targets |
| Linux | Ubuntu/Kubuntu 26.04 LTS/26.10; not yet tested |
| Network | UDM Pro Max OS 5.1.33 / Network 10.6.100; later milestone |
| Protect | UNVR 6.0.11 / Protect 7.3.70; later milestone |
| Access | 4.3.22; later milestone |
| Drive | UNAS Pro 6.0.11 / Drive 4.4.20; later capability gate |

Future Python versions are not automatically certified. Live infrastructure and
packaged deployment are unverified until tested. The development PC cannot reach
the infrastructure; default tests use fixtures and block live sockets.

## Installation

Install Python >=3.15.1 and check `python --version` inside `.venv`.

Windows PowerShell, with the Python launcher:

```powershell
py -3.15 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Alternatively, with uv: `uv venv --python 3.15.1 --seed .venv`, then activate and
install as above. Ubuntu/Kubuntu with a separately installed Python 3.15:

```bash
python3.15 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Install the matching venv package if required. Never replace system Python or use
`--break-system-packages`. Native EXE/Linux package deployment remains planned.

## Configuration and Security

Default local TOML configuration, outside the repository:

- Windows: `%LOCALAPPDATA%\unifi2netbox\config.toml`.
- Linux: `${XDG_CONFIG_HOME:-~/.config}/unifi2netbox/config.toml`.

[config.example.toml](config.example.toml) contains placeholders. Enter an explicit
`http://` or `https://` base URL without `/api`, credentials, query or fragment.
Reverse-proxy subpaths are supported; port 8000 does not determine the scheme.

TLS verification defaults on. Use a private CA file or explicitly disable checks
per connection. Self-signed certificates can be trusted with the correct CA.
HTTP transmits tokens unencrypted; disabled verification weakens authentication.
Tokens are initially plaintext locally, not encrypted. Restrict file access.
Never commit real configuration, tokens, logs, raw captures or inventory caches.

This milestone needs a dedicated token with device-read permission, not writes.
Online requires successful authenticated API status/version and device inventory
reads, even for an empty inventory. Redirects are refused. See
[connection behavior](docs/CONNECTIONS.md) for outcomes and timeout semantics.
GUI settings and startup instructions follow with the GUI patch.

## Development and Testing

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -m "not integration"
python -m ruff check .
python -m ruff format --check .
```

[Testing instructions](docs/TESTING.md) cover offline tests and the separate
target-PC acceptance workflow. Return only sanitized reports including exact
commit/application/Python/OS/API versions. No live writes run by default.

## Roadmap and Rules

See [the detailed plan](docs/IMPLEMENTATION_PLAN.md), [project rules](AGENTS.md)
and [changelog](CHANGELOG.md). M1 is NetBox connectivity; M2 adds independent
Network status. Inventory/snapshots, matching, approved writes, ports/VLANs,
Protect, Access, Drive and deployment follow as separate functional milestones.

Each milestone gets one branch and small commits. Ordinary code commits increment
patch; approved milestone merges increment minor and reset patch. Major changes
require user instruction. Documentation-only commits have no version/tag.
Commit messages have an English subject plus short bullets. Direct commits are
authorized; every merge to main needs explicit approval.

## License

MIT; see [LICENSE](LICENSE). Dependencies retain their respective licenses.
# unifi2netbox