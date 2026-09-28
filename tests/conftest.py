"""Shared pytest fixtures.

Qt runs under the ``offscreen`` platform plugin so the GUI-dependent tests work
on a headless CI runner. One ``QApplication`` is shared by the whole session:
Qt does not support creating a second one in the same process.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Must be set before QApplication is constructed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(scope="session")
def qapp():
    """A single QApplication for the session."""
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    created = app is None
    if created:
        app = QApplication([])
    yield app
    # Deliberately not calling quit(): other session-scoped fixtures may still
    # hold widgets, and the process is about to exit anyway.


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Redirect all app storage into a temporary directory."""
    target = tmp_path / "appdata"
    target.mkdir()
    monkeypatch.setenv("OBS_OVERLAY_DATA_DIR", str(target))
    return target


@pytest.fixture()
def store(data_dir):
    from obs_overlay.config.store import ConfigStore

    store = ConfigStore()
    store.ensure_dirs()
    return store


@pytest.fixture()
def profile():
    from obs_overlay.config.models import Profile

    return Profile.default()
