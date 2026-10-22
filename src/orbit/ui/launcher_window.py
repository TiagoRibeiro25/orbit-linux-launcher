"""The frameless, floating launcher window."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QPointF,
    QPropertyAnimation,
    Qt,
    QTimer,
)
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QKeyEvent,
    QPainter,
    QPen,
    QShowEvent,
)
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from orbit.config.settings import APP_NAME, Settings
from orbit.core.desktop_entry import DesktopEntry
from orbit.core.search import search
from orbit.services.icon_service import IconService
from orbit.ui.results_list import ResultsList
from orbit.ui.search_bar import SearchBar
from orbit.ui.styles import Theme, shadow_color

logger = logging.getLogger(__name__)

# Setting a top-level window's opacity is not supported by the Wayland plugin
# (and several other embedded platforms). Only animate where Qt can honour it.
_OPACITY_PLATFORMS = frozenset({"xcb", "windows", "cocoa"})


class _BrandMark(QWidget):
    """The small orbit glyph shown next to the wordmark."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setFixedSize(16, 16)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.translate(self.width() / 2, self.height() / 2)

        accent = QColor(self._theme.accent)
        ring = QColor(accent)
        ring.setAlpha(185)
        pen = QPen(ring, 1.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        painter.save()
        painter.rotate(-20.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(0.0, 0.0), 7.0, 2.6)
        satellite = QColor(accent)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(satellite)
        painter.drawEllipse(QPointF(5.8, 1.25), 0.9, 0.9)
        painter.restore()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawEllipse(QPointF(0.0, 0.0), 3.1, 3.1)


class LauncherWindow(QWidget):
    """Top-level launcher UI and its keyboard flow."""

    def __init__(
        self,
        *,
        entries: Sequence[DesktopEntry],
        icon_service: IconService,
        settings: Settings,
        theme: Theme,
        on_launch: Callable[[DesktopEntry], object],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._entries = list(entries)
        self._settings = settings
        self._theme = theme
        self._on_launch = on_launch
        self._fade_played = False
        self._focus_close_armed = False
        self._fade_animation: QPropertyAnimation | None = None
        self._window_opacity_supported = (
            QGuiApplication.platformName() in _OPACITY_PLATFORMS
        )

        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        if self._window_opacity_supported:
            self.setWindowOpacity(0.0)

        self._build_ui(icon_service)
        self._wire_signals()
        self._refresh_results("")
        self._place_on_screen()

    def _build_ui(self, icon_service: IconService) -> None:
        margins = self._settings.shadow_margin

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(margins, margins, margins, margins)
        root_layout.setSpacing(0)

        self._panel = QFrame(self)
        self._panel.setObjectName("LauncherPanel")
        self._panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        shadow = QGraphicsDropShadowEffect(self._panel)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 12)
        shadow.setColor(shadow_color(self._theme))
        self._panel.setGraphicsEffect(shadow)

        root_layout.addWidget(self._panel)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        self._search = SearchBar(
            self._theme,
            placeholder=self._settings.search_placeholder,
            parent=self._panel,
        )
        panel_layout.addWidget(self._search)
        panel_layout.addWidget(self._divider())

        content = QWidget(self._panel)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        header = QWidget(content)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 10, 24, 2)
        header_layout.setSpacing(8)

        self._eyebrow = QLabel("APPLICATIONS", header)
        self._eyebrow.setObjectName("Eyebrow")
        self._count = QLabel("", header)
        self._count.setObjectName("ResultCount")

        header_layout.addWidget(self._eyebrow, 0, Qt.AlignmentFlag.AlignVCenter)
        header_layout.addStretch(1)
        header_layout.addWidget(self._count, 0, Qt.AlignmentFlag.AlignVCenter)

        self._results = ResultsList(
            icon_service,
            self._theme,
            icon_size=self._settings.icon_size,
            show_categories=self._settings.show_categories,
            parent=content,
        )

        content_layout.addWidget(header)
        content_layout.addWidget(self._results, 1)
        panel_layout.addWidget(content, 1)
        panel_layout.addWidget(self._divider())

        panel_layout.addWidget(self._build_footer())

    def _build_footer(self) -> QWidget:
        footer = QWidget(self._panel)
        footer.setFixedHeight(46)

        layout = QHBoxLayout(footer)
        layout.setContentsMargins(20, 0, 20, 4)
        layout.setSpacing(10)

        brand_mark = _BrandMark(self._theme, footer)
        brand_label = QLabel("orbit", footer)
        brand_label.setObjectName("Brand")
        brand_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._error_label = QLabel("", footer)
        self._error_label.setObjectName("ErrorLabel")
        self._error_label.setVisible(False)
        self._error_label.setMaximumWidth(390)

        self._hints = QWidget(footer)
        hints_layout = QHBoxLayout(self._hints)
        hints_layout.setContentsMargins(0, 0, 0, 0)
        hints_layout.setSpacing(16)
        hints_layout.addWidget(self._hint_group(("↑", "↓"), "navigate"))
        hints_layout.addWidget(self._hint_group(("↵",), "launch"))
        hints_layout.addWidget(self._hint_group(("esc",), "close"))

        layout.addWidget(brand_mark, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(brand_label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addSpacing(12)
        layout.addWidget(self._error_label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)
        layout.addWidget(self._hints, 0, Qt.AlignmentFlag.AlignVCenter)

        self._error_timer = QTimer(self)
        self._error_timer.setSingleShot(True)
        self._error_timer.setInterval(5000)
        self._error_timer.timeout.connect(self._clear_error)

        return footer

    def _hint_group(self, keys: tuple[str, ...], action: str) -> QWidget:
        group = QWidget(self)
        layout = QHBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        for key in keys:
            key_label = QLabel(key, group)
            key_label.setObjectName("KeyCap")
            key_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            key_label.setFixedHeight(18)
            key_label.setMinimumWidth(18)
            key_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(key_label)

        action_label = QLabel(action, group)
        action_label.setObjectName("Hint")
        action_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(action_label)

        return group

    @staticmethod
    def _divider() -> QFrame:
        divider = QFrame()
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)
        return divider

    def _wire_signals(self) -> None:
        self._search.textChanged.connect(self._refresh_results)
        self._search.navigateRequested.connect(self._results.move_selection)
        self._search.activateRequested.connect(self._results.activate_current)
        self._search.escapeRequested.connect(self.close)
        self._results.activated.connect(self._launch)

    def _refresh_results(self, query: str) -> None:
        matches = search(self._entries, query)
        visible = matches[: self._settings.max_results]

        self._results.set_results(
            visible,
            query=query,
            has_applications=bool(self._entries),
        )

        if query.strip():
            self._eyebrow.setText("SEARCH RESULTS")
            self._count.setText(f"{len(matches)} found")
        else:
            self._eyebrow.setText("APPLICATIONS")
            self._count.setText(f"{len(self._entries)} installed")

    def _launch(self, entry: DesktopEntry) -> None:
        try:
            self._on_launch(entry)
        except Exception as exc:  # noqa: BLE001 - surface failures in the UI
            logger.warning("Failed to launch %s: %s", entry.name, exc)
            self._show_error(str(exc) or f"Could not launch {entry.name}")
            return

        self.close()

    def _show_error(self, message: str) -> None:
        self._error_label.setText(message)
        self._error_label.setToolTip(message)
        self._error_label.setVisible(True)
        self._hints.setVisible(False)
        self._error_timer.start()

    def _clear_error(self) -> None:
        self._error_label.clear()
        self._error_label.setToolTip("")
        self._error_label.setVisible(False)
        self._hints.setVisible(True)

    def _place_on_screen(self) -> None:
        screen = (
            QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        )
        if screen is None:
            return

        available = screen.availableGeometry()
        margin = self._settings.shadow_margin
        desired_width = self._settings.window_width + margin * 2
        desired_height = self._settings.window_height + margin * 2

        width = max(420, min(desired_width, available.width() - 24))
        height = max(320, min(desired_height, available.height() - 24))
        self.setFixedSize(width, height)

        x = available.x() + (available.width() - width) // 2
        y = available.y() + int(available.height() * self._settings.window_top_ratio)
        y = min(y, available.y() + available.height() - height - 16)
        y = max(available.y() + 8, y)

        self.move(x, y)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)

        if self._window_opacity_supported and not self._fade_played:
            self._fade_played = True
            self._fade_animation = QPropertyAnimation(self, b"windowOpacity", self)
            self._fade_animation.setDuration(150)
            self._fade_animation.setStartValue(0.0)
            self._fade_animation.setEndValue(1.0)
            self._fade_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._fade_animation.finished.connect(lambda: self.setWindowOpacity(1.0))
            self._fade_animation.start()

        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, self._search.focus_input)
        QTimer.singleShot(200, self._arm_focus_close)

    def _arm_focus_close(self) -> None:
        self._focus_close_armed = True

    def event(self, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.WindowDeactivate
            and self._focus_close_armed
            and self._settings.close_on_focus_loss
        ):
            QTimer.singleShot(0, self._close_if_inactive)

        return super().event(event)

    def _close_if_inactive(self) -> None:
        if self.isVisible() and not self.isActiveWindow():
            self.close()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)
