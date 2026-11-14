#!/usr/bin/env bash
# Build the Linux standalone folder, a tarball and an Ubuntu .deb package.
#
# Run from the repository root in the activated .venv (Ubuntu, Python 3.15)
# with requirements-build.txt and requirements-dev.txt installed:
#
#   tools/build_linux.sh
#
# Output in dist/:
#   unifi2netbox/                         PyInstaller one-folder build
#   unifi2netbox-<version>-linux-x86_64.tar.gz
#   unifi2netbox_<version>_amd64.deb      installs to /opt/unifi2netbox
#
# The .deb adds /usr/bin/unifi2netbox, a desktop entry and hicolor icons.
# Settings stay per user in ~/.config/unifi2netbox and are never packaged or
# removed by the package.
set -euo pipefail

cd "$(dirname "$0")/.."
version=$(python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')
echo "Building unifi2netbox ${version} for Linux"

python -m PyInstaller --noconfirm --clean --windowed --onedir --name unifi2netbox \
    --paths src --recursive-copy-metadata unifi2netbox \
    --add-data "LICENSE:." --add-data "docs/THIRD_PARTY_NOTICES.md:." \
    --add-data "src/unifi2netbox/resources:unifi2netbox/resources" \
    src/unifi2netbox/__main__.py

# Bundle hygiene: never ship settings, caches, journals or captures.
forbidden=$(find dist/unifi2netbox -type f \( -name config.toml -o -name snapshots.sqlite3 \
    -o -name write-journal.sqlite3 -o -name '*.har' -o -name '*.pcap' \))
if [[ -n "${forbidden}" ]]; then
    echo "Forbidden files in bundle: ${forbidden}" >&2
    exit 1
fi
for notice in LICENSE THIRD_PARTY_NOTICES.md; do
    test -f "dist/unifi2netbox/_internal/${notice}" || { echo "Missing ${notice}" >&2; exit 1; }
done

UNIFI2NETBOX_EXE="$PWD/dist/unifi2netbox/unifi2netbox" \
    python -m pytest tests/test_package.py -q -p no:cacheprovider

tar -C dist -czf "dist/unifi2netbox-${version}-linux-x86_64.tar.gz" unifi2netbox

root=$(mktemp -d)
trap 'rm -rf "${root}"' EXIT
mkdir -p "${root}/DEBIAN" "${root}/opt" "${root}/usr/bin" "${root}/usr/share/applications" \
    "${root}/usr/share/doc/unifi2netbox"
cp -a dist/unifi2netbox "${root}/opt/unifi2netbox"
ln -s /opt/unifi2netbox/unifi2netbox "${root}/usr/bin/unifi2netbox"
install -m 0644 packaging/linux/unifi2netbox.desktop "${root}/usr/share/applications/"
for size in 16 24 32 48 64 128 256; do
    dir="${root}/usr/share/icons/hicolor/${size}x${size}/apps"
    mkdir -p "${dir}"
    install -m 0644 "src/unifi2netbox/resources/icon-${size}.png" "${dir}/unifi2netbox.png"
done
mkdir -p "${root}/usr/share/icons/hicolor/scalable/apps"
install -m 0644 src/unifi2netbox/resources/icon.svg \
    "${root}/usr/share/icons/hicolor/scalable/apps/unifi2netbox.svg"
install -m 0644 LICENSE "${root}/usr/share/doc/unifi2netbox/copyright"
install -m 0644 docs/THIRD_PARTY_NOTICES.md "${root}/usr/share/doc/unifi2netbox/"

size_kb=$(du -sk "${root}" | cut -f1)
cat > "${root}/DEBIAN/control" <<EOF
Package: unifi2netbox
Version: ${version}
Section: net
Priority: optional
Architecture: amd64
Installed-Size: ${size_kb}
Depends: libc6, libgl1, libegl1, libfontconfig1, libfreetype6, libdbus-1-3, libxkbcommon0, libxkbcommon-x11-0, libxcb-cursor0
Maintainer: unifi2netbox maintainers <noreply@users.noreply.github.com>
Description: UniFi inventory review for NetBox
 Desktop application that compares UniFi inventory with NetBox, explains
 matches and conflicts, and applies selected, confirmed changes to NetBox.
 UniFi is only read. Settings stay per user in ~/.config/unifi2netbox.
EOF
cat > "${root}/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
exit 0
EOF
cp "${root}/DEBIAN/postinst" "${root}/DEBIAN/postrm"
chmod 0755 "${root}/DEBIAN/postinst" "${root}/DEBIAN/postrm"

dpkg-deb --root-owner-group --build "${root}" "dist/unifi2netbox_${version}_amd64.deb"
echo "Built dist/unifi2netbox_${version}_amd64.deb and the standalone tarball"
