# Deployment

## Initial Windows Standalone Gate

Use the same Python >=3.15.1 `.venv` as the source installation. Build on Windows;
cross-compiling a Windows executable from Linux is not supported by this recipe.
This early smoke build is not the final installer or a signed production release.

Verified locally with CPython 3.15.1, PySide6 6.12.0 and PyInstaller 6.22.3 on
Windows 11: native windowed EXE starts with version 0.0.2, opens first-run settings
and exits cleanly after settings/main windows close. No live API was exercised.

```powershell
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean --windowed --onedir --name unifi2netbox --paths src --recursive-copy-metadata unifi2netbox --add-data "LICENSE:." --add-data "docs/THIRD_PARTY_NOTICES.md:." src/unifi2netbox/__main__.py
```

The executable is `dist/unifi2netbox/unifi2netbox.exe`. Distribute the entire
`dist/unifi2netbox` directory, not just the executable. The standalone directory
uses shared Qt libraries, supporting replacement and dependency-license review.
Build files, spec files and distribution output are ignored by Git.

Runtime configuration remains per-user and outside this directory. Never add
your configuration, cache, captures or tokens to a build. Dependency metadata,
including available license files, is copied recursively; review the resulting
notices/license material before redistribution. See [third-party notices](THIRD_PARTY_NOTICES.md).

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

## Linux and Final Deployment

Source-based Ubuntu/Kubuntu execution is a target, not yet locally verified.
M10 finalizes native Linux packages, proposed `.deb` and standalone build output,
alongside Windows packaging, signing decisions, upgrade and uninstall behavior.
Never describe a Windows smoke build as verified Linux deployment.