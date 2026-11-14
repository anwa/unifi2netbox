"""Application icon and themed native title bars."""

import struct
from importlib.resources import files

from PySide6.QtWidgets import QDialog, QMainWindow

from unifi2netbox import theme, window_frame


def test_app_icon_bundles_every_size(qapp):
    icon = window_frame.app_icon()

    assert not icon.isNull()
    sizes = {size.width() for size in icon.availableSizes()}
    assert set(window_frame.ICON_SIZES) <= sizes


def test_windows_icon_file_holds_png_entries_for_all_sizes():
    data = (files("unifi2netbox") / "resources" / "unifi2netbox.ico").read_bytes()

    reserved, kind, count = struct.unpack_from("<HHH", data)
    assert (reserved, kind, count) == (0, 1, 9)
    sizes = []
    for index in range(count):
        width, _, _, _, _, bits, length, offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + 16 * index
        )
        sizes.append(width or 256)
        assert bits == 32
        assert data[offset : offset + 8] == b"\x89PNG\r\n\x1a\n"
        assert offset + length <= len(data)
    assert sizes == [16, 20, 24, 32, 40, 48, 64, 128, 256]


def test_colorref_is_bgr():
    assert window_frame.colorref("#112233") == 0x332211


def test_main_window_caption_blends_into_the_header(qtbot):
    main, dialog = QMainWindow(), QDialog()
    qtbot.addWidget(main)
    qtbot.addWidget(dialog)

    assert window_frame.caption_colors(main, theme.DARK) == (
        theme.DARK.surface,
        theme.DARK.text,
        theme.DARK.border,
    )
    assert window_frame.caption_colors(dialog, theme.LIGHT)[0] == theme.LIGHT.window


def test_title_bar_styling_never_fails(qtbot, monkeypatch):
    from PySide6.QtWidgets import QLabel

    dialog = QDialog()
    qtbot.addWidget(dialog)

    # Offscreen tests have no native window handle to style.
    assert window_frame.style_title_bar(dialog) is False
    # Child widgets are never styled.
    assert window_frame.style_title_bar(QLabel(dialog)) is False
    monkeypatch.setattr(window_frame.sys, "platform", "linux")
    assert window_frame.style_title_bar(dialog) is False


def test_install_sets_the_icon_and_restyles_on_theme_changes(qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(window_frame.theme, "_listeners", [])
    monkeypatch.setattr(
        window_frame.TitleBarStyler, "restyle_all", lambda self: calls.append(1)
    )

    styler = window_frame.install(qapp)
    theme.apply_theme(qapp, True)
    theme.apply_theme(qapp, False)

    assert not qapp.windowIcon().isNull()
    assert len(calls) == 2
    qapp.removeEventFilter(styler)
    theme.apply_theme(qapp, None)
