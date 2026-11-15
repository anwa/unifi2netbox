# Deployment

## Initial Windows Standalone Gate

Use the same Python >=3.15.1 `.venv` as the source installation. Build on Windows;
cross-compiling a Windows executable from Linux is not supported by this recipe.
This early smoke build is not the final installer or a signed production release.

Verified locally with CPython 3.15.1, PySide6 6.12.0 and PyInstaller 6.22.3 on
Windows 11: native windowed EXE starts with version 0.0.2, opens first-run settings
and exits cleanly after settings/main windows close. No live API was exercised.

Release 0.1.0 was rebuilt with the same pinned tools and passed the separately
enabled native startup/shutdown test on 2026-10-25. This verifies the versioned
release window, not a repeat of the user's live NetBox acceptance.

M2 development version 0.1.3 was rebuilt with the same tools on 2026-10-25.
Its versioned native window and first-run dialog pass the opt-in startup/shutdown
test. Source GUI checks cover both connection areas and UniFi settings. No live
UniFi access, Linux build or target-PC package acceptance is claimed.

Version 0.1.4 was rebuilt on 2026-10-25 and passed the native startup/shutdown
test with the single first-run Settings dialog. The package now exposes the same
NetBox/UniFi tabs and common Check Connections action as the source application.

Since v0.9.0 every approved minor or major release is built this way from its
tagged commit and smoke-tested before the release counts as complete. Earlier
releases (v0.2.0 to v0.8.0) were not rebuilt; build them from their tags if
needed.

Release v0.9.0 (tag commit dfca950) was built on 2026-11-14 on the developer
workstation with CPython 3.15.1 and PyInstaller 6.22.3 from a clean working tree
at the tag; the directory is about 132 MB. The native startup/shutdown test passed
(1 passed). No live API was exercised by the packaged app.

Release v0.10.0 (tag commit e2c5987) was built on 2026-11-14 the same way from
a clean working tree at the tag (about 132 MB); the native startup/shutdown
test passed (1 passed). No live API was exercised by the packaged app.

Release v1.0.0 (tag commit 1b7f429) was built on 2026-11-14 with
`tools/build_windows.ps1` from a clean working tree at the tag: bundle check
and native smoke test passed, installer `unifi2netbox-1.0.0-setup.exe`
(43.5 MB). The Packages workflow built `unifi2netbox_1.0.0_amd64.deb` and the
Linux tarball from the same tag and passed its offscreen smoke tests. All
three files and `SHA256SUMS.txt` are attached to the public GitHub release
v1.0.0 (approved by the user). The Windows build is not code-signed.

Release v1.1.0 (tag v1.1.0 on merge commit 1adddc4) was built on 2026-11-15
with `tools/build_windows.ps1` from a clean detached worktree at the tag
(the main checkout held an untracked user file): bundle check and native
smoke test passed (1 passed, 1 skipped), the exe reports `1.1.0`, the
directory is about 132 MB and the installer `unifi2netbox-1.1.0-setup.exe`
is 43.6 MB (SHA-256
`000DEA447FA66B29F4B3985B7A683A62D152F1EDFDC41D19E3D0473E6C2FB9E5`). The
Offline Tests workflow passed for main and the tag. Installer install,
upgrade and uninstall were not repeated for this version, and the packaged
app was not run against the live APIs. The Windows build is not code-signed.

```powershell
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean --windowed --onedir --name unifi2netbox --icon src/unifi2netbox/resources/unifi2netbox.ico --paths src --recursive-copy-metadata unifi2netbox --add-data "LICENSE:." --add-data "docs/THIRD_PARTY_NOTICES.md:." --add-data "src/unifi2netbox/resources:unifi2netbox/resources" src/unifi2netbox/__main__.py
```

Since 0.10.1 the recipe embeds the application icon (`--icon`) and bundles
the icon resources the windows use (`--add-data .../resources`).

The executable is `dist/unifi2netbox/unifi2netbox.exe`. Distribute the entire
`dist/unifi2netbox` directory, not just the executable. The standalone directory
uses shared Qt libraries, supporting replacement and dependency-license review.
Build files, spec files and distribution output are ignored by Git.

