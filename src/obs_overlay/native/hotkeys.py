"""System-wide hotkeys on Windows.

Registration is *thread-scoped*: ``RegisterHotKey`` is called with a ``NULL``
window handle, so ``WM_HOTKEY`` is posted to the calling thread's message queue
rather than to a particular window. That matters because Qt destroys and
recreates the native window on several innocuous operations (``setWindowFlags``,
``setParent``, some screen changes) — an HWND-bound hotkey would silently stop
working after any of them.

Qt's Windows event dispatcher drains the thread queue with ``PeekMessage`` and
hands each message to every installed ``QAbstractNativeEventFilter`` under the
event type ``windows_generic_MSG``, which is how the messages get back here.

Registration can legitimately fail — another application may already own the
combination — so :meth:`Win32HotkeyManager.apply` reports per-binding failures
instead of raising; the control panel shows them next to the offending row.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

from PyQt6.QtCore import QAbstractNativeEventFilter, QCoreApplication

from .base import HotkeyCallback, HotkeyManager
from .hotkey_spec import HotkeyParseError, parse_hotkey

logger = logging.getLogger(__name__)

WM_HOTKEY = 0x0312

#: Application hotkey ids must be in 0x0000-0xBFFF. Starting high keeps us
#: clear of anything a bundled library might register from the same thread.
_FIRST_HOTKEY_ID = 0xB000
_LAST_HOTKEY_ID = 0xBFFF

ERROR_HOTKEY_ALREADY_REGISTERED = 1409

#: MSDN: "The F12 key is reserved for use by the debugger at all times."
_VK_F12 = 0x7B

_EVENT_TYPES = (b"windows_generic_MSG", b"windows_dispatcher_MSG")


class _HotkeyEventFilter(QAbstractNativeEventFilter):
    """Turns ``WM_HOTKEY`` thread messages back into action names."""

    def __init__(self, manager: Win32HotkeyManager) -> None:
        super().__init__()
        self._manager = manager

    def nativeEventFilter(self, event_type, message):  # type: ignore[override]
        # An exception escaping a virtual called from C++ can abort the
        # process, so nothing in here is allowed to raise.
        try:
            if bytes(event_type) not in _EVENT_TYPES:
                return False, 0
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self._manager._dispatch(int(msg.wParam))
                return True, 0
        except Exception:  # pragma: no cover - defensive
            logger.exception("Hotkey event filter failed.")
        return False, 0


class Win32HotkeyManager(HotkeyManager):
    """Registers global hotkeys and routes them to a callback."""

    supported = True

    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.RegisterHotKey.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self._user32.RegisterHotKey.restype = wintypes.BOOL
        self._user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.UnregisterHotKey.restype = wintypes.BOOL

        self._filter: _HotkeyEventFilter | None = None
        self._callback: HotkeyCallback | None = None
        self._by_id: dict[int, str] = {}
        self._by_action: dict[str, int] = {}
        self._next_id = _FIRST_HOTKEY_ID

    # -- lifecycle ---------------------------------------------------------
    def start(self, callback: HotkeyCallback) -> bool:
        self._callback = callback
        if self._filter is not None:
            return True
        app = QCoreApplication.instance()
        if app is None:  # pragma: no cover - programming error
            logger.error("Cannot install the hotkey filter before QApplication exists.")
            return False
        self._filter = _HotkeyEventFilter(self)
        app.installNativeEventFilter(self._filter)
        logger.debug("Hotkey event filter installed.")
        return True

    def stop(self) -> None:
        self._unregister_all()
        self._callback = None
        if self._filter is not None:
            app = QCoreApplication.instance()
            if app is not None:
                app.removeNativeEventFilter(self._filter)
            self._filter = None

    # -- registration ------------------------------------------------------
    def _unregister_all(self) -> None:
        for hotkey_id in list(self._by_id):
            self._user32.UnregisterHotKey(wintypes.HWND(0), hotkey_id)
        self._by_id.clear()
        self._by_action.clear()

    def _allocate_id(self) -> int:
        hotkey_id = self._next_id
        self._next_id += 1
        if self._next_id > _LAST_HOTKEY_ID:  # pragma: no cover - absurd usage
            self._next_id = _FIRST_HOTKEY_ID
        return hotkey_id

    def apply(self, bindings: dict[str, str]) -> dict[str, str]:
        """Replace every registration with ``bindings``.

        Everything is unregistered first so that re-applying after an edit
        cannot leave an orphaned hotkey behind holding a combination hostage.
        """
        failures: dict[str, str] = {}
        wanted = {action: combo for action, combo in bindings.items() if combo and combo.strip()}

        if self._filter is None and not self.start(self._callback or (lambda _a: None)):
            return dict.fromkeys(wanted, "Hotkey listener could not be installed.")

        self._unregister_all()

        for action, combo in wanted.items():
            try:
                spec = parse_hotkey(combo)
            except HotkeyParseError as exc:
                failures[action] = str(exc)
                continue

            if spec.vk == _VK_F12:
                failures[action] = "F12 is reserved by Windows for the debugger; pick another key."
                continue

            hotkey_id = self._allocate_id()
            ctypes.set_last_error(0)
            ok = self._user32.RegisterHotKey(
                wintypes.HWND(0),
                hotkey_id,
                spec.modifiers_with_norepeat,
                spec.vk,
            )
            if not ok:
                error = ctypes.get_last_error()
                if error == ERROR_HOTKEY_ALREADY_REGISTERED:
                    reason = f"{spec.text} is already used by another application."
                else:
                    detail = ctypes.WinError(error).strerror if error else "unknown error"
                    reason = f"{spec.text} could not be registered ({detail})."
                logger.warning("Hotkey %s for %s failed: %s", spec.text, action, reason)
                failures[action] = reason
                continue

            self._by_id[hotkey_id] = action
            self._by_action[action] = hotkey_id
            logger.info("Registered global hotkey %s -> %s", spec.text, action)

        return failures

    def registered_actions(self) -> list[str]:
        return sorted(self._by_action)

    # -- dispatch ----------------------------------------------------------
    def _dispatch(self, hotkey_id: int) -> None:
        action = self._by_id.get(hotkey_id)
        if action is None:
            return
        callback = self._callback
        if callback is None:
            return
        try:
            callback(action)
        except Exception:  # pragma: no cover - a UI bug must not kill the hook
            logger.exception("Hotkey handler for %r raised.", action)
