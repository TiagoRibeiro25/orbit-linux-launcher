"""Locate and filter installed applications.

Discovery follows the XDG Desktop Entry specification:

* application directories are searched in ``XDG_DATA_DIRS`` order;
* the first entry for a desktop ID wins (user files override system files);
* hidden, NoDisplay, desktop-restricted and broken entries are skipped.
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Iterable, Sequence
from pathlib import Path

from orbit.core.desktop_entry import DesktopEntry

logger = logging.getLogger(__name__)

_DEFAULT_DATA_DIRS = ("/usr/local/share", "/usr/share")
_FLATPAK_DATA_DIRS = (
    "~/.local/share/flatpak/exports/share",
    "/var/lib/flatpak/exports/share",
)
_SNAP_APPLICATIONS = Path("/var/lib/snapd/desktop/applications")


def _data_home() -> Path:
    raw = os.environ.get("XDG_DATA_HOME", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".local" / "share"


def xdg_data_dirs() -> list[Path]:
    """Return data directories, including common Flatpak export locations."""

    raw = os.environ.get("XDG_DATA_DIRS", "").strip()
    values = raw.split(":") if raw else list(_DEFAULT_DATA_DIRS)

    candidates: Iterable[str | Path] = [
        _data_home(),
        *(Path(value).expanduser() for value in values if value.strip()),
        *(Path(value).expanduser() for value in _FLATPAK_DATA_DIRS),
    ]

    result: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        path = Path(candidate)
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def application_dirs(data_dirs: Sequence[Path] | None = None) -> list[Path]:
    """Return existing ``applications`` directories in lookup order."""

    base_dirs = list(data_dirs) if data_dirs is not None else xdg_data_dirs()
    directories = [base / "applications" for base in base_dirs]

    if _SNAP_APPLICATIONS.is_dir():
        directories.append(_SNAP_APPLICATIONS)

    return [directory for directory in directories if directory.is_dir()]


def current_desktops() -> set[str]:
    """Return the names of the currently running desktop environments."""

    values: list[str] = []
    for env_name in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION"):
        raw = os.environ.get(env_name, "")
        values.extend(
            part.strip().casefold() for part in raw.split(":") if part.strip()
        )
    return set(values)


class AppDiscovery:
    """Scan XDG application directories for launchable entries."""

    def __init__(
        self,
        *,
        data_dirs: Sequence[Path] | None = None,
        desktops: Iterable[str] | None = None,
    ) -> None:
        self._data_dirs = list(data_dirs) if data_dirs is not None else None
        self._desktops = (
            {desktop.casefold() for desktop in desktops}
            if desktops is not None
            else current_desktops()
        )

    def discover(self) -> list[DesktopEntry]:
        """Return all visible applications, sorted by display name."""

        found: dict[str, DesktopEntry] = {}
        seen_ids: set[str] = set()

        for directory in application_dirs(self._data_dirs):
            for path in sorted(directory.rglob("*.desktop")):
                if path.name.startswith("."):
                    continue

                desktop_id = self._desktop_id(directory, path)

                # A file in a higher-priority directory overrides lower ones,
                # even when the override is hidden or marked NoDisplay.
                if desktop_id in seen_ids:
                    continue
                seen_ids.add(desktop_id)

                entry = DesktopEntry.from_file(path, desktop_id)
                if entry is None:
                    logger.debug("Ignoring malformed desktop file: %s", path)
                    continue

                if self._is_available(entry):
                    found[desktop_id] = entry

        logger.info("Discovered %d applications", len(found))
        entries = sorted(found.values(), key=lambda entry: entry.name.casefold())

        # Some packages ship the same application under two desktop IDs. Keep
        # the first (highest-priority) entry rather than showing duplicate rows.
        unique: list[DesktopEntry] = []
        fingerprints: set[tuple[str, str]] = set()
        for entry in entries:
            fingerprint = (entry.name.casefold(), entry.exec_line)
            if fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            unique.append(entry)

        return unique

    @staticmethod
    def _desktop_id(directory: Path, path: Path) -> str:
        relative = path.relative_to(directory).as_posix()
        return relative.replace("/", "-")

    def _is_available(self, entry: DesktopEntry) -> bool:
        if entry.hidden or entry.no_display:
            return False

        if not entry.exec_line:
            return False

        if entry.only_show_in and self._desktops:
            allowed = {value.casefold() for value in entry.only_show_in}
            if not allowed & self._desktops:
                return False

        if entry.not_show_in and self._desktops:
            blocked = {value.casefold() for value in entry.not_show_in}
            if blocked & self._desktops:
                return False

        return self._try_exec_available(entry.try_exec)

    @staticmethod
    def _try_exec_available(try_exec: str) -> bool:
        candidate = os.path.expanduser(try_exec.strip().strip("\"'"))
        if not candidate:
            return True

        if os.path.isabs(candidate) or os.sep in candidate:
            path = Path(candidate)
            return path.is_file() and os.access(path, os.X_OK)

        return shutil.which(candidate) is not None
