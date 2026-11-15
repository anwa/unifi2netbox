# Installation

Download the current release from the
[GitHub releases](https://github.com/anwa/unifi2netbox/releases).
`SHA256SUMS.txt` lists the checksums of all files.

## Windows 11

1. Download `unifi2netbox-<version>-setup.exe`.
2. Run it. No administrator rights are needed; the app is installed for your
   user under `%LOCALAPPDATA%\Programs\unifi2netbox` with a Start menu entry
   (a desktop icon is optional).
3. The build is not code-signed, so Windows SmartScreen may warn on the first
   start. Choose **More info > Run anyway** if you trust the download.

**Upgrading:** run the newer installer; it replaces the program files and
keeps your settings. **Uninstalling** (Windows Settings > Apps) keeps your
settings, snapshots and write history in `%LOCALAPPDATA%\unifi2netbox`;
delete that folder yourself to remove everything, including the stored
tokens. See [Files and data](../05-reference/03-files-and-data.md).

## Ubuntu (.deb)

```bash
sudo apt install ./unifi2netbox_<version>_amd64.deb
```

The app is installed to `/opt/unifi2netbox` with a launcher and a menu entry.
Start it from the application menu or with `unifi2netbox`.

## Linux standalone (tarball)

Unpack `unifi2netbox-<version>-linux-x86_64.tar.gz` anywhere and start
`unifi2netbox/unifi2netbox` from the unpacked folder.

> Linux packages are built and tested automatically without a desktop. A real
> Linux desktop has not been verified yet.

## From source

Requires Python 3.15.1 or newer.

```bash
python3.15 -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unifi2netbox
```

`python -m unifi2netbox --version` prints the version, and
`--config PATH` uses another configuration file.

Next: [First start](02-first-start.md).
