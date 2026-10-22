"""Persistent cache for parsed desktop entries.

Parsing every ``.desktop`` file on each launch is one of the slower startup
steps. The cache records each file's size and nanosecond mtime, so unchanged
files can be reused while additions, edits and removals are still picked up on
the next discovery pass.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from orbit.core.desktop_entry import DesktopEntry, locale_signature

logger = logging.getLogger(__name__)

# Bump this whenever the parser output or payload shape changes.
_CACHE_VERSION = 1
_CACHE_FILENAME = "desktop-entries.json"
_TUPLE_FIELDS = ("categories", "keywords", "only_show_in", "not_show_in")


def _cache_path() -> Path:
    raw = os.environ.get("XDG_CACHE_HOME", "").strip()
    root = Path(raw).expanduser() if raw else Path.home() / ".cache"
    return root / "orbit" / _CACHE_FILENAME


def load() -> dict[str, dict[str, Any]]:
    """Return cached file records, or an empty mapping when unusable."""

    try:
        payload = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}
    if payload.get("version") != _CACHE_VERSION:
        return {}
    if payload.get("locale") != list(locale_signature()):
        return {}

    files = payload.get("files")
    return files if isinstance(files, dict) else {}


def save(files: dict[str, dict[str, Any]]) -> None:
    """Atomically replace the cache with *files*, ignoring write failures."""

    path = _cache_path()
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    payload = {
        "version": _CACHE_VERSION,
        "locale": list(locale_signature()),
        "files": files,
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError as exc:
        logger.debug("Could not write desktop cache %s: %s", path, exc)
        try:
            temporary.unlink()
        except OSError:
            pass


def entry_payload(entry: DesktopEntry) -> dict[str, Any]:
    """Serialize the parsed fields needed to reconstruct *entry*."""

    return {
        "desktop_id": entry.desktop_id,
        "path": str(entry.path),
        "name": entry.name,
        "exec_line": entry.exec_line,
        "icon": entry.icon,
        "comment": entry.comment,
        "generic_name": entry.generic_name,
        "categories": list(entry.categories),
        "keywords": list(entry.keywords),
        "terminal": entry.terminal,
        "no_display": entry.no_display,
        "hidden": entry.hidden,
        "only_show_in": list(entry.only_show_in),
        "not_show_in": list(entry.not_show_in),
        "working_dir": entry.working_dir,
        "try_exec": entry.try_exec,
        "startup_wm_class": entry.startup_wm_class,
    }


def entry_from_payload(value: object) -> DesktopEntry | None:
    """Reconstruct a cached entry, returning ``None`` for invalid records."""

    if not isinstance(value, dict):
        return None

    try:
        raw_path = value.get("path")
        if not isinstance(raw_path, str):
            return None

        fields: dict[str, Any] = {
            "desktop_id": str(value["desktop_id"]),
            "path": Path(raw_path),
            "name": str(value["name"]),
            "exec_line": str(value["exec_line"]),
            "icon": str(value.get("icon", "")),
            "comment": str(value.get("comment", "")),
            "generic_name": str(value.get("generic_name", "")),
            "terminal": bool(value.get("terminal", False)),
            "no_display": bool(value.get("no_display", False)),
            "hidden": bool(value.get("hidden", False)),
            "working_dir": str(value.get("working_dir", "")),
            "try_exec": str(value.get("try_exec", "")),
            "startup_wm_class": str(value.get("startup_wm_class", "")),
        }

        for field in _TUPLE_FIELDS:
            raw = value.get(field, ())
            if not isinstance(raw, list):
                return None
            fields[field] = tuple(str(item) for item in raw)

        return DesktopEntry(**fields)
    except (KeyError, TypeError, ValueError):
        return None
