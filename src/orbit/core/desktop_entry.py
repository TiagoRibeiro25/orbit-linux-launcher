"""Read and parse freedesktop.org ``.desktop`` files.

The parser only exposes the metadata Orbit needs and has no Qt dependency, so it
can be reused or tested without starting a graphical application.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

_ESCAPES = {
    "s": " ",
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "\\": "\\",
}
_ESCAPE_RE = re.compile(r"\\([sntr\\])")
_TRUE_VALUES = {"1", "true", "yes", "on"}
_LOCALE_ENV_VARS = ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")
_DESKTOP_GROUP = "Desktop Entry"


def _unescape(value: str) -> str:
    return _ESCAPE_RE.sub(lambda match: _ESCAPES[match.group(1)], value)


def _as_bool(value: str | None) -> bool:
    return (value or "").strip().casefold() in _TRUE_VALUES


def _as_list(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    parts = (item.strip() for item in value.split(";"))
    return tuple(item for item in (_unescape(part) for part in parts) if item)


def _locale_candidates() -> list[str]:
    """Return locale tags in gettext priority order, without encoding hints."""

    candidates: list[str] = []
    for env_name in _LOCALE_ENV_VARS:
        raw = os.environ.get(env_name, "")
        for chunk in raw.split(":"):
            tag = chunk.strip()
            if not tag or tag in {"C", "POSIX"}:
                continue

            tag = tag.split(".", 1)[0].replace("-", "_").casefold()
            if tag not in candidates:
                candidates.append(tag)

            language = tag.split("_", 1)[0]
            if language and language not in candidates:
                candidates.append(language)

    return candidates


def _localized_value(raw: dict[str, str], key: str) -> str | None:
    localized: dict[str, str] = {}
    prefix = f"{key}["

    for raw_key, value in raw.items():
        if raw_key.startswith(prefix) and raw_key.endswith("]"):
            tag = (
                raw_key[len(prefix) : -1].split(".", 1)[0].replace("-", "_").casefold()
            )
            localized.setdefault(tag, value)

    for candidate in _locale_candidates():
        if candidate in localized:
            return _unescape(localized[candidate])

    return None


def _text_value(raw: dict[str, str], key: str) -> str:
    value = _localized_value(raw, key)
    if value is None:
        value = _unescape(raw.get(key, ""))
    return value.strip()


def _list_value(raw: dict[str, str], key: str) -> tuple[str, ...]:
    value = _localized_value(raw, key)
    if value is None:
        value = raw.get(key)
    return _as_list(value)


def _parse_groups(text: str) -> dict[str, dict[str, str]]:
    groups: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    pending = ""

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if pending:
            line = pending + line.lstrip()
            pending = ""

        if not line.strip() or line.lstrip().startswith("#"):
            continue

        if line.endswith("\\"):
            pending = line[:-1]
            continue

        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = groups.setdefault(stripped[1:-1], {})
            continue

        if current is None or "=" not in line:
            continue

        key, value = line.split("=", 1)
        current[key.strip()] = value.strip()

    return groups


@dataclass(frozen=True, slots=True)
class DesktopEntry:
    """A launchable application described by a ``.desktop`` file."""

    desktop_id: str
    path: Path
    name: str
    exec_line: str
    icon: str = ""
    comment: str = ""
    generic_name: str = ""
    categories: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    terminal: bool = False
    no_display: bool = False
    hidden: bool = False
    only_show_in: tuple[str, ...] = ()
    not_show_in: tuple[str, ...] = ()
    working_dir: str = ""
    try_exec: str = ""
    startup_wm_class: str = ""

    @classmethod
    def from_file(
        cls, path: str | Path, desktop_id: str | None = None
    ) -> DesktopEntry | None:
        """Parse a single file. Missing or unreadable files return ``None``."""

        file_path = Path(path)
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        return cls.from_text(
            text,
            path=file_path,
            desktop_id=desktop_id or file_path.name,
        )

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        path: str | Path,
        desktop_id: str,
    ) -> DesktopEntry | None:
        """Parse desktop-entry contents. Useful for tests and other sources."""

        raw = _parse_groups(text).get(_DESKTOP_GROUP)
        if not raw:
            return None

        entry_type = raw.get("Type", "Application").strip()
        if entry_type != "Application":
            return None

        name = _text_value(raw, "Name")
        exec_line = raw.get("Exec", "").strip()
        if not name or not exec_line:
            return None

        file_path = Path(path)

        return cls(
            desktop_id=desktop_id,
            path=file_path,
            name=name,
            exec_line=exec_line,
            icon=_text_value(raw, "Icon"),
            comment=_text_value(raw, "Comment"),
            generic_name=_text_value(raw, "GenericName"),
            categories=_list_value(raw, "Categories"),
            keywords=_list_value(raw, "Keywords"),
            terminal=_as_bool(raw.get("Terminal")),
            no_display=_as_bool(raw.get("NoDisplay")),
            hidden=_as_bool(raw.get("Hidden")),
            only_show_in=_as_list(raw.get("OnlyShowIn")),
            not_show_in=_as_list(raw.get("NotShowIn")),
            working_dir=raw.get("Path", "").strip(),
            try_exec=raw.get("TryExec", "").strip(),
            startup_wm_class=raw.get("StartupWMClass", "").strip(),
        )

    @property
    def category(self) -> str:
        """Return the first useful category, if one is available."""

        for category in self.categories:
            if category and not category.startswith("X-"):
                return category
        return ""
