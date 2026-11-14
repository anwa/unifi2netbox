"""Application look: Fusion style, light/dark palettes, style sheet and icons.

The theme follows the operating system color scheme and switches live when the
user changes it. Widgets opt into styled variants through dynamic properties,
for example ``button.setProperty("variant", "primary")``.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QStyle, QWidget


@dataclass(frozen=True)
class Colors:
    window: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_secondary: str
    accent: str
    accent_text: str
    accent_soft: str
    success: str
    success_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_soft: str
    neutral_soft: str


LIGHT = Colors(
    window="#f4f5f7",
    surface="#ffffff",
    surface_alt="#f8f9fb",
    border="#dfe2e7",
    text="#1c1f24",
    text_secondary="#5f6670",
    accent="#2563eb",
    accent_text="#ffffff",
    accent_soft="#e3ecfd",
    success="#1f7a4d",
    success_soft="#e1f3e9",
    warning="#8a5a00",
    warning_soft="#fbefd5",
    danger="#b42318",
    danger_soft="#fde4e1",
    neutral_soft="#eceef1",
)

DARK = Colors(
    window="#17191d",
    surface="#202329",
    surface_alt="#262a31",
    border="#343943",
    text="#e8eaed",
    text_secondary="#a0a7b1",
    accent="#5b8def",
    accent_text="#0d1117",
    accent_soft="#1f2f4d",
    success="#4cc38a",
    success_soft="#183a2a",
    warning="#e8b44c",
    warning_soft="#3d3017",
    danger="#f07067",
    danger_soft="#45201d",
    neutral_soft="#2c3038",
)

# Semantic tones used by chips, badges and banners.
TONES = ("neutral", "accent", "success", "warning", "danger")


_forced_dark: bool | None = None


def is_dark(app: QGuiApplication | None = None) -> bool:
    if _forced_dark is not None:
        return _forced_dark
    app = app or QGuiApplication.instance()
    if app is None:
        return False
    return app.styleHints().colorScheme() == Qt.ColorScheme.Dark


def colors(app: QGuiApplication | None = None) -> Colors:
    return DARK if is_dark(app) else LIGHT


def tone_colors(tone: str, palette: Colors | None = None) -> tuple[str, str]:
    """Return (foreground, background) for a semantic tone."""
    c = palette or colors()
    return {
        "accent": (c.accent, c.accent_soft),
        "success": (c.success, c.success_soft),
        "warning": (c.warning, c.warning_soft),
        "danger": (c.danger, c.danger_soft),
    }.get(tone, (c.text_secondary, c.neutral_soft))


def dark_for(choice: str) -> bool | None:
    """Map a saved theme choice to apply_theme's ``dark`` argument."""
    return {"light": False, "dark": True}.get(choice)


def apply_theme(app: QApplication, dark: bool | None = None) -> None:
    """Apply Fusion, the matching palette and the style sheet; follow changes.

    ``dark`` forces a scheme; ``None`` follows the operating system.
    """
    global _forced_dark
    _forced_dark = dark
    app.setStyle("Fusion")
    _apply(app)
    if not app.property("unifi2netbox_theme_connected"):
        app.styleHints().colorSchemeChanged.connect(lambda _scheme: _apply(app))
        app.setProperty("unifi2netbox_theme_connected", True)


def _apply(app: QApplication) -> None:
    c = colors(app)
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: c.window,
        QPalette.ColorRole.WindowText: c.text,
        QPalette.ColorRole.Base: c.surface,
        QPalette.ColorRole.AlternateBase: c.surface_alt,
        QPalette.ColorRole.Text: c.text,
        QPalette.ColorRole.Button: c.surface,
        QPalette.ColorRole.ButtonText: c.text,
        QPalette.ColorRole.Highlight: c.accent,
        QPalette.ColorRole.HighlightedText: c.accent_text,
        QPalette.ColorRole.ToolTipBase: c.surface,
        QPalette.ColorRole.ToolTipText: c.text,
        QPalette.ColorRole.PlaceholderText: c.text_secondary,
        QPalette.ColorRole.Link: c.accent,
        QPalette.ColorRole.Mid: c.border,
        QPalette.ColorRole.Midlight: c.border,
    }
    for role, value in roles.items():
        palette.setColor(role, QColor(value))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(c.text_secondary))
    app.setPalette(palette)
    app.setStyleSheet(style_sheet(c))


