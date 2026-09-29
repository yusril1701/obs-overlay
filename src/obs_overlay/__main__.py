"""``python -m obs_overlay``, the installed scripts, and the frozen .exe.

The import below is **absolute on purpose**, and must stay that way.

PyInstaller uses this file as its entry script and runs it as a plain
top-level script named ``__main__`` with no package context, so a relative
``from .cli import ...`` raises "attempted relative import with no known
parent package" and the built executable dies before it draws anything. An
absolute import works in every launch mode — ``python -m obs_overlay``, the
``obs-overlay`` console script, and the frozen bundle — because the package
is importable in all three.

``tests/test_entry_point.py`` runs this file the way PyInstaller does, so the
mistake cannot come back unnoticed.
"""

from __future__ import annotations

import sys


def main() -> int:
    from obs_overlay.cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    sys.exit(main())
