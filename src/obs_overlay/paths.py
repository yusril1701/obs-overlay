"""Filesystem locations used by the app.

Everything user-writable lives under a single per-user directory:

* Windows  ``%APPDATA%\\obs-overlay``
* elsewhere ``$XDG_CONFIG_HOME/obs-overlay`` (or ``~/.config/obs-overlay``)

The non-Windows branch exists purely so the test suite and development on
Linux/macOS behave sanely; the shipped application targets Windows.

A portable mode is supported: if a file named ``portable.txt`` sits next to the
executable (or next to the package during development), all data is stored in a
``data`` folder there instead, which is what you want on a USB stick.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .constants import APP_SLUG

_PORTABLE_MARKER = "portable.txt"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def bundle_dir() -> Path:
    """Directory that holds bundled read-only resources.

    Under PyInstaller this is the extraction dir (``sys._MEIPASS``); in a normal
    checkout it is the package directory.
    """
    if is_frozen():
        # PyInstaller injects _MEIPASS at runtime; it does not exist in the
        # `sys` stubs, so it has to be fetched dynamically.
        return Path(getattr(sys, "_MEIPASS"))  # noqa: B009
    return Path(__file__).resolve().parent


def executable_dir() -> Path:
    """Directory containing the running executable (or the repo root in dev)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    # src/obs_overlay/paths.py -> repo root
    return Path(__file__).resolve().parents[2]


def portable_marker_path() -> Path:
    return executable_dir() / _PORTABLE_MARKER


def is_portable() -> bool:
    return portable_marker_path().is_file()


def _default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_SLUG
        return Path.home() / "AppData" / "Roaming" / APP_SLUG
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / APP_SLUG
    return Path.home() / ".config" / APP_SLUG


def data_dir() -> Path:
    """Root directory for all user-writable application data.

    Honours, in order: the ``OBS_OVERLAY_DATA_DIR`` environment variable
    (used by the tests), portable mode, then the per-user OS location.
    """
    override = os.environ.get("OBS_OVERLAY_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if is_portable():
        return executable_dir() / "data"
    return _default_data_dir()


def profiles_dir() -> Path:
    return data_dir() / "profiles"


def logs_dir() -> Path:
    return data_dir() / "logs"


def settings_path() -> Path:
    """Small file holding app-level state (which profile was last active)."""
    return data_dir() / "settings.json"


def resources_dir() -> Path:
    """Read-only bundled resources (icons, built-in presets)."""
    return bundle_dir() / "resources"


def ensure_dirs() -> None:
    """Create every user-writable directory the app needs."""
    for path in (data_dir(), profiles_dir(), logs_dir()):
        path.mkdir(parents=True, exist_ok=True)
