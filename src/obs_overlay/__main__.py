"""``python -m obs_overlay`` and the installed console/GUI scripts."""

from __future__ import annotations

import sys


def main() -> int:
    from .cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    sys.exit(main())
