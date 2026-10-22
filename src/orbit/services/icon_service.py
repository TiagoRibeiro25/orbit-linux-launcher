"""Resolve icon names and paths into Qt icons.

Resolution order is: absolute path, the active Qt icon theme, application icon
directories discovered from the XDG icon search path, and finally a generated
letter tile. Generated tiles keep the launcher looking complete even when an
application ships no icon at all.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QLinearGradient,
    QPainter,
    QPixmap,
)
from PyQt6.QtWidgets import QApplication

_ICON_EXTENSIONS = (".svg", ".svgz", ".png", ".xpm")
_SIZE_PATTERN = re.compile(r"(?<!\d)(\d{2,4})x(\d{2,4})(?!\d)")
_SYMBOLIC_PARTS = {"symbolic"}


def _icon_path_score(path: Path, active_theme: str) -> int:
    parts = {part.casefold() for part in path.parts}
    suffix = path.suffix.casefold()

    score = 0
    if active_theme and active_theme.casefold() in parts:
        score += 1_000_000

    if "hicolor" in parts:
        score += 4_000

    if suffix in {".svg", ".svgz"}:
        score += 10_000
    elif suffix == ".png":
        score += 1_000
    elif suffix == ".xpm":
        score += 100

    if parts & _SYMBOLIC_PARTS:
        score -= 20_000

    sizes = [
        int(match.group(1))
        for part in path.parts
        for match in _SIZE_PATTERN.finditer(part)
    ]
    if sizes:
        score += min(max(sizes), 512)

    return score


class IconService:
    """A small cached facade around Qt's icon lookup."""

    def __init__(self, default_size: int = 38) -> None:
        self._default_size = default_size
        self._icons: dict[tuple[str, str, int], QIcon] = {}
        self._fallback_pixmaps: dict[tuple[str, int, int], QPixmap] = {}
        self._path_cache: dict[str, Path | None] = {}
        self._directories: tuple[Path, ...] | None = None

    def get_icon(
        self,
        icon_name: str,
        fallback_text: str = "",
        size: int | None = None,
    ) -> QIcon:
        """Return an icon for *icon_name*, generating a tile if needed."""

        target_size = size or self._default_size
        cache_key = (icon_name, fallback_text, target_size)
        cached = self._icons.get(cache_key)
        if cached is not None:
            return cached

        icon = self._resolve(icon_name, fallback_text, target_size)
        self._icons[cache_key] = icon
        return icon

    def _resolve(self, icon_name: str, fallback_text: str, size: int) -> QIcon:
        name = (icon_name or "").strip()
        if not name:
            return self._fallback_icon(fallback_text, size)

        expanded = Path(os.path.expanduser(name))
        if expanded.is_absolute():
            if expanded.is_file():
                return QIcon(str(expanded))
            return self._fallback_icon(fallback_text, size)

        themed = QIcon.fromTheme(name)
        if not themed.isNull():
            return themed

        resolved = self._lookup_icon_path(name)
        if resolved is not None:
            return QIcon(str(resolved))

        return self._fallback_icon(fallback_text, size)

    def _lookup_icon_path(self, name: str) -> Path | None:
        if name in self._path_cache:
            return self._path_cache[name]

        candidate_name = Path(name).name
        explicit_suffix = Path(candidate_name).suffix.casefold()
        if explicit_suffix in _ICON_EXTENSIONS:
            stem = Path(candidate_name).stem
            extensions = (explicit_suffix,)
        else:
            stem = candidate_name
            extensions = _ICON_EXTENSIONS

        active_theme = QIcon.themeName()
        best_path: Path | None = None
        best_score = -1

        for directory in self._icon_directories():
            for extension in extensions:
                candidate = directory / f"{stem}{extension}"
                if not candidate.is_file():
                    continue

                score = _icon_path_score(candidate, active_theme)
                if score > best_score:
                    best_score = score
                    best_path = candidate

        self._path_cache[name] = best_path
        return best_path

    def _icon_directories(self) -> tuple[Path, ...]:
        if self._directories is not None:
            return self._directories

        roots: list[Path] = [Path(path) for path in QIcon.themeSearchPaths() if path]

        data_home = Path(
            os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
        ).expanduser()
        data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
        roots.extend([data_home / "icons", Path.home() / ".icons"])
        roots.extend(
            Path(value).expanduser() / "icons" for value in data_dirs.split(":")
        )
        roots.append(Path("/usr/share/pixmaps"))

        directories: set[Path] = set()
        for root in roots:
            if not root.is_dir():
                continue

            if root.name == "pixmaps":
                directories.add(root)
                continue

            directories.add(root)
            for theme_dir in root.iterdir():
                if not theme_dir.is_dir():
                    continue

                for child in theme_dir.iterdir():
                    if not child.is_dir():
                        continue

                    apps_dir = child / "apps"
                    if apps_dir.is_dir():
                        directories.add(apps_dir)

                apps_dir = theme_dir / "apps"
                if apps_dir.is_dir():
                    directories.add(apps_dir)
                    for size_dir in apps_dir.iterdir():
                        if size_dir.is_dir():
                            directories.add(size_dir)

        self._directories = tuple(sorted(directories))
        return self._directories

    def _fallback_icon(self, text: str, size: int) -> QIcon:
        label = text.strip() or "?"
        screen = QGuiApplication.primaryScreen()
        dpr = max(1.0, screen.devicePixelRatio()) if screen is not None else 1.0
        key = (label, size, int(dpr * 100))

        pixmap = self._fallback_pixmaps.get(key)
        if pixmap is None:
            pixmap = self._draw_fallback(label, size, dpr)
            self._fallback_pixmaps[key] = pixmap

        return QIcon(pixmap)

    @staticmethod
    def _draw_fallback(text: str, size: int, dpr: float) -> QPixmap:
        pixmap = QPixmap(int(size * dpr), int(size * dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.scale(dpr, dpr)

        rect = QRectF(0.5, 0.5, size - 1.0, size - 1.0)
        radius = size * 0.3

        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
        hue = int(digest[:8], 16) % 360
        gradient = QLinearGradient(0.0, 0.0, size, size)
        gradient.setColorAt(0.0, QColor.fromHsl(hue, 150, 132))
        gradient.setColorAt(1.0, QColor.fromHsl((hue + 36) % 360, 170, 86))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, radius, radius)

        highlight = QLinearGradient(0.0, 0.0, 0.0, size)
        highlight.setColorAt(0.0, QColor(255, 255, 255, 42))
        highlight.setColorAt(0.55, QColor(255, 255, 255, 0))
        painter.setBrush(highlight)
        painter.drawRoundedRect(rect, radius, radius)

        letter = next((char for char in text.strip() if char.isalnum()), "?")
        font = QFont(QApplication.font())
        font.setPixelSize(max(10, round(size * 0.43)))
        font.setWeight(QFont.Weight.DemiBold)

        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 235))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, letter.upper())
        painter.end()

        return pixmap
