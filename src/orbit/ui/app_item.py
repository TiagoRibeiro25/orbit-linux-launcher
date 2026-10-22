"""A single, keyboard-aware application row."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QEnterEvent,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QMouseEvent,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from orbit.core.search import SearchResult
from orbit.ui.styles import Theme

_CATEGORY_PRIORITY = (
    "WebBrowser",
    "Game",
    "Development",
    "Graphics",
    "AudioVideo",
    "Network",
    "Office",
    "Education",
    "Science",
    "System",
    "Utility",
    "Settings",
)

_CATEGORY_LABELS = {
    "WebBrowser": "BROWSER",
    "Game": "GAME",
    "Development": "DEVELOPMENT",
    "Graphics": "GRAPHICS",
    "AudioVideo": "MEDIA",
    "Network": "INTERNET",
    "Office": "OFFICE",
    "Education": "EDUCATION",
    "Science": "SCIENCE",
    "System": "SYSTEM",
    "Utility": "UTILITY",
    "Settings": "SETTINGS",
}

_IGNORED_CATEGORIES = {
    "gtk",
    "qt",
    "kde",
    "gnome",
    "application",
    "core",
    "x-",
}


def category_label(categories: tuple[str, ...]) -> str:
    """Turn freedesktop categories into one short, human-friendly badge."""

    by_name = {category.casefold(): category for category in categories}

    for category in _CATEGORY_PRIORITY:
        if category.casefold() in by_name:
            return _CATEGORY_LABELS[category]

    for category in categories:
        folded = category.casefold()
        if folded in _IGNORED_CATEGORIES or folded.startswith("x-"):
            continue
        return category.replace("Application", "").strip().upper()

    return ""


class _HighlightedName(QWidget):
    """Paints the application name with matched query characters emphasized."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._text = ""
        self._positions: frozenset[int] = frozenset()

        font = QFont(QApplication.font())
        font.setPixelSize(15)
        font.setWeight(QFont.Weight.DemiBold)
        self._font = font
        self._metrics = QFontMetrics(font)

        self.setFixedHeight(self._metrics.height())
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_content(self, text: str, positions: tuple[int, ...]) -> None:
        self._text = text
        self._positions = frozenset(positions)
        self.setAccessibleName(text)
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(
            self._metrics.horizontalAdvance(self._text), self._metrics.height()
        )

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self._metrics.height())

    def paintEvent(self, event) -> None:
        if not self._text or self.width() <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setFont(self._font)

        visible = self._metrics.elidedText(
            self._text, Qt.TextElideMode.ElideRight, self.width()
        )
        if not visible:
            return

        normal = QColor(self._theme.text)
        highlighted = QColor(self._theme.accent)
        baseline = (
            self.height() + self._metrics.ascent() - self._metrics.descent()
        ) / 2

        x = 0.0
        for index, character in enumerate(visible):
            painter.setPen(highlighted if index in self._positions else normal)
            painter.drawText(QPointF(x, baseline), character)
            x += self._metrics.horizontalAdvance(character)


class _ElidedText(QWidget):
    """A single muted line that elides instead of clipping."""

    def __init__(
        self,
        theme: Theme,
        text: str,
        color: str,
        pixel_size: int = 12,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._color = QColor(color)

        font = QFont(QApplication.font())
        font.setPixelSize(pixel_size)
        self._font = font
        self._metrics = QFontMetrics(font)

        self.setFixedHeight(self._metrics.height())
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAccessibleName(text)

    def sizeHint(self) -> QSize:
        return QSize(
            self._metrics.horizontalAdvance(self._text), self._metrics.height()
        )

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self._metrics.height())

    def paintEvent(self, event) -> None:
        if not self._text or self.width() <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setFont(self._font)
        painter.setPen(self._color)

        visible = self._metrics.elidedText(
            self._text, Qt.TextElideMode.ElideRight, self.width()
        )
        painter.drawText(
            self.rect(),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            visible,
        )


class _EnterHint(QWidget):
    """A small return-key glyph, visible only on the selected row."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._active = False
        self.setFixedSize(24, 20)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_active(self, active: bool) -> None:
        if active != self._active:
            self._active = active
            self.update()

    def paintEvent(self, event) -> None:
        if not self._active:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        fill = QColor(self._theme.accent)
        fill.setAlphaF(0.14)
        border = QColor(self._theme.accent)
        border.setAlphaF(0.30)

        painter.setBrush(fill)
        painter.setPen(QPen(border, 1.0))
        painter.drawRoundedRect(QRectF(1.5, 2.5, 21.0, 15.0), 5.0, 5.0)

        pen = QPen(QColor(self._theme.accent), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(QPointF(15.8, 6.0), QPointF(15.8, 11.0))
        painter.drawLine(QPointF(15.8, 11.0), QPointF(9.4, 11.0))
        painter.drawLine(QPointF(9.4, 11.0), QPointF(11.8, 8.7))
        painter.drawLine(QPointF(9.4, 11.0), QPointF(11.8, 13.3))


class AppItem(QFrame):
    """One row in the launcher's results list."""

    activated = pyqtSignal(int)
    hovered = pyqtSignal(int)

    def __init__(
        self,
        result: SearchResult,
        icon: QIcon,
        index: int,
        theme: Theme,
        icon_size: int = 38,
        show_category: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._index = index
        self._selected = False

        self.setObjectName("AppItem")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(58)
        self.setProperty("selected", False)

        entry = result.entry

        tooltip = entry.name
        if entry.comment:
            tooltip += f"\n{entry.comment}"
        self.setToolTip(tooltip)
        self.setAccessibleName(entry.name)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 8, 12, 8)
        layout.setSpacing(14)

        icon_label = QLabel(self)
        icon_label.setFixedSize(icon_size, icon_size)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        screen = QGuiApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen is not None else 1.0
        pixmap = icon.pixmap(QSize(icon_size, icon_size), dpr)
        if not pixmap.isNull():
            icon_label.setPixmap(pixmap)

        text_widget = QWidget(self)
        text_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)

        name_label = _HighlightedName(theme, text_widget)
        name_label.set_content(entry.name, result.name_positions)
        text_layout.addWidget(name_label)

        description = entry.comment or entry.generic_name
        description_label: _ElidedText | None = None
        if description:
            description_label = _ElidedText(
                theme, description, theme.muted, 12, text_widget
            )
            text_layout.addWidget(description_label)

        text_height = name_label.height()
        if description_label is not None:
            text_height += 1 + description_label.height()
        text_widget.setFixedHeight(text_height)

        layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(text_widget, 1, Qt.AlignmentFlag.AlignVCenter)

        category = category_label(entry.categories) if show_category else ""
        if category:
            badge = QLabel(category, self)
            badge.setObjectName("CategoryBadge")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedHeight(20)
            badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)

        self._enter_hint = _EnterHint(theme, self)
        layout.addWidget(self._enter_hint, 0, Qt.AlignmentFlag.AlignVCenter)

    @property
    def selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool) -> None:
        if selected == self._selected:
            return

        self._selected = selected
        self.setProperty("selected", selected)
        self._enter_hint.set_active(selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def enterEvent(self, event: QEnterEvent) -> None:
        self.hovered.emit(self._index)
        super().enterEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.activated.emit(self._index)
        super().mouseReleaseEvent(event)
