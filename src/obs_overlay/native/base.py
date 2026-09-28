"""Platform interfaces and their no-op implementations.

The no-op versions let the whole application run on Linux/macOS for
development and testing. The overlay still appears and still masks itself —
only the Windows-specific behaviours (click-through, tool window, capture
exclusion, global hotkeys) are absent, and each one reports that it is
unsupported rather than pretending to have worked.
"""

from __future__ import annotations

import abc
import logging
from typing import Callable

logger = logging.getLogger(__name__)


class WindowController(abc.ABC):
    """Manipulates native window attributes of an already-created window."""

    #: Whether this controller actually does anything.
    supported: bool = False

    @abc.abstractmethod
    def attach(self, hwnd: int) -> bool:
        """Bind to a native window handle. Returns True when usable."""

    @abc.abstractmethod
    def detach(self) -> None:
        """Forget the current handle."""

    @abc.abstractmethod
    def set_click_through(self, enabled: bool) -> bool:
        """Make mouse input pass through the window (or stop doing so)."""

    @abc.abstractmethod
    def set_tool_window(self, enabled: bool) -> bool:
        """Hide the window from the taskbar and the Alt-Tab list."""

    @abc.abstractmethod
    def set_no_activate(self, enabled: bool) -> bool:
        """Stop the window from taking focus when clicked."""

    @abc.abstractmethod
    def set_topmost(self, enabled: bool) -> bool:
        """Put the window in (or take it out of) the always-on-top band."""

    @abc.abstractmethod
    def reassert_topmost(self) -> bool:
        """Re-apply always-on-top, which fullscreen apps can steal."""

    @abc.abstractmethod
    def set_excluded_from_capture(self, enabled: bool) -> bool:
        """Hide the window from screen recorders and capture APIs."""

    @abc.abstractmethod
    def is_click_through(self) -> bool | None:
        """Current click-through state, or ``None`` when unknown."""

    def describe(self) -> str:
        return type(self).__name__


class NullWindowController(WindowController):
    """Does nothing, and says so."""

    supported = False

    def __init__(self) -> None:
        self._hwnd = 0
        self._warned = False

    def _unsupported(self, what: str) -> bool:
        if not self._warned:
            logger.info("Native window control is not available on this platform (%s).", what)
            self._warned = True
        return False

    def attach(self, hwnd: int) -> bool:
        self._hwnd = hwnd
        return False

    def detach(self) -> None:
        self._hwnd = 0

    def set_click_through(self, enabled: bool) -> bool:
        return self._unsupported("click-through")

    def set_tool_window(self, enabled: bool) -> bool:
        return self._unsupported("tool window")

    def set_no_activate(self, enabled: bool) -> bool:
        return self._unsupported("no-activate")

    def set_topmost(self, enabled: bool) -> bool:
        return self._unsupported("always-on-top")

    def reassert_topmost(self) -> bool:
        return False

    def set_excluded_from_capture(self, enabled: bool) -> bool:
        return self._unsupported("capture exclusion")

    def is_click_through(self) -> bool | None:
        return None


HotkeyCallback = Callable[[str], None]


class HotkeyManager(abc.ABC):
    """Registers system-wide hotkeys and reports which action fired."""

    supported: bool = False

    @abc.abstractmethod
    def start(self, callback: HotkeyCallback) -> bool:
        """Begin listening. ``callback`` receives the action name."""

    @abc.abstractmethod
    def stop(self) -> None:
        """Unregister everything and stop listening."""

    @abc.abstractmethod
    def apply(self, bindings: dict[str, str]) -> dict[str, str]:
        """Register ``{action: "Ctrl+Alt+M"}``.

        Returns ``{action: reason}`` for every binding that could *not* be
        registered — usually because another application owns that
        combination. The UI shows these so the user can pick another.
        """

    @abc.abstractmethod
    def registered_actions(self) -> list[str]:
        """Actions currently bound to a working hotkey."""


class NullHotkeyManager(HotkeyManager):
    """No global hotkeys; every binding is reported as unsupported."""

    supported = False

    def start(self, callback: HotkeyCallback) -> bool:
        logger.info("Global hotkeys are not available on this platform.")
        return False

    def stop(self) -> None:
        return None

    def apply(self, bindings: dict[str, str]) -> dict[str, str]:
        return {
            action: "Global hotkeys are only supported on Windows."
            for action, combo in bindings.items()
            if combo
        }

    def registered_actions(self) -> list[str]:
        return []
