"""The entry point has to survive every way it is launched.

PyInstaller does not run ``src/obs_overlay/__main__.py`` as a module. It runs
it as a top-level script called ``__main__`` with no package, which is exactly
the one context where a relative import fails. That failure does not show up
in any ordinary test — the package imports fine — and it does not show up at
build time either; it only appears when someone double-clicks the .exe.

So these tests launch the real file the same three ways the shipped product
does, in a subprocess, and check that it actually runs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from obs_overlay.constants import APP_NAME, APP_VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
MAIN_PY = SRC_DIR / "obs_overlay" / "__main__.py"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    # Qt needs a platform plugin even for --version, because argparse's
    # version action runs before anything else but the imports do not.
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(PROJECT_ROOT),
    )


@pytest.mark.skipif(not MAIN_PY.is_file(), reason="running against an installed package")
def test_runs_as_a_bare_script() -> None:
    """The PyInstaller case: no package, no -m, just the file.

    A relative import in __main__.py fails here and nowhere else.
    """
    result = _run([str(MAIN_PY), "--version"])
    assert "attempted relative import" not in result.stderr
    assert result.returncode == 0, result.stderr
    assert APP_VERSION in result.stdout


def test_runs_as_a_module() -> None:
    """The development case: ``python -m obs_overlay``."""
    result = _run(["-m", "obs_overlay", "--version"])
    assert result.returncode == 0, result.stderr
    assert APP_NAME in result.stdout
    assert APP_VERSION in result.stdout


def test_main_callable_is_importable() -> None:
    """The console-script case: ``obs-overlay = obs_overlay.__main__:main``.

    The entry point declared in pyproject.toml is resolved by importing the
    module and reading the attribute, so that path has to work too.
    """
    import importlib

    module = importlib.import_module("obs_overlay.__main__")
    assert callable(module.main)
