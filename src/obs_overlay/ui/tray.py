"""System tray icon.

With the overlay click-through and hidden from the taskbar, the tray is the
only permanent handle on the application, so it carries a full menu rather
than just a quit item — including the panic action, in case a layout leaves
the user unable to reach anything.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from ..constants import APP_NAME, APP_VERSION
from ..sources.base import SourceInfo, SourceState
from .icons import tray_icon

logger = logging.getLogger(__name__)

_STATE_LABELS = {
    SourceState.CONNECTED: "connected",
    SourceState.CONNECTING: "waiting for sender",
    SourceState.ERROR: "error",
    SourceState.IDLE: "idle",
    SourceState.CLOSED: "stopped",
}


class TrayIcon(QSystemTrayIcon):
    """Tray presence and menu."""

    panelRequested = pyqtSignal()
    editModeRequested = pyqtSignal()
    overlayToggled = pyqtSignal(bool)
    clickThroughToggled = pyqtSignal(bool)
    reconnectRequested = pyqtSignal()
    panicRequested = pyqtSignal()
    quitRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = SourceState.IDLE
        self.setIcon(tray_icon("idle"))
        self.setToolTip(APP_NAME)

        menu = QMenu()

        self._panel_action = QAction("Control panel…", menu)
        self._panel_action.triggered.connect(self.panelRequested.emit)
        menu.addAction(self._panel_action)

        self._edit_action = QAction("Edit layout", menu)
        self._edit_action.triggered.connect(self.editModeRequested.emit)
        menu.addAction(self._edit_action)

        menu.addSeparator()

        self._overlay_action = QAction("Show overlay", menu)
        self._overlay_action.setCheckable(True)
        self._overlay_action.setChecked(True)
        self._overlay_action.toggled.connect(self.overlayToggled.emit)
        menu.addAction(self._overlay_action)

        self._click_through_action = QAction("Click through", menu)
        self._click_through_action.setCheckable(True)
        self._click_through_action.setChecked(True)
        self._click_through_action.toggled.connect(self.clickThroughToggled.emit)
        menu.addAction(self._click_through_action)

        menu.addSeparator()

        reconnect = QAction("Reconnect to sender", menu)
        reconnect.triggered.connect(self.reconnectRequested.emit)
        menu.addAction(reconnect)

        panic = QAction("Panic — restore input", menu)
        panic.setToolTip("Turns off click-through, shows the overlay and opens the control panel.")
        panic.triggered.connect(self.panicRequested.emit)
        menu.addAction(panic)

        menu.addSeparator()

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quitRequested.emit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)
        self._menu = menu
        self.activated.connect(self._on_activated)

    # -- state -------------------------------------------------------------
    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.panelRequested.emit()

    def set_source_info(self, info: SourceInfo) -> None:
        if info.state is not self._state:
            self._state = info.state
            key = {
                SourceState.CONNECTED: "connected",
                SourceState.CONNECTING: "connecting",
                SourceState.ERROR: "error",
            }.get(info.state, "idle")
            self.setIcon(tray_icon(key))

        label = _STATE_LABELS.get(info.state, "idle")
        detail = f"{info.name} · {info.resolution}" if info.name else ""
        tooltip = f"{APP_NAME} {APP_VERSION}\n{label}"
        if detail:
            tooltip += f"\n{detail}"
        if info.detail:
            tooltip += f"\n{info.detail}"
        self.setToolTip(tooltip)

    def set_overlay_visible(self, visible: bool) -> None:
        blocked = self._overlay_action.blockSignals(True)
        self._overlay_action.setChecked(visible)
        self._overlay_action.blockSignals(blocked)

    def set_click_through(self, enabled: bool) -> None:
        blocked = self._click_through_action.blockSignals(True)
        self._click_through_action.setChecked(enabled)
        self._click_through_action.blockSignals(blocked)

    def set_edit_mode(self, active: bool) -> None:
        self._edit_action.setText("Finish editing" if active else "Edit layout")

    def notify(self, title: str, message: str, warning: bool = False) -> None:
        """Show a balloon, when the platform supports one."""
        if not self.supportsMessages():
            logger.info("%s: %s", title, message)
            return
        icon = (
            QSystemTrayIcon.MessageIcon.Warning
            if warning
            else QSystemTrayIcon.MessageIcon.Information
        )
        self.showMessage(title, message, icon, 6000)