def style_sheet(c: Colors) -> str:
    chips = "\n".join(
        f"""
QToolButton[chip="{tone}"] {{
    color: {tone_colors(tone, c)[0]};
    background: {tone_colors(tone, c)[1]};
    border: none; border-radius: 13px; padding: 4px 14px;
}}
QLabel[badge="{tone}"] {{
    color: {tone_colors(tone, c)[0]};
    background: {tone_colors(tone, c)[1]};
    border-radius: 9px; padding: 2px 8px; font-weight: 600;
}}
QFrame[banner="{tone}"] {{
    background: {tone_colors(tone, c)[1]};
    border: 1px solid {tone_colors(tone, c)[0]};
    border-radius: 8px;
}}
QFrame[banner="{tone}"] QLabel {{ color: {tone_colors(tone, c)[0]}; }}"""
        for tone in TONES
    )
    return f"""
QWidget {{ font-size: 10pt; }}
QMainWindow, QDialog {{ background: {c.window}; }}
QToolTip {{ color: {c.text}; background: {c.surface}; border: 1px solid {c.border}; }}
QFrame#header {{ background: {c.surface}; border-bottom: 1px solid {c.border}; }}
QFrame#applyBar {{ background: {c.surface}; border-top: 1px solid {c.border}; }}
QLabel#appTitle {{ font-size: 13pt; font-weight: 700; }}
QLabel[role="heading"] {{ font-size: 13pt; font-weight: 700; }}
QLabel[role="subheading"] {{ font-size: 11pt; font-weight: 600; }}
QLabel[role="secondary"], QLabel[role="caption"] {{ color: {c.text_secondary}; }}
QLabel[role="caption"] {{ font-size: 9pt; }}
QLabel[role="emptyTitle"] {{ font-size: 15pt; font-weight: 600; }}
QFrame[card="true"] {{
    background: {c.surface}; border: 1px solid {c.border}; border-radius: 10px;
}}
QPushButton[summaryCard="true"] {{
    background: {c.surface}; border: 1px solid {c.border}; border-radius: 10px;
    text-align: left; padding: 0; min-height: 60px;
}}
QPushButton[summaryCard="true"]:hover {{ border-color: {c.accent}; }}
QPushButton[summaryCard="true"]:checked {{
    border: 2px solid {c.accent}; background: {c.accent_soft};
}}
QPushButton {{
    background: {c.surface}; border: 1px solid {c.border}; border-radius: 6px;
    padding: 6px 14px; min-height: 18px;
}}
QPushButton:hover {{ background: {c.surface_alt}; border-color: {c.text_secondary}; }}
QPushButton:pressed {{ background: {c.neutral_soft}; }}
QPushButton:disabled {{ color: {c.text_secondary}; background: {c.surface_alt}; }}
QPushButton[variant="primary"] {{
    background: {c.accent}; color: {c.accent_text}; border: 1px solid {c.accent};
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{
    background: {c.accent}; border-color: {c.text};
}}
QPushButton[variant="primary"]:disabled {{
    background: {c.neutral_soft}; color: {c.text_secondary}; border-color: {c.border};
}}
QPushButton[variant="ghost"], QToolButton[variant="ghost"] {{
    background: transparent; border: 1px solid transparent; border-radius: 6px;
    padding: 6px 10px;
}}
QPushButton[variant="ghost"]:hover, QToolButton[variant="ghost"]:hover {{
    background: {c.neutral_soft};
}}
QPushButton[segment="true"] {{
    background: transparent; border: 1px solid transparent; border-radius: 14px;
    padding: 4px 12px; color: {c.text_secondary};
}}
QPushButton[segment="true"]:hover {{ background: {c.neutral_soft}; }}
QPushButton[segment="true"]:checked {{
    background: {c.accent_soft}; color: {c.accent}; font-weight: 600;
}}
QLineEdit, QComboBox {{
    background: {c.surface}; border: 1px solid {c.border}; border-radius: 6px;
    padding: 5px 8px; min-height: 18px;
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {c.accent}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolButton[variant="ghost"]::menu-button {{
    border: none; background: transparent; width: 14px;
}}
QToolButton#themeButton {{ padding-right: 18px; }}
QLabel#cardCount {{ font-size: 18pt; font-weight: 700; background: transparent; }}
QLabel#cardCaption {{ color: {c.text_secondary}; background: transparent; }}
QTableView {{
    background: {c.surface}; border: 1px solid {c.border}; border-radius: 10px;
    gridline-color: transparent; selection-background-color: {c.accent_soft};
    selection-color: {c.text};
}}
QTableView::item {{ padding: 4px 8px; border-bottom: 1px solid {c.border}; }}
QHeaderView::section {{
    background: {c.surface}; color: {c.text_secondary}; border: none;
    border-bottom: 1px solid {c.border}; padding: 8px; font-weight: 600;
}}
QListWidget#historyRuns {{
    background: {c.surface}; border: 1px solid {c.border}; border-radius: 10px;
    outline: none; padding: 4px;
}}
QListWidget#historyRuns::item {{ padding: 8px 10px; border-radius: 6px; }}
QListWidget#historyRuns::item:selected {{
    background: {c.accent_soft}; color: {c.text};
}}
QListWidget#settingsNav {{
    background: transparent; border: none; outline: none;
}}
QListWidget#settingsNav::item {{ padding: 9px 12px; border-radius: 6px; }}
QListWidget#settingsNav::item:selected {{
    background: {c.accent_soft}; color: {c.accent}; font-weight: 600;
}}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QSplitter::handle {{ background: transparent; }}
QStatusBar {{ color: {c.text_secondary}; }}
{chips}
"""


def icon(name: str, fallback: QStyle.StandardPixmap | None = None) -> QIcon:
    """Native theme icon (Segoe Fluent on Windows 11) with a style fallback."""
    theme_icon = getattr(QIcon.ThemeIcon, name, None)
    result = QIcon.fromTheme(theme_icon) if theme_icon is not None else QIcon()
    if result.isNull() and fallback is not None:
        app = QApplication.instance()
        if isinstance(app, QApplication):
            result = app.style().standardIcon(fallback)
    return result


def set_variant(widget: QWidget, key: str, value: str | bool) -> None:
    """Set a style property and re-polish so the style sheet picks it up."""
    widget.setProperty(key, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
