"""Application defaults and user-configurable settings.

Settings are intentionally independent from Qt. A JSON file at
``~/.config/orbit/settings.json`` (or ``$XDG_CONFIG_HOME/orbit/settings.json``)
can override any of the defaults below. Unknown keys are ignored, which keeps
old settings files usable as Orbit evolves.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

APP_NAME = "Orbit"
APP_SLUG = "orbit"

_VALID_THEMES = {"dark", "light", "system"}
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")

# The panel is centered over the shadow margins, so these are the dimensions of
# the visible card rather than of the transparent top-level window.
_DEFAULT_WINDOW_WIDTH = 720
_DEFAULT_WINDOW_HEIGHT = 596
_DEFAULT_SHADOW_MARGIN = 36


def _config_home() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".config"


CONFIG_DIR = _config_home() / APP_SLUG
SETTINGS_PATH = CONFIG_DIR / "settings.json"


@dataclass(frozen=True, slots=True)
class Settings:
    """Default appearance and behaviour for Orbit."""

    # Appearance
    theme: str = "system"  # "system", "dark" or "light"
    accent_color: str | None = None  # e.g. "#8B7CFF"; None uses the theme default
    font_family: str | None = None  # None picks the best available system font
    window_width: int = _DEFAULT_WINDOW_WIDTH
    window_height: int = _DEFAULT_WINDOW_HEIGHT
    window_radius: int = 20
    shadow_margin: int = _DEFAULT_SHADOW_MARGIN
    window_top_ratio: float = 0.16  # vertical anchor on the active screen
    icon_size: int = 38

    # Behaviour
    max_results: int = 60
    close_on_focus_loss: bool = True
    show_categories: bool = True
    search_placeholder: str = "Search applications…"

    @classmethod
    def load(cls, path: Path | str | None = None) -> Settings:
        """Load settings from *path*, falling back to defaults on any error."""

        settings_path = Path(path) if path is not None else SETTINGS_PATH
        try:
            payload = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return cls()

        if not isinstance(payload, Mapping):
            return cls()

        return cls._from_mapping(payload)

    @classmethod
    def _from_mapping(cls, payload: Mapping[str, Any]) -> Settings:
        values: dict[str, Any] = {}

        for field in fields(cls):
            if field.name not in payload:
                continue

            value = payload[field.name]
            validator = _VALIDATORS.get(field.name)
            if validator is None:
                continue

            try:
                converted = validator(value)
            except (TypeError, ValueError):
                continue

            if converted is not None:
                values[field.name] = converted

        return replace(cls(), **values)


def _positive_int(value: Any) -> int:
    if isinstance(value, bool):
        raise TypeError
    number = int(value)
    if number <= 0:
        raise ValueError
    return number


def _clamped_int(minimum: int, maximum: int):
    def validate(value: Any) -> int:
        return max(minimum, min(maximum, _positive_int(value)))

    return validate


def _boolean(value: Any) -> bool:
    if not isinstance(value, bool):
        raise TypeError
    return value


def _ratio(value: Any) -> float:
    if isinstance(value, bool):
        raise TypeError
    number = float(value)
    return max(0.0, min(1.0, number))


def _theme(value: Any) -> str:
    if not isinstance(value, str) or value.lower() not in _VALID_THEMES:
        raise ValueError
    return value.lower()


def _color(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _HEX_COLOR.match(value):
        raise ValueError
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError
    return value.strip() or None


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError
    return value.strip()


_VALIDATORS = {
    "theme": _theme,
    "accent_color": _color,
    "font_family": _optional_text,
    "window_width": _clamped_int(480, 1600),
    "window_height": _clamped_int(360, 1200),
    "window_radius": _clamped_int(0, 40),
    "shadow_margin": _clamped_int(0, 80),
    "window_top_ratio": _ratio,
    "icon_size": _clamped_int(20, 96),
    "max_results": _clamped_int(1, 200),
    "close_on_focus_loss": _boolean,
    "show_categories": _boolean,
    "search_placeholder": _text,
}
