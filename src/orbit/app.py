"""Application bootstrap: Qt configuration, wiring and the event loop."""

from __future__ import annotations

import logging
import os
import signal
import sys

from PyQt6.QtCore import QLoggingCategory, Qt, QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication

from orbit import __version__
from orbit.config.settings import APP_NAME, APP_SLUG, Settings
from orbit.core.app_discovery import AppDiscovery
from orbit.core.app_launcher import launch
from orbit.services.icon_service import IconService
from orbit.ui.launcher_window import LauncherWindow
from orbit.ui.styles import (
    build_app_font,
    build_stylesheet,
    resolve_theme,
)

logger = logging.getLogger(__name__)


def _configure_environment() -> bool:
    # Orbit launches applications directly and never uses desktop portals.
    # Opting out avoids an unnecessary D-Bus round trip and Qt's portal
    # registration warning when running from a source checkout. Return whether
    # the variable was added so it can be removed again once Qt has started,
    # keeping the environment clean for applications Orbit launches.
    if "QT_NO_XDG_DESKTOP_PORTAL" in os.environ:
        return False

    os.environ["QT_NO_XDG_DESKTOP_PORTAL"] = "1"
    return True


def _restore_environment() -> None:
    os.environ.pop("QT_NO_XDG_DESKTOP_PORTAL", None)


def _configure_qt_logging() -> None:
    # Broken third-party SVG icon assets still render in Qt but produce a
    # warning each time. Quiet that category without touching other logging.
    # ORBIT_DEBUG keeps the warnings visible for icon troubleshooting.
    rules = os.environ.get("QT_LOGGING_RULES", "")
    if not os.environ.get("ORBIT_DEBUG") and "qt.svg" not in rules:
        QLoggingCategory.setFilterRules("qt.svg.warning=false")


def _configure_logging() -> None:
    level = logging.DEBUG if os.environ.get("ORBIT_DEBUG") else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )


def _configure_signals() -> None:
    # Qt's event loop does not process Python signal handlers while idle. Let
    # the terminal's default Ctrl+C behaviour terminate the launcher cleanly.
    try:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    except ValueError:
        pass


def create_application(argv: list[str] | None = None) -> QApplication:
    """Create and configure the single QApplication instance."""

    application = QApplication(argv if argv is not None else sys.argv)
    application.setApplicationName(APP_SLUG)
    application.setApplicationDisplayName(APP_NAME)
    application.setApplicationVersion(__version__)
    application.setOrganizationName(APP_NAME)
    application.setDesktopFileName(APP_SLUG)
    application.setStyle("Fusion")
    return application


def run(argv: list[str] | None = None) -> int:
    """Start Orbit and block until its window closes."""

    _configure_logging()
    _configure_signals()
    restore_portal_environment = _configure_environment()

    settings = Settings.load()

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    application = create_application(list(argv) if argv is not None else None)
    _configure_qt_logging()
    application.setFont(build_app_font(settings.font_family))

    theme = resolve_theme(settings.theme, settings.accent_color)
    application.setStyleSheet(
        build_stylesheet(theme, window_radius=settings.window_radius)
    )

    icon_service = IconService(settings.icon_size)
    application.setWindowIcon(icon_service.get_icon("", APP_NAME, size=64))

    entries = AppDiscovery().discover()
    logger.info("Starting Orbit with %d applications", len(entries))

    window = LauncherWindow(
        entries=entries,
        icon_service=icon_service,
        settings=settings,
        theme=theme,
        on_launch=launch,
    )
    window.show()

    if restore_portal_environment:
        QTimer.singleShot(0, _restore_environment)

    return application.exec()
