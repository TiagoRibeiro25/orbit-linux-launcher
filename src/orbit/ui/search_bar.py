"""Search input with keyboard signals and understated custom glyphs."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent, QPainter, QPalette, QPen
from PyQt6.QtWidgets import QAbstractButton, QHBoxLayout, QLineEdit, QWidget

from orbit.ui.styles import Theme


class _SearchGlyph(QWidget):
    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._active = True
        self.setFixedSize(20, 20)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_active(self, active: bool) -> None:
        if active != self._active:
            self._active = active
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        color = QColor(self._theme.accent if self._active else self._theme.faint)
        if not self._active:
            color.setAlpha(190)

        pen = QPen(color, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        painter.drawEllipse(QPointF(8.4, 8.4), 6.0, 6.0)
        painter.drawLine(QPointF(13.0, 13.0), QPointF(17.0, 17.0))


class _ClearButton(QAbstractButton):
    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Clear search")
        self.setAccessibleName("Clear search")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self._theme.hover))
            painter.drawRoundedRect(QRectF(1, 1, 24, 24), 7, 7)

        color = QColor(self._theme.accent if self.underMouse() else self._theme.muted)
        pen = QPen(color, 1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(9.5, 9.5), QPointF(16.5, 16.5))
        painter.drawLine(QPointF(16.5, 9.5), QPointF(9.5, 16.5))

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)


class _SearchInput(QLineEdit):
    navigateRequested = pyqtSignal(int)
    activateRequested = pyqtSignal()
    escapeRequested = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()

        if key == Qt.Key.Key_Up:
            self.navigateRequested.emit(-1)
            event.accept()
            return
        if key == Qt.Key.Key_Down:
            self.navigateRequested.emit(1)
            event.accept()
            return
        if key == Qt.Key.Key_PageUp:
            self.navigateRequested.emit(-5)
            event.accept()
            return
        if key == Qt.Key.Key_PageDown:
            self.navigateRequested.emit(5)
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.activateRequested.emit()
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self.escapeRequested.emit()
            event.accept()
            return

        super().keyPressEvent(event)


class SearchBar(QWidget):
    """The launcher's single search field."""

    textChanged = pyqtSignal(str)
    navigateRequested = pyqtSignal(int)
    activateRequested = pyqtSignal()
    escapeRequested = pyqtSignal()

    def __init__(
        self,
        theme: Theme,
        placeholder: str = "Search applications…",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme

        self._glyph = _SearchGlyph(theme, self)

        self._input = _SearchInput(self)
        self._input.setObjectName("SearchInput")
        self._input.setFrame(False)
        self._input.setPlaceholderText(placeholder)
        self._input.setClearButtonEnabled(False)
        self._input.setAccessibleName("Search applications")
        self._input.installEventFilter(self)

        palette = self._input.palette()
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(theme.faint))
        self._input.setPalette(palette)

        self._clear_button = _ClearButton(theme, self)
        self._clear_button.hide()
        self._clear_button.clicked.connect(self._clear)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 16, 18, 16)
        layout.setSpacing(14)
        layout.addWidget(self._glyph, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._input, 1)
        layout.addWidget(self._clear_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self._input.textChanged.connect(self._on_text_changed)
        self._input.navigateRequested.connect(self.navigateRequested)
        self._input.activateRequested.connect(self.activateRequested)
        self._input.escapeRequested.connect(self.escapeRequested)

        self.setFixedHeight(70)

    def eventFilter(self, watched, event) -> bool:
        if watched is self._input:
            if event.type() == QEvent.Type.FocusIn:
                self._glyph.set_active(True)
            elif event.type() == QEvent.Type.FocusOut:
                self._glyph.set_active(False)
        return super().eventFilter(watched, event)

    def _on_text_changed(self, text: str) -> None:
        self._clear_button.setVisible(bool(text))
        self.textChanged.emit(text)

    def _clear(self) -> None:
        self._input.clear()
        self.focus_input()

    def set_text(self, text: str) -> None:
        self._input.setText(text)
        self._input.setCursorPosition(len(text))

    def text(self) -> str:
        return self._input.text()

    def focus_input(self) -> None:
        self._input.setFocus(Qt.FocusReason.OtherFocusReason)

    def select_all(self) -> None:
        self._input.selectAll()
