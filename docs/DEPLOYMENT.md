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
The Packages workflow built `unifi2netbox_1.1.0_amd64.deb` and the Linux
tarball from the same tag and passed its offscreen smoke tests. All three
files and `SHA256SUMS.txt` are attached to the public GitHub release v1.1.0
(approved by the user on 2026-11-15).

Release v1.1.1 (tag v1.1.1 on merge commit 02fa9c0, patch release with the
user manual) was built on 2026-11-15 the same way from a clean detached
worktree at the tag: bundle check (now including `manual/index.md`) and
native smoke test passed (1 passed, 1 skipped), the exe reports `1.1.1`, the
bundle holds the manual with its 22 screenshots, and the installer
`unifi2netbox-1.1.1-setup.exe` is 45.4 MB (SHA-256
`20DF2D8F536647E4D5D83EC2AAB74C8222590049E3C83B9F57046E76BD858D92`). The
Offline Tests and Packages workflows passed for main and the tag; the Linux
tarball contains the manual. All three files and `SHA256SUMS.txt` are
attached to the public GitHub release v1.1.1 (requested by the user). Not
verified: installer upgrade/uninstall for this version and opening the
manual window in the packaged app. The Windows build is not code-signed.

Release v1.1.2 (tag v1.1.2 on merge commit 5b980f5, fix release for the
title bar of reopened windows) was built on 2026-11-15 the same way from a
clean detached worktree at the tag: bundle check and native smoke test
passed (1 passed, 1 skipped), the exe reports `1.1.2`, and the installer
`unifi2netbox-1.1.2-setup.exe` is 45.4 MB (SHA-256
`3EB27CC8CAE2F83A83103C1A6FC6FEAE13CA79FA5A7D9083B7C6C5773EC64DEE`). The
Offline Tests and Packages workflows passed for main and the tag. All three
files and `SHA256SUMS.txt` are attached to the public GitHub release v1.1.2
(requested by the user). Not verified: installer upgrade/uninstall for this
version. The Windows build is not code-signed.

Release v1.2.0 (tag v1.2.0 on merge commit 5420357, milestone M12 device
types) was built on 2026-11-16 the same way from a clean detached worktree at
the tag: bundle check (including `manual/index.md`) and native smoke test
passed (1 passed, 1 skipped), the exe reports `1.2.0`, the directory is about
136 MB and the installer `unifi2netbox-1.2.0-setup.exe` is 46.6 MB (SHA-256
`1716D1035B14561001833278274607055EC65A999051C3F529C771933436222A`). The
bundle contains the device type schema
(`_internal/unifi2netbox/resources/devicetype-schema`) and the
`jsonschema_specifications` data; ruamel.yaml and jsonschema are imported at
start-up, so the smoke test covers their presence. The Offline Tests and
Packages workflows passed for main and the tag. Not verified: installer
upgrade/uninstall for this version, and validating, importing or fetching
device types inside the packaged app. The Windows build is not code-signed.
The Packages workflow built `unifi2netbox_1.2.0_amd64.deb` and the Linux
tarball (which contains the schema) from the same tag. All three files and
`SHA256SUMS.txt` are attached to the public GitHub release v1.2.0 (approved by
the user on 2026-11-16).

Release v1.3.0 (tag v1.3.0 on merge commit b5571b6, milestone M13
NetBox-complete device types) was built on 2026-11-17 the same way from a
clean detached worktree at the tag: bundle check and native smoke test passed
(1 passed, 1 skipped), the exe reports `1.3.0`, the directory is about 135 MB
and the installer `unifi2netbox-1.3.0-setup.exe` is 44.6 MB (SHA-256
`D1DD88052E8B12B0F053447BB86F28312CF34879B14402DBBF552BFC18620330`). The
bundle contains the NetBox field metadata
(`_internal/unifi2netbox/resources/netbox-metadata/netbox-4.7.json`), the
device type schema and the new manual page. The Offline Tests workflow passed
for main and the tag, and the Packages workflow passed for both. Not
verified: installer upgrade/uninstall for this version, and the editor's
NetBox drop-downs, New dialogs or an import inside the packaged app. The
Windows build is not code-signed. The Packages workflow built
`unifi2netbox_1.3.0_amd64.deb` and the Linux tarball (which contains the
NetBox metadata and the new manual page) from the same tag. All three files
and `SHA256SUMS.txt` are attached to the public GitHub release v1.3.0
(approved by the user on 2026-11-17).

