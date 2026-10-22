"""Visual design tokens and the application-wide stylesheet.

Keeping colors in a dataclass means custom widgets, generated icons and QSS all
read from the same palette. Adding a new theme only requires adding one theme
factory below.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication

_FONT_CANDIDATES = (
    "Inter",
    "SF Pro Display",
    "SF Pro Text",
    "Adwaita Sans",
    "Fira Sans",
    "Cantarell",
    "Noto Sans",
    "DejaVu Sans",
)

_DARK_ACCENT = "#8B7CFF"
_LIGHT_ACCENT = "#6A57E8"


def _rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def _rgba(color: str, opacity: float) -> str:
    red, green, blue = _rgb(color)
    return f"rgba({red}, {green}, {blue}, {max(0, min(100, round(opacity * 100)))}%)"


def _mix(first: str, second: str, amount: float) -> str:
    first_rgb = _rgb(first)
    second_rgb = _rgb(second)
    mixed = (
        round(first_rgb[index] + (second_rgb[index] - first_rgb[index]) * amount)
        for index in range(3)
    )
    return "#" + "".join(f"{channel:02x}" for channel in mixed)


@dataclass(frozen=True, slots=True)
class Theme:
    mode: str
    panel_top: str
    panel_bottom: str
    border: str
    text: str
    muted: str
    faint: str
    accent: str
    accent_soft: str
    accent_softer: str
    accent_border: str
    hover: str
    divider: str
    badge_bg: str
    badge_border: str
    keycap_bg: str
    keycap_border: str
    scrollbar: str
    scrollbar_hover: str
    danger: str
    danger_soft: str

    @property
    def is_dark(self) -> bool:
        return self.mode == "dark"


def _dark_theme(accent: str) -> Theme:
    return Theme(
        mode="dark",
        panel_top="#181923",
        panel_bottom="#111218",
        border="#2A2C3A",
        text="#F5F6FA",
        muted="#A3A6B9",
        faint="#75798C",
        accent=accent,
        accent_soft=_rgba(accent, 0.14),
        accent_softer=_rgba(accent, 0.06),
        accent_border=_rgba(accent, 0.30),
        hover="#20222D",
        divider="#252733",
        badge_bg="rgba(255, 255, 255, 5%)",
        badge_border="rgba(255, 255, 255, 8%)",
        keycap_bg="rgba(255, 255, 255, 6%)",
        keycap_border="rgba(255, 255, 255, 10%)",
        scrollbar="rgba(255, 255, 255, 18%)",
        scrollbar_hover="rgba(255, 255, 255, 34%)",
        danger="#FF7A90",
        danger_soft=_rgba("#FF7A90", 0.12),
    )


def _light_theme(accent: str) -> Theme:
    return Theme(
        mode="light",
        panel_top="#FFFFFF",
        panel_bottom="#F7F7FB",
        border="#E3E4EC",
        text="#1B1C24",
        muted="#656879",
        faint="#9396A6",
        accent=accent,
        accent_soft=_rgba(accent, 0.10),
        accent_softer=_rgba(accent, 0.04),
        accent_border=_rgba(accent, 0.24),
        hover="#F2F2F8",
        divider="#ECECF3",
        badge_bg="rgba(23, 24, 40, 4%)",
        badge_border="rgba(23, 24, 40, 7%)",
        keycap_bg="rgba(23, 24, 40, 4%)",
        keycap_border="rgba(23, 24, 40, 8%)",
        scrollbar="rgba(23, 24, 40, 18%)",
        scrollbar_hover="rgba(23, 24, 40, 32%)",
        danger="#D93A56",
        danger_soft=_rgba("#D93A56", 0.08),
    )


def _system_mode() -> str:
    instance = QGuiApplication.instance()
    if instance is not None:
        try:
            if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Light:
                return "light"
        except (AttributeError, TypeError):
            pass
    return "dark"


def resolve_theme(mode: str, accent: str | None = None) -> Theme:
    """Build a theme from a mode name and an optional accent color."""

    selected_mode = mode.casefold() if isinstance(mode, str) else "system"
    if selected_mode not in {"dark", "light"}:
        selected_mode = _system_mode()

    if accent:
        base_accent = accent
    else:
        base_accent = _DARK_ACCENT if selected_mode == "dark" else _LIGHT_ACCENT

    if selected_mode == "light":
        base_accent = _mix(base_accent, "#000000", 0.12)
        return _light_theme(base_accent)

    return _dark_theme(base_accent)


def shadow_color(theme: Theme) -> QColor:
    return QColor(0, 0, 0, 150) if theme.is_dark else QColor(32, 33, 48, 55)


def choose_font_family(preferred: str | None = None) -> str:
    families = set(QFontDatabase.families())
    if preferred and preferred in families:
        return preferred

    for candidate in _FONT_CANDIDATES:
        if candidate in families:
            return candidate

    return QGuiApplication.font().family()


def build_app_font(preferred: str | None = None) -> QFont:
    font = QFont(choose_font_family(preferred))
    font.setPixelSize(13)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def build_stylesheet(theme: Theme, *, window_radius: int = 20) -> str:
    """Return the global QSS for the given theme."""

    return f"""
    QWidget {{
        color: {theme.text};
    }}

    QFrame#LauncherPanel {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 0, y2: 1,
            stop: 0 {theme.panel_top},
            stop: 1 {theme.panel_bottom}
        );
        border: 1px solid {theme.border};
        border-radius: {window_radius}px;
    }}

    QFrame#Divider {{
        background-color: {theme.divider};
        border: none;
    }}

    QLineEdit#SearchInput {{
        background: transparent;
        border: none;
        padding: 0px;
        margin: 0px;
        color: {theme.text};
        font-size: 21px;
        font-weight: 500;
        selection-background-color: {theme.accent_soft};
        selection-color: {theme.text};
    }}

    QFrame#AppItem {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 12px;
    }}

    QFrame#AppItem:hover {{
        background-color: {theme.hover};
    }}

    QFrame#AppItem[selected="true"] {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 0,
            stop: 0 {theme.accent_soft},
            stop: 1 {theme.accent_softer}
        );
        border: 1px solid {theme.accent_border};
    }}

    QLabel#CategoryBadge {{
        background-color: {theme.badge_bg};
        border: 1px solid {theme.badge_border};
        border-radius: 6px;
        color: {theme.faint};
        font-size: 9px;
        font-weight: 600;
        padding: 2px 7px;
    }}

    QLabel#KeyCap {{
        background-color: {theme.keycap_bg};
        border: 1px solid {theme.keycap_border};
        border-radius: 5px;
        color: {theme.muted};
        font-size: 10px;
        font-weight: 600;
        padding: 0px 5px;
    }}

    QLabel#Hint {{
        color: {theme.faint};
        font-size: 11px;
    }}

    QLabel#Brand {{
        color: {theme.faint};
        font-size: 11px;
        font-weight: 600;
    }}

    QLabel#Eyebrow {{
        color: {theme.faint};
        font-size: 10px;
        font-weight: 700;
    }}

    QLabel#ResultCount {{
        color: {theme.faint};
        font-size: 11px;
        font-weight: 500;
    }}

    QLabel#EmptyTitle {{
        color: {theme.text};
        font-size: 16px;
        font-weight: 600;
    }}

    QLabel#EmptyBody {{
        color: {theme.muted};
        font-size: 12px;
    }}

    QLabel#ErrorLabel {{
        color: {theme.danger};
        font-size: 11px;
        font-weight: 500;
    }}

    QStackedWidget#ResultsStack {{
        background: transparent;
    }}

    QScrollArea#ResultsScroll {{
        background: transparent;
        border: none;
    }}

    QScrollArea#ResultsScroll > QWidget > QWidget {{
        background: transparent;
    }}

    QWidget#ResultsContent {{
        background: transparent;
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 4px 0px;
    }}

    QScrollBar::handle:vertical {{
        background: {theme.scrollbar};
        border-radius: 3px;
        min-height: 32px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: {theme.scrollbar_hover};
    }}

    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {{
        height: 0px;
        background: transparent;
        border: none;
    }}

    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {{
        background: transparent;
    }}

    QToolTip {{
        background-color: {theme.panel_top};
        color: {theme.text};
        border: 1px solid {theme.border};
        border-radius: 6px;
        padding: 5px 8px;
        font-size: 12px;
    }}
    """
