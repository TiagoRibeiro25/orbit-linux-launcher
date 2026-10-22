#!/usr/bin/env python3
"""Orbit application launcher entry point."""

from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def main() -> int:
    try:
        from orbit.app import run
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.split(".", 1)[0] == "PyQt6":
            print(
                "Orbit requires PyQt6. Install the dependencies with:\n"
                f"  {sys.executable} -m pip install -r requirements.txt",
                file=sys.stderr,
            )
            return 1
        raise

    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
