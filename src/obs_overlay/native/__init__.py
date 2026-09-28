"""Native (Windows) integration, behind an interface that no-ops elsewhere.

Import this package anywhere: it never imports ``win32`` or ``ctypes.windll``
at module load. :func:`create_window_controller` and
:func:`create_hotkey_manager` pick the real implementation only when running on
Windows, so the whole app — and its test suite — still imports on Linux/macOS.
"""

from __future__ import annotations

import logging

from ..constants import IS_WINDOWS
from .base import HotkeyManager, NullHotkeyManager, NullWindowController, WindowController

logger = logging.getLogger(__name__)


def create_window_controller() -> WindowController:
    """The best available window controller for this platform."""
    if IS_WINDOWS:
        try:
            from .win32_window import Win32WindowController

            return Win32WindowController()
        except Exception as exc:  # pragma: no cover - platform dependent
            logger.error("Win32 integration unavailable (%s); click-through disabled.", exc)
    return NullWindowController()


def create_hotkey_manager() -> HotkeyManager:
    """The best available global-hotkey manager for this platform."""
    if IS_WINDOWS:
        try:
            from .hotkeys import Win32HotkeyManager

            return Win32HotkeyManager()
        except Exception as exc:  # pragma: no cover - platform dependent
            logger.error("Global hotkeys unavailable: %s", exc)
    return NullHotkeyManager()


__all__ = [
    "HotkeyManager",
    "NullHotkeyManager",
    "NullWindowController",
    "WindowController",
    "create_hotkey_manager",
    "create_window_controller",
]
