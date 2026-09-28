"""Windows implementation of :class:`~obs_overlay.native.base.WindowController`.

What this touches, and what it deliberately does not
----------------------------------------------------
Qt already owns ``WS_EX_LAYERED`` on a translucent frameless window: its
Windows backing store flushes frames with ``UpdateLayeredWindowIndirect`` and
``ULW_ALPHA``, which is what gives true per-pixel alpha. So this module:

* only ever flips the three bits it owns — ``WS_EX_TRANSPARENT``,
  ``WS_EX_TOOLWINDOW`` and ``WS_EX_NOACTIVATE`` — with a read-modify-write, and
  never clears ``WS_EX_LAYERED``;
* never calls ``SetLayeredWindowAttributes``. Windows documents that once it
  has been called on a window, subsequent ``UpdateLayeredWindow`` calls fail
  until the layered style is cleared and re-set — it would silently break Qt's
  alpha compositing.

Runtime toggling goes through ``SetWindowLongW`` rather than
``QWidget.setWindowFlags``, because the Qt call internally re-parents and hides
the widget, which makes the overlay blink.

``pywin32`` is used where it covers the API and ``ctypes`` where it does not
(``SetWindowDisplayAffinity``); if ``pywin32`` is missing entirely, everything
falls back to ``ctypes`` so the overlay degrades rather than dies.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

from .base import WindowController

logger = logging.getLogger(__name__)

#: WDA_EXCLUDEFROMCAPTURE needs Windows 10 version 2004 (build 19041). On
#: earlier builds Windows silently downgrades it to WDA_MONITOR, which makes
#: the overlay a solid black rectangle in every capture — strictly worse than
#: doing nothing, so the call is gated rather than attempted.
_MIN_BUILD_EXCLUDE_FROM_CAPTURE = 19041

# -- Win32 constants --------------------------------------------------------
GWL_EXSTYLE = -20

WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_APPWINDOW = 0x00040000

HWND_TOPMOST = -1
HWND_NOTOPMOST = -2

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
SWP_NOOWNERZORDER = 0x0200

#: SetWindowDisplayAffinity values. EXCLUDEFROMCAPTURE needs Windows 10 2004+;
#: on older builds the call fails and we report it instead of pretending.
WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011


def _load_user32() -> ctypes.WinDLL:
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    return user32


class Win32WindowController(WindowController):
    """Real window control on Windows."""

    supported = True

    def __init__(self) -> None:
        self._hwnd = 0
        self._user32 = _load_user32()
        self._capture_exclusion_warned = False

    # -- attachment --------------------------------------------------------
    def attach(self, hwnd: int) -> bool:
        hwnd = int(hwnd)
        if hwnd <= 0:
            logger.error("Refusing to attach to an invalid window handle (%r).", hwnd)
            self._hwnd = 0
            return False
        if not self._user32.IsWindow(wintypes.HWND(hwnd)):
            logger.error("Window handle %d does not refer to a live window.", hwnd)
            self._hwnd = 0
            return False
        self._hwnd = hwnd
        logger.debug("Attached to HWND %d", hwnd)
        return True

    def detach(self) -> None:
        self._hwnd = 0

    @property
    def hwnd(self) -> int:
        return self._hwnd

    def _valid(self) -> bool:
        if not self._hwnd:
            return False
        if not self._user32.IsWindow(wintypes.HWND(self._hwnd)):
            logger.debug("HWND %d is gone; detaching.", self._hwnd)
            self._hwnd = 0
            return False
        return True

    # -- extended style ----------------------------------------------------
    def _get_ex_style(self) -> int | None:
        if not self._valid():
            return None
        ctypes.set_last_error(0)
        value = self._user32.GetWindowLongW(wintypes.HWND(self._hwnd), GWL_EXSTYLE)
        if value == 0:
            error = ctypes.get_last_error()
            if error:
                logger.error("GetWindowLongW failed: %s", ctypes.WinError(error))
                return None
        # GetWindowLongW returns a signed LONG; the style is an unsigned
        # bitmask, so reinterpret it before any bitwise work.
        return value & 0xFFFFFFFF

    def _set_ex_style(self, style: int) -> bool:
        if not self._valid():
            return False
        # Back to signed for the API call.
        signed = ctypes.c_long(style - 0x100000000 if style >= 0x80000000 else style)
        ctypes.set_last_error(0)
        result = self._user32.SetWindowLongW(wintypes.HWND(self._hwnd), GWL_EXSTYLE, signed)
        if result == 0:
            error = ctypes.get_last_error()
            if error:
                logger.error("SetWindowLongW failed: %s", ctypes.WinError(error))
                return False
        return True

    def _flush_style_change(self) -> None:
        """Make a GWL_EXSTYLE change take effect.

        Windows caches window frame data; MSDN requires a ``SetWindowPos`` with
        ``SWP_FRAMECHANGED`` for the cache to be refreshed. ``SWP_NOZORDER``
        keeps the current Z order (unlike :meth:`set_topmost`, which must omit
        it), and ``SWP_NOACTIVATE`` stops the call itself stealing focus.
        """
        if not self._hwnd:
            return
        self._user32.SetWindowPos(
            wintypes.HWND(self._hwnd),
            wintypes.HWND(0),
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )

    def _update_ex_style(self, bits: int, enabled: bool, what: str) -> bool:
        """Read-modify-write a single style bit, leaving every other bit alone."""
        current = self._get_ex_style()
        if current is None:
            return False
        updated = (current | bits) if enabled else (current & ~bits)
        if updated == current:
            return True
        if not self._set_ex_style(updated):
            return False
        self._flush_style_change()
        logger.debug("%s -> %s (ex-style 0x%08X)", what, enabled, updated)
        return True

    # -- behaviours --------------------------------------------------------
    def set_click_through(self, enabled: bool) -> bool:
        """WS_EX_TRANSPARENT makes the window ignore every mouse message.

        WS_EX_LAYERED is intentionally not touched: Qt sets it for the
        translucent window and clearing it would kill per-pixel alpha.
        """
        return self._update_ex_style(WS_EX_TRANSPARENT, enabled, "click-through")

    def set_tool_window(self, enabled: bool) -> bool:
        """A tool window stays out of the taskbar *and* the Alt-Tab list.

        ``WS_EX_NOACTIVATE`` alone only removes the taskbar button;
        ``WS_EX_TOOLWINDOW`` is the flag that removes the Alt-Tab entry too.
        ``WS_EX_APPWINDOW`` is always cleared because it overrides both — any
        Qt flag change or tray helper that ORs it back in would make the
        overlay reappear in the taskbar.
        """
        current = self._get_ex_style()
        if current is None:
            return False
        updated = (current | WS_EX_TOOLWINDOW) if enabled else (current & ~WS_EX_TOOLWINDOW)
        updated &= ~WS_EX_APPWINDOW
        if updated == current:
            return True
        if not self._set_ex_style(updated):
            return False
        self._flush_style_change()
        logger.debug("tool window -> %s (ex-style 0x%08X)", enabled, updated)
        return True

    def set_no_activate(self, enabled: bool) -> bool:
        """Stop the overlay stealing focus from the game or app underneath."""
        return self._update_ex_style(WS_EX_NOACTIVATE, enabled, "no-activate")

    def set_topmost(self, enabled: bool) -> bool:
        """Move the window into or out of the always-on-top Z-order band.

        ``SWP_NOZORDER`` must *not* be set here: MSDN only honours
        ``HWND_TOPMOST`` when the Z order is allowed to change.
        """
        if not self._valid():
            return False
        insert_after = HWND_TOPMOST if enabled else HWND_NOTOPMOST
        ok = bool(
            self._user32.SetWindowPos(
                wintypes.HWND(self._hwnd),
                wintypes.HWND(insert_after),
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER,
            )
        )
        if not ok:
            logger.error("SetWindowPos(topmost=%s) failed: %s", enabled, ctypes.WinError())
        return ok

    def reassert_topmost(self) -> bool:
        """Re-apply topmost.

        A fullscreen application entering exclusive mode can push every other
        window out of the topmost band. There is no event for it, so the app
        calls this on a timer.
        """
        return self.set_topmost(True)

    def set_excluded_from_capture(self, enabled: bool) -> bool:
        """Hide the overlay from screen capture.

        Useful when OBS captures the same display the overlay is on: without
        it you get the overlay feeding back into the scene it came from.
        Requires Windows 10 version 2004 or newer.
        """
        if not self._valid():
            return False
        if enabled and not self.capture_exclusion_supported():
            if not self._capture_exclusion_warned:
                logger.warning(
                    "Capture exclusion needs Windows 10 version 2004 (build %d) or newer. "
                    "On older builds Windows would draw the overlay as a solid black "
                    "rectangle in captures, so the request is ignored.",
                    _MIN_BUILD_EXCLUDE_FROM_CAPTURE,
                )
                self._capture_exclusion_warned = True
            return False

        affinity = WDA_EXCLUDEFROMCAPTURE if enabled else WDA_NONE
        ok = bool(self._user32.SetWindowDisplayAffinity(wintypes.HWND(self._hwnd), affinity))
        if not ok and not self._capture_exclusion_warned:
            logger.warning("SetWindowDisplayAffinity failed: %s", ctypes.WinError())
            self._capture_exclusion_warned = True
        return ok

    @staticmethod
    def capture_exclusion_supported() -> bool:
        """Whether this Windows build honours WDA_EXCLUDEFROMCAPTURE."""
        version = getattr(sys, "getwindowsversion", None)
        if version is None:  # pragma: no cover - not Windows
            return False
        try:
            return version().build >= _MIN_BUILD_EXCLUDE_FROM_CAPTURE
        except Exception:  # pragma: no cover - defensive
            return False

    def is_click_through(self) -> bool | None:
        style = self._get_ex_style()
        if style is None:
            return None
        return bool(style & WS_EX_TRANSPARENT)

    def is_layered(self) -> bool | None:
        """Whether Qt gave the window the layered style (per-pixel alpha)."""
        style = self._get_ex_style()
        if style is None:
            return None
        return bool(style & WS_EX_LAYERED)

    def describe(self) -> str:
        style = self._get_ex_style()
        if style is None:
            return "Win32WindowController(detached)"
        flags = []
        for name, bit in (
            ("LAYERED", WS_EX_LAYERED),
            ("TRANSPARENT", WS_EX_TRANSPARENT),
            ("TOOLWINDOW", WS_EX_TOOLWINDOW),
            ("NOACTIVATE", WS_EX_NOACTIVATE),
        ):
            if style & bit:
                flags.append(name)
        return f"Win32WindowController(hwnd={self._hwnd}, {'|'.join(flags) or 'none'})"
