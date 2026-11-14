"""Render the application icon from its SVG into PNG sizes and a Windows .ico.

Run from the repository root after changing ``src/unifi2netbox/resources/icon.svg``:

    python tools/build_icons.py

Writes ``icon-<size>.png`` for every size in ``window_frame.ICON_SIZES`` and a
multi-size ``unifi2netbox.ico`` (PNG-compressed entries) next to the SVG.
Sizes up to ``SMALL_MAX`` use the simplified ``icon-small.svg``, which stays
legible at 16-24 px.
Uses Qt only, so no extra dependency is needed.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "src" / "unifi2netbox" / "resources"
sys.path.insert(0, str(ROOT / "src"))

from unifi2netbox.window_frame import ICON_SIZES  # noqa: E402

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
SMALL_MAX = 24


def render(renderer: QSvgRenderer, size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def ico_bytes(images: dict[int, bytes]) -> bytes:
    """ICONDIR + ICONDIRENTRY list + PNG payloads (supported since Vista)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    entries = b""
    payload = b""
    offset = 6 + 16 * len(images)
    for size, data in sorted(images.items()):
        dimension = 0 if size >= 256 else size
        entries += struct.pack(
            "<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset
        )
        payload += data
        offset += len(data)
    return header + entries + payload


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(RESOURCES / "icon.svg"))
    small = QSvgRenderer(str(RESOURCES / "icon-small.svg"))
    if not renderer.isValid() or not small.isValid():
        print("icon.svg or icon-small.svg is not a valid SVG", file=sys.stderr)
        return 1
    pngs = {}
    for size in sorted(set(ICON_SIZES) | set(ICO_SIZES)):
        source = small if size <= SMALL_MAX else renderer
        data = png_bytes(render(source, size))
        pngs[size] = data
        if size in ICON_SIZES:
            (RESOURCES / f"icon-{size}.png").write_bytes(data)
    (RESOURCES / "unifi2netbox.ico").write_bytes(
        ico_bytes({size: pngs[size] for size in ICO_SIZES})
    )
    print(f"Wrote {len(ICON_SIZES)} PNGs and unifi2netbox.ico to {RESOURCES}")
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
