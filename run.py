#!/usr/bin/env python3
"""Development entry point.

Runs the app straight from a checkout without installing it, by putting ``src``
on the path first. For a normal install use the ``obs-overlay`` command.

    python run.py --demo
    python run.py --log-level DEBUG
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from obs_overlay.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
