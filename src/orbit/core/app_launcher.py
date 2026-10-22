"""Launch desktop applications without blocking the launcher.

No shell is involved: the ``Exec`` value is parsed with :mod:`shlex`, desktop
field codes are expanded or removed, and the resulting process is detached from
Orbit's session so closing the launcher does not affect it.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from orbit.core.desktop_entry import DesktopEntry

logger = logging.getLogger(__name__)

_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_FIELD_CODE = re.compile(r"%%|%([fFuUdDnNvmick])")
_TERMINAL_ENV = "TERMINAL"

# Preferred terminals, in order. Most desktops ship one of these.
_TERMINAL_CANDIDATES = (
    "x-terminal-emulator",
    "ptyxis",
    "kgx",
    "gnome-terminal",
    "konsole",
    "alacritty",
    "kitty",
    "foot",
    "wezterm",
    "xfce4-terminal",
    "tilix",
    "mate-terminal",
    "xterm",
)

_DASHDASH_TERMINALS = {"gnome-terminal", "kgx", "ptyxis", "foot"}
_EXECUTE_TERMINALS = {"xfce4-terminal", "mate-terminal", "tilix", "lxterminal"}
_BARE_TERMINALS = {"kitty"}
_WEZTERM = "wezterm"


class LaunchError(RuntimeError):
    """Raised when an application cannot be started."""


def _expand_field_codes(token: str, entry: DesktopEntry) -> str:
    def expand(match: re.Match[str]) -> str:
        if match.group(0) == "%%":
            return "%"

        code = match.group(1)
        if code == "c":
            return entry.name
        if code == "k":
            return str(entry.path)
        # %i and the file/URL/removed field codes do not belong in argv.
        return ""

    return _FIELD_CODE.sub(expand, token)


def _parse_exec(entry: DesktopEntry) -> tuple[list[str], dict[str, str]]:
    try:
        tokens = shlex.split(entry.exec_line, posix=True)
    except ValueError as exc:
        raise LaunchError(f"{entry.name} has an invalid launch command") from exc

    if not tokens:
        raise LaunchError(f"{entry.name} has an empty launch command")

    env_overrides: dict[str, str] = {}
    while tokens and _ENV_ASSIGNMENT.match(tokens[0]):
        key, value = tokens.pop(0).split("=", 1)
        env_overrides[key] = value

    command: list[str] = []
    for token in tokens:
        if token == "%i":
            if entry.icon:
                command.extend(("--icon", entry.icon))
            continue

        if token == "%c":
            command.append(entry.name)
            continue

        if token == "%k":
            command.append(str(entry.path))
            continue

        had_field_code = "%" in token
        cleaned = _expand_field_codes(token, entry)

        if had_field_code and (not cleaned or cleaned.endswith("=")):
            continue
        if cleaned or not had_field_code:
            command.append(cleaned)

    if not command:
        raise LaunchError(f"{entry.name} has no launch command")

    return command, env_overrides


def _find_terminal(explicit: str | None = None) -> list[str]:
    if explicit:
        tokens = shlex.split(explicit)
        if tokens:
            resolved = shutil.which(tokens[0]) or tokens[0]
            return [resolved, *tokens[1:]]

    env_value = os.environ.get(_TERMINAL_ENV, "").strip()
    if env_value:
        tokens = shlex.split(env_value)
        if tokens:
            resolved = shutil.which(tokens[0])
            if resolved:
                return [resolved, *tokens[1:]]

    for candidate in _TERMINAL_CANDIDATES:
        resolved = shutil.which(candidate)
        if resolved:
            return [resolved]

    raise LaunchError("No terminal emulator was found")


def _in_terminal(terminal: Sequence[str], command: Sequence[str]) -> list[str]:
    program = Path(terminal[0]).name
    base = list(terminal)

    if program in _BARE_TERMINALS:
        return [*base, *command]
    if program == _WEZTERM:
        return [*base, "start", "--", *command]
    if program in _DASHDASH_TERMINALS:
        return [*base, "--", *command]
    if program in _EXECUTE_TERMINALS:
        return [*base, "-x", *command]
    return [*base, "-e", *command]


def build_command(entry: DesktopEntry, *, terminal: str | None = None) -> list[str]:
    """Build the argv for *entry* without starting it.

    Exposed separately from :func:`launch` so command generation can be tested
    and inspected independently.
    """

    command, _ = _parse_exec(entry)
    if entry.terminal:
        command = _in_terminal(_find_terminal(terminal), command)
    return command


def launch(
    entry: DesktopEntry, *, terminal: str | None = None
) -> subprocess.Popen[bytes]:
    """Start *entry* as a detached process and return its handle."""

    command, env_overrides = _parse_exec(entry)
    if entry.terminal:
        command = _in_terminal(_find_terminal(terminal), command)

    environment = os.environ.copy()
    if env_overrides:
        environment.update(env_overrides)

    working_dir: str | None = None
    if entry.working_dir:
        candidate = Path(os.path.expanduser(entry.working_dir))
        if candidate.is_dir():
            working_dir = str(candidate)

    try:
        process = subprocess.Popen(
            command,
            cwd=working_dir,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except (OSError, ValueError) as exc:
        logger.warning("Could not launch %s: %s", entry.name, exc)
        raise LaunchError(f"Could not start {entry.name}") from exc

    logger.info("Launched %s (pid %d)", entry.name, process.pid)
    return process
