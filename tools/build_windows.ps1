<#
.SYNOPSIS
  Build the Windows one-folder executable and the per-user installer.

.DESCRIPTION
  Run from the repository root in the project .venv (Windows, Python 3.15):

    .\tools\build_windows.ps1            # exe + installer
    .\tools\build_windows.ps1 -SkipInstaller

  Steps: refuse a dirty working tree (unless -AllowDirty), read the version
  from pyproject.toml, run the pinned PyInstaller recipe, check that no
  configuration, cache or journal file landed in the bundle, run the native
  smoke test, then compile packaging\windows\unifi2netbox.iss with Inno Setup.
  Output: dist\unifi2netbox\ and dist\installer\unifi2netbox-<version>-setup.exe.
#>
param(
    [switch]$SkipInstaller,
    [switch]$AllowDirty,
    [string]$Iscc = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

if (-not $AllowDirty -and (git status --porcelain)) {
    throw "Working tree is not clean; commit first or pass -AllowDirty."
}

$version = (Select-String -Path pyproject.toml -Pattern '^version = "([^"]+)"').Matches[0].Groups[1].Value
Write-Host "Building unifi2netbox $version"

python -m PyInstaller --noconfirm --clean --windowed --onedir --name unifi2netbox `
    --icon src/unifi2netbox/resources/unifi2netbox.ico `
    --paths src --recursive-copy-metadata unifi2netbox `
    --add-data "LICENSE:." --add-data "docs/THIRD_PARTY_NOTICES.md:." `
    --add-data "src/unifi2netbox/resources:unifi2netbox/resources" `
    src/unifi2netbox/__main__.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

# Bundle hygiene: never ship settings, caches, journals or captures.
$forbidden = Get-ChildItem -Recurse dist\unifi2netbox -File |
    Where-Object { $_.Name -match '^(config\.toml|snapshots\.sqlite3|write-journal\.sqlite3)$' -or $_.Extension -in '.har', '.pcap' }
if ($forbidden) { throw "Forbidden files in bundle: $($forbidden.FullName -join ', ')" }
foreach ($notice in 'LICENSE', 'THIRD_PARTY_NOTICES.md') {
    if (-not (Test-Path "dist\unifi2netbox\_internal\$notice")) { throw "Missing $notice in bundle." }
}

$env:UNIFI2NETBOX_EXE = (Resolve-Path dist\unifi2netbox\unifi2netbox.exe).Path
try {
    python -m pytest tests/test_package.py -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw "Native smoke test failed." }
} finally {
    Remove-Item Env:UNIFI2NETBOX_EXE
}

if ($SkipInstaller) { return }

if (-not $Iscc) {
    $onPath = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    $candidates = @(
        $(if ($onPath) { $onPath.Source } else { "" }),
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }
    if (-not $candidates) { throw "Inno Setup 6 (ISCC.exe) not found; install it or pass -Iscc." }
    $Iscc = @($candidates)[0]
}
& $Iscc "/DAppVersion=$version" packaging\windows\unifi2netbox.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }
Write-Host "Installer: dist\installer\unifi2netbox-$version-setup.exe"