Release v1.4.0 (tag v1.4.0 on merge commit f555ada, milestone M14 device
types synced with NetBox) was built on 2026-11-17 the same way from a clean
detached worktree at the tag: bundle check and native smoke test passed
(1 passed, 1 skipped), the exe reports `1.4.0`, the directory is about
135 MB and the installer `unifi2netbox-1.4.0-setup.exe` is 44.8 MB (SHA-256
`173CDF8FF0751DA6476AD1940A83BAED1492AE4209951C78A5F0FB56084DECDF`), also
copied to the local `dist\installer\`. The bundle contains the new manual
page and the NetBox metadata. Not verified: installer upgrade/uninstall for
this version, and the editor's NetBox comparison or sync inside the packaged
app. The Windows build is not code-signed.
The Offline Tests and Packages workflows passed for main and the tag; the
Packages workflow built `unifi2netbox_1.4.0_amd64.deb` and the Linux tarball
(which contains the new manual page) from the same tag. All three files and
`SHA256SUMS.txt` are attached to the public GitHub release v1.4.0 (approved
by the user on 2026-11-17).

Release v1.4.2 (tag v1.4.2 on merge commit 7350b47, usability fixes) was
built on 2026-11-18 the same way from a clean detached worktree at the tag:
bundle check and native smoke test passed (1 passed, 1 skipped), the exe
reports `1.4.2`, the directory is about 135 MB and the installer
`unifi2netbox-1.4.2-setup.exe` is 44.9 MB (SHA-256
`A85191493BED309858A8FBABBFBDDA6C28C216BD4146591C816D02D4114E6DCF`), also
copied to the local `dist\installer\`. The Offline Tests and Packages
workflows passed for the tag; the Packages workflow built
`unifi2netbox_1.4.2_amd64.deb` and the Linux tarball. All three files and
`SHA256SUMS.txt` are attached to the public GitHub release v1.4.2 (approved
by the user on 2026-11-18). Not verified: installer upgrade/uninstall. The
Windows build is not code-signed.

Release v1.5.0 (tag v1.5.0 on merge commit 12dfd7a, milestone M15 NetBox
backup and restore) was built on 2026-11-20 the same way from a clean
detached worktree at the tag: bundle check and native smoke test passed
(1 passed, 1 skipped), the exe reports `1.5.0`, the bundle contains the new
manual chapter, the directory is about 135 MB and the installer
`unifi2netbox-1.5.0-setup.exe` is 45.1 MB (SHA-256
`9E865F91EFEE7506335771CA5C8969B711B6B406892464CBB09F53F2B78F17AF`), also
copied to the local `dist\installer\`. Not verified: installer
upgrade/uninstall, and backup or restore inside the packaged app. The
Windows build is not code-signed.
The Offline Tests and Packages workflows passed for main and the tag; the
Packages workflow built `unifi2netbox_1.5.0_amd64.deb` and the Linux tarball
(which contains the new manual chapter). All three files and
`SHA256SUMS.txt` are attached to the public GitHub release v1.5.0 (approved
by the user on 2026-11-20).

Release v1.5.1 (tag v1.5.1 on merge commit 573a206, full-text search in the
manual viewer) was built on 2026-11-20 the same way from a clean detached
worktree at the tag: bundle check and native smoke test passed (1 passed,
1 skipped), the exe reports `1.5.1`, the directory is about 135 MB and the
installer `unifi2netbox-1.5.1-setup.exe` is 45.1 MB (SHA-256
`A8D1333AEA95161A0B1B25B5CC9E42BAFA81466DDA22EBB11922CF115A008CB9`), also
copied to the local `dist\installer\`. Not verified: installer
upgrade/uninstall, and the manual search inside the packaged app. The
Windows build is not code-signed.
The Offline Tests and Packages workflows passed for the tag; the Packages
workflow built `unifi2netbox_1.5.1_amd64.deb` and the Linux tarball. All
three files and `SHA256SUMS.txt` are attached to the public GitHub release
v1.5.1 (approved by the user on 2026-11-20).

```powershell
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean --windowed --onedir --name unifi2netbox --icon src/unifi2netbox/resources/unifi2netbox.ico --paths src --recursive-copy-metadata unifi2netbox --add-data "LICENSE:." --add-data "docs/THIRD_PARTY_NOTICES.md:." --add-data "manual:manual" --add-data "src/unifi2netbox/resources:unifi2netbox/resources" src/unifi2netbox/__main__.py
```

Since 0.10.1 the recipe embeds the application icon (`--icon`) and bundles
the icon resources the windows use (`--add-data .../resources`). Since 1.1.1
it also bundles the user manual (`--add-data "manual:manual"`); both build
scripts fail when `manual/index.md` is missing from the bundle.

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