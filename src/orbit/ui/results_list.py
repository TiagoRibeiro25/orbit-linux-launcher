"""Scrollable results area with selection, keyboard navigation and an empty state."""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import QPointF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPen, QResizeEvent
from PyQt6.QtWidgets import (
    QLabel,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from orbit.core.desktop_entry import DesktopEntry
from orbit.core.search import SearchResult
from orbit.services.icon_service import IconService
from orbit.ui.app_item import AppItem
from orbit.ui.styles import Theme

# Only the rows around the viewport are materialized. Building every possible
# result up front costs tens of milliseconds and resolves icons nobody sees.
_INITIAL_ROW_COUNT = 14
_SCROLL_OVERSCAN = 3


class _OrbitArt(QWidget):
    """Small decorative planet used by the empty state."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setFixedSize(78, 78)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.translate(self.width() / 2, self.height() / 2)

        accent = QColor(self._theme.accent)
        lighter = QColor(self._theme.accent).lighter(135)

        ring_color = QColor(accent)
        ring_color.setAlpha(145)
        ring_pen = QPen(ring_color, 2.0)
        ring_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        painter.save()
        painter.rotate(-18.0)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(ring_pen)
        painter.drawEllipse(QPointF(0.0, 0.0), 31.0, 10.5)

        satellite = QColor(accent)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(satellite)
        painter.drawEllipse(QPointF(25.8, 5.2), 2.5, 2.5)
        painter.restore()

        gradient = QLinearGradient(-13.0, -13.0, 13.0, 13.0)
        gradient.setColorAt(0.0, lighter)
        gradient.setColorAt(1.0, accent)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(QPointF(0.0, 0.0), 14.0, 14.0)

        highlight = QColor(255, 255, 255, 50)
        painter.setBrush(highlight)
        painter.drawEllipse(QPointF(-4.3, -4.5), 4.6, 4.6)


class _ScrollFade(QWidget):
    """Softly fades the last visible row into the panel when more results follow."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        gradient = QLinearGradient(0.0, 0.0, 0.0, float(self.height()))
        start = QColor(self._theme.panel_bottom)
        start.setAlpha(0)
        end = QColor(self._theme.panel_bottom)
        end.setAlpha(245)
        gradient.setColorAt(0.0, start)
        gradient.setColorAt(1.0, end)
        painter.fillRect(self.rect(), gradient)


class _EmptyState(QWidget):
    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        art = _OrbitArt(theme, self)

        self._title = QLabel(self)
        self._title.setObjectName("EmptyTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._body = QLabel(self)
        self._body.setObjectName("EmptyBody")
        self._body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._body.setWordWrap(False)
        self._body.setMaximumWidth(480)
        self._body.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 24, 40, 24)
        layout.setSpacing(0)
        layout.addStretch(1)
        layout.addWidget(art, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(16)
        layout.addWidget(self._title, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(6)
        layout.addWidget(self._body, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)

    def set_message(self, title: str, body: str) -> None:
        self._title.setText(title)
        self._body.setText(body)


class ResultsList(QWidget):
    """Owns application rows and keeps keyboard and mouse selection in sync."""

    activated = pyqtSignal(object)  # DesktopEntry

    def __init__(
        self,
        icon_service: IconService,
        theme: Theme,
        *,
        icon_size: int = 38,
        show_categories: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icons = icon_service
        self._theme = theme
        self._icon_size = icon_size
        self._show_categories = show_categories

        self._results: list[SearchResult] = []
        self._items: list[AppItem] = []
        self._selected_index = -1

        self._stack = QStackedWidget(self)
        self._stack.setObjectName("ResultsStack")

        self._scroll = QScrollArea(self._stack)
        self._scroll.setObjectName("ResultsScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.viewport().setAutoFillBackground(False)

        self._content = QWidget()
        self._content.setObjectName("ResultsContent")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(10, 2, 8, 8)
        self._content_layout.setSpacing(2)
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._content)

        self._empty = _EmptyState(theme, self._stack)

        self._stack.addWidget(self._scroll)
        self._stack.addWidget(self._empty)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        self._fade = _ScrollFade(theme, self)
        self._fade.hide()
        self._fade.raise_()

        scrollbar = self._scroll.verticalScrollBar()
        scrollbar.valueChanged.connect(self._on_scroll)
        scrollbar.rangeChanged.connect(self._update_fade)

        self._stack.setCurrentWidget(self._empty)
        self.set_empty_message(
            "No applications found",
            "Orbit could not find any installed applications.",
        )

    def set_results(
        self,
        results: Sequence[SearchResult],
        *,
        query: str = "",
        has_applications: bool = True,
    ) -> None:
        self._clear_items()

        self._results = list(results)
        self._build_items(min(len(self._results), _INITIAL_ROW_COUNT))
        self._update_content_height()

        if self._results:
            self._selected_index = -1
            self._set_selected(0, scroll=False)
            self._scroll.verticalScrollBar().setValue(0)
            self._stack.setCurrentWidget(self._scroll)
            QTimer.singleShot(0, self._ensure_selection_visible)
            QTimer.singleShot(0, self._fill_visible_rows)
        else:
            self._selected_index = -1
            if not has_applications:
                self.set_empty_message(
                    "No applications found",
                    "Orbit could not find any installed applications.",
                )
            else:
                display_query = query.strip()
                if len(display_query) > 26:
                    display_query = display_query[:25].rstrip() + "…"
                self.set_empty_message(
                    "No matches found",
                    f"Nothing here matches “{display_query}”.\n"
                    "Try a different name, keyword, or category.",
                )
            self._stack.setCurrentWidget(self._empty)

        QTimer.singleShot(0, self._update_fade)

    def move_selection(self, delta: int) -> None:
        if not self._results:
            return

        start = max(self._selected_index, 0)
        self._set_selected((start + delta) % len(self._results))

    def activate_current(self) -> None:
        if 0 <= self._selected_index < len(self._results):
            self.activated.emit(self._results[self._selected_index].entry)

    def selected_entry(self) -> DesktopEntry | None:
        if 0 <= self._selected_index < len(self._results):
            return self._results[self._selected_index].entry
        return None

    def set_empty_message(self, title: str, body: str) -> None:
        self._empty.set_message(title, body)

    def _build_items(self, count: int) -> None:
        target = min(count, len(self._results))
        if target <= len(self._items):
            return

        for index in range(len(self._items), target):
            result = self._results[index]
            item = AppItem(
                result,
                self._icons,
                index,
                self._theme,
                icon_size=self._icon_size,
                show_category=self._show_categories,
                parent=self._content,
            )
            item.activated.connect(self._activate)
            item.hovered.connect(self._hover)
            self._content_layout.addWidget(item, 0)
            self._items.append(item)

    def _ensure_items_through(self, index: int) -> None:
        if index >= len(self._items):
            self._build_items(
                min(len(self._results), max(index + 1, len(self._items) + 8))
            )

    def _fill_visible_rows(self) -> None:
        if not self._results:
            return

        scrollbar = self._scroll.verticalScrollBar()
        viewport_height = self._scroll.viewport().height()
        if viewport_height <= 0:
            return

        step = AppItem.ROW_HEIGHT + self._content_layout.spacing()
        last_row = (scrollbar.value() + viewport_height) // step
        target = min(len(self._results), last_row + 1 + _SCROLL_OVERSCAN)
        self._build_items(max(target, _INITIAL_ROW_COUNT))
        self._update_fade()

    def _on_scroll(self, value: int) -> None:
        self._fill_visible_rows()
        self._update_fade()

    def _clear_items(self) -> None:
        self._selected_index = -1
        self._results = []
        self._items = []

        while self._content_layout.count():
            layout_item = self._content_layout.takeAt(0)
            widget = layout_item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

        self._content.setMinimumHeight(0)

    def _update_content_height(self) -> None:
        margins = self._content_layout.contentsMargins()
        spacing = self._content_layout.spacing()
        count = len(self._results)
        content_height = margins.top() + margins.bottom()
        if count:
            content_height += count * AppItem.ROW_HEIGHT
            content_height += max(0, count - 1) * spacing
        self._content.setMinimumHeight(content_height)
        self._content.updateGeometry()

    def _set_selected(self, index: int, *, scroll: bool = True) -> None:
        if not (0 <= index < len(self._results)):
            return

        self._ensure_items_through(index)

        if index != self._selected_index:
            if 0 <= self._selected_index < len(self._items):
                self._items[self._selected_index].set_selected(False)
            self._selected_index = index
            self._items[index].set_selected(True)

        if scroll:
            self._ensure_selection_visible()

    def _ensure_selection_visible(self) -> None:
        if 0 <= self._selected_index < len(self._results):
            self._ensure_items_through(self._selected_index)
            self._scroll.ensureWidgetVisible(
                self._items[self._selected_index],
                0,
                14,
            )

    def _update_fade(self, *_: object) -> None:
        scrollbar = self._scroll.verticalScrollBar()
        scrollbar_width = max(8, scrollbar.sizeHint().width())
        self._fade.setGeometry(
            0,
            self.height() - 30,
            max(0, self.width() - scrollbar_width),
            30,
        )

        has_more = (
            self._stack.currentWidget() is self._scroll
            and scrollbar.maximum() > 0
            and scrollbar.maximum() - scrollbar.value() > 2
        )
        self._fade.setVisible(has_more)
        if has_more:
            self._fade.raise_()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self.isVisible():
            self._fill_visible_rows()
        self._update_fade()

    def _activate(self, index: int) -> None:
        if 0 <= index < len(self._results):
            self.activated.emit(self._results[index].entry)

    def _hover(self, index: int) -> None:
        if index != self._selected_index:
            self._set_selected(index)