Runtime configuration remains per-user and outside this directory. Never add
your configuration, cache, captures or tokens to a build. Dependency metadata,
including available license files, is copied recursively; review the resulting
notices/license material before redistribution. See [third-party notices](THIRD_PARTY_NOTICES.md).

## Windows Installer

Since M10 the Windows release is a per-user installer built with Inno Setup 6
(`winget install --id JRSoftware.InnoSetup --scope user`). From the
repository root, in the activated `.venv` and on a clean working tree:

```powershell
.\tools\build_windows.ps1
```

The script runs the PyInstaller recipe above, fails if a `config.toml`,
`snapshots.sqlite3`, `write-journal.sqlite3` or capture file is in the bundle
or a license notice is missing, runs the native smoke test and compiles
`packaging\windows\unifi2netbox.iss` into
`dist\installer\unifi2netbox-<version>-setup.exe`.

The installer needs no administrator rights and installs to
`%LOCALAPPDATA%\Programs\unifi2netbox` with a Start menu entry (desktop icon
optional). A newer installer upgrades in place (same AppId) and removes the
files of the previous build first. Silent use:
`unifi2netbox-<version>-setup.exe /VERYSILENT /SUPPRESSMSGBOXES`.

### Data policy for upgrade and uninstall

Settings, tokens, snapshots and the write history live in
`%LOCALAPPDATA%\unifi2netbox` (`config.toml`, `snapshots.sqlite3`,
`write-journal.sqlite3`). Setup, upgrades and the uninstaller never touch this
folder, so a reinstall keeps the configuration. To remove everything, uninstall
the app and then delete that folder yourself; it contains your API tokens in
plain text.

Verified on 2026-11-14 with 0.10.3 on the developer workstation (Windows 11):
build, silent install into a test folder, reinstall over it, smoke test of the
installed exe and silent uninstall; the configuration folder was unchanged.

## Native Windows Smoke Test

Install development requirements too, then explicitly select the artifact:

```powershell
$env:UNIFI2NETBOX_EXE = (Resolve-Path dist/unifi2netbox/unifi2netbox.exe).Path
python -m pytest tests/test_package.py -q
Remove-Item Env:UNIFI2NETBOX_EXE
```

The test uses a temporary empty configuration, does not contact any server and
does not write tokens. It verifies the exact versioned native window title and
graceful exit. Without the explicit environment variable, this test is skipped.
This is not a substitute for live NetBox acceptance on the target PC.

## Linux Packages

Linux packages are built on Ubuntu, normally by the **Packages** GitHub Actions
workflow (`.github/workflows/package.yml`, on pushes to `main` and `v*` tags,
or manually). Locally on Ubuntu with Python
3.15 in an activated `.venv`:

```bash
python -m pip install -r requirements-build.txt -r requirements-dev.txt
bash tools/build_linux.sh
```

Output in `dist/`: the standalone folder `unifi2netbox/`, the tarball
`unifi2netbox-<version>-linux-x86_64.tar.gz` and
`unifi2netbox_<version>_amd64.deb`. The `.deb` installs the folder to
`/opt/unifi2netbox`, links `/usr/bin/unifi2netbox` and adds a desktop entry
and hicolor icons; it depends on the usual Qt runtime libraries (OpenGL/EGL,
fontconfig, D-Bus, xkbcommon, xcb-cursor). Install with
`sudo apt install ./unifi2netbox_<version>_amd64.deb`.

Settings, tokens, snapshots and the write history stay per user in
`~/.config/unifi2netbox`; installing, upgrading or removing the package never
touches them. Delete that folder yourself to remove everything.

The workflow smoke-tests the standalone build and the installed launcher
offscreen (`--version`, then `--smoke-test`, which shows the main window and
exits), removes the package again and keeps the `.deb` and tarball as
workflow artifacts for 14 days. Nothing is published as a release without
approval.

Verified on 2026-11-14 by GitHub Actions only (Ubuntu 24.04 runner, offscreen,
commit c6b183d, version 0.10.4). Ubuntu/Kubuntu 26.04 and a real Linux desktop
are unverified; never describe the CI build as verified desktop deployment.