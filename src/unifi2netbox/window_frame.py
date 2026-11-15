"""Native title bars that follow the app theme, and the application icon.

On Windows 10/11 the title bar of every top-level window (main window,
settings, dialogs, message boxes) is switched to dark mode when the app is
dark (``DWMWA_USE_IMMERSIVE_DARK_MODE``). Windows 11 additionally gets the
app's own caption, text and border colors (``DWMWA_CAPTION_COLOR`` and
friends), so the title bar blends into the header. The native frame stays,
so snapping, resizing and accessibility keep working. Other platforms and
older Windows builds ignore the calls.
"""

from __future__ import annotations

import sys
from importlib.resources import files

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from unifi2netbox import theme

APP_USER_MODEL_ID = "unifi2netbox.desktop"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

# DwmSetWindowAttribute attribute IDs (dwmapi.h).
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36


def app_icon() -> QIcon:
    """The application icon in all bundled sizes (empty if not packaged)."""
    icon = QIcon()
    folder = files("unifi2netbox") / "resources"
    for size in ICON_SIZES:
        path = folder / f"icon-{size}.png"
        if path.is_file():
            icon.addFile(str(path))
    return icon


def colorref(value: str) -> int:
    """Windows COLORREF (0x00BBGGRR) of a ``#rrggbb`` color."""
    color = QColor(value)
    return color.red() | (color.green() << 8) | (color.blue() << 16)


def caption_colors(widget: QWidget, palette: theme.Colors) -> tuple[str, str, str]:
    """(caption, text, border): the main window blends into its header."""
    caption = palette.surface if isinstance(widget, QMainWindow) else palette.window
    return caption, palette.text, palette.border


def native_handle(widget: QWidget) -> int:
    """The current native window handle of a top-level widget.

    A dialog that is closed and shown again gets a new native window, while
    ``QWidget.winId()`` can still return the destroyed one; the window
    handle (``QWindow``) always knows the current handle.
    """
    window = widget.windowHandle()
    return int(window.winId()) if window is not None else int(widget.winId())


def style_title_bar(widget: QWidget) -> bool:
    """Apply the theme to the native title bar; False where unsupported."""
    if (
        sys.platform != "win32"
        or QGuiApplication.platformName() != "windows"
        or not widget.isWindow()
    ):
        # Offscreen and other Qt platforms have no native HWND to style.
        return False
    try:
        import ctypes
        from ctypes import wintypes

        dwm = ctypes.windll.dwmapi
    except ImportError, AttributeError, OSError:
        return False
    hwnd = wintypes.HWND(native_handle(widget))
    palette = theme.colors()
    caption, text, border = caption_colors(widget, palette)

    def set_attribute(attribute: int, value: int) -> bool:
        data = ctypes.c_int(value)
        result = dwm.DwmSetWindowAttribute(
            hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data)
        )
        return result == 0

    applied = set_attribute(DWMWA_USE_IMMERSIVE_DARK_MODE, int(theme.is_dark()))
    # Windows 11 only; earlier builds reject these attributes harmlessly.
    for attribute, value in (
        (DWMWA_CAPTION_COLOR, caption),
        (DWMWA_TEXT_COLOR, text),
        (DWMWA_BORDER_COLOR, border),
    ):
        applied = set_attribute(attribute, colorref(value)) or applied
    return applied


class TitleBarStyler(QObject):
    """Styles each top-level window when it is shown and on theme changes."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if (
            event.type() in (QEvent.Type.Show, QEvent.Type.WinIdChange)
            and isinstance(watched, QWidget)
            and watched.isWindow()
        ):
            style_title_bar(watched)
        return False

    def restyle_all(self) -> None:
        for widget in QApplication.topLevelWidgets():
            if widget.isVisible():
                style_title_bar(widget)
                widget.update()


def install(app: QApplication) -> TitleBarStyler:
    """Set the app icon and keep native title bars in line with the theme."""
    if sys.platform == "win32":
        # Own taskbar identity, so Windows shows this icon instead of Python's.
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                APP_USER_MODEL_ID
            )
        except AttributeError, OSError:
            pass
    icon = app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    styler = TitleBarStyler(app)
    app.installEventFilter(styler)
    theme.add_listener(styler.restyle_all)
    return styler
