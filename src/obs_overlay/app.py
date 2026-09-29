"""Application wiring.

:class:`OverlayApplication` owns the pieces and connects them; it holds no
logic of its own beyond the lifecycle. Everything that can be reasoned about
in isolation — geometry, masking, configuration, the frame pipeline — lives in
the modules it composes.

Persistence is debounced: dragging a parcel emits a change on every mouse move,
and writing the profile to disk sixty times a second would be absurd, so saves
coalesce into one write a second after the user stops.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from .config.models import AppSettings, Profile, SourceKind
from .config.store import ConfigStore, ProfileStoreError
from .constants import APP_NAME, APP_VERSION, ORG_NAME
from .core import geometry as geo
from .core.frame import Frame
from .core.producer import FrameProducer
from .native import create_hotkey_manager, create_window_controller
from .sources.base import SourceInfo
from .ui.control_panel import (
    SECTION_BEHAVIOR,
    SECTION_DISPLAY,
    SECTION_EDITOR,
    SECTION_HOTKEYS,
    SECTION_HUD,
    SECTION_PARCELS,
    SECTION_SOURCE,
    ControlPanel,
)
from .ui.icons import app_icon
from .ui.overlay_window import OverlayWindow
from .ui.theme import stylesheet
from .ui.tray import TrayIcon

logger = logging.getLogger(__name__)

#: How long after the last change a profile is written to disk.
_SAVE_DEBOUNCE_MS = 1000
#: How often the HUD and the panel's live readouts are refreshed.
_STATS_INTERVAL_MS = 250


class OverlayApplication(QObject):
    """Owns the overlay, the panel, the tray, the producer and the hotkeys."""

    def __init__(
        self,
        app: QApplication,
        store: ConfigStore | None = None,
        profile_name: str | None = None,
    ) -> None:
        super().__init__()
        self._app = app
        self._store = store or ConfigStore()
        self._store.bootstrap()

        self._settings: AppSettings = self._store.load_settings()
        if profile_name:
            self._settings.active_profile = profile_name
        self._profile: Profile = self._store.load_profile(self._settings.active_profile)
        logger.info("Loaded profile %r", self._profile.name)

        # -- windows -------------------------------------------------------
        self._controller = create_window_controller()
        self.overlay = OverlayWindow(self._profile, self._controller)
        self.panel = ControlPanel(self._profile, self._settings, self._store)
        self.tray = TrayIcon()

        # -- frame pipeline ------------------------------------------------
        self.producer = FrameProducer(self._profile.source)

        # -- hotkeys -------------------------------------------------------
        self._hotkeys = create_hotkey_manager()

        # -- timers --------------------------------------------------------
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(_SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self._save_profile_now)

        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(_STATS_INTERVAL_MS)
        self._stats_timer.timeout.connect(self._push_stats)

        self._shutting_down = False
        self._connect()

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------
    def _connect(self) -> None:
        # These are emitted from the producer thread. Auto-connection already
        # queues a signal whose receiver lives in another thread, so the slots
        # run on the GUI thread without asking for it explicitly.
        self.producer.frameAvailable.connect(self._on_frame_available)
        self.producer.statusChanged.connect(self._on_source_status)
        self.producer.failed.connect(self._on_source_failed)

        self.overlay.layoutChanged.connect(self._on_layout_changed)
        self.overlay.editModeChanged.connect(self._on_edit_mode_changed)
        self.overlay.panelRequested.connect(self.show_panel)
        self.overlay.quitRequested.connect(self.quit)
        self.overlay.editor.selectionChanged.connect(self._on_editor_selection)

        self.panel.profileEdited.connect(self._on_profile_edited)
        self.panel.profileSwitched.connect(self.switch_profile)
        self.panel.editModeRequested.connect(self.set_edit_mode)
        self.panel.reconnectRequested.connect(self.reconnect)
        self.panel.quitRequested.connect(self.quit)
        self.panel.parcelSelectionChanged.connect(self._on_panel_selection)

        self.tray.panelRequested.connect(self.toggle_panel)
        self.tray.editModeRequested.connect(lambda: self.set_edit_mode(not self.overlay.edit_mode))
        self.tray.overlayToggled.connect(self.set_overlay_visible)
        self.tray.clickThroughToggled.connect(self.set_click_through)
        self.tray.reconnectRequested.connect(self.reconnect)
        self.tray.panicRequested.connect(self.panic)
        self.tray.quitRequested.connect(self.quit)

        self._app.aboutToQuit.connect(self._teardown)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Show everything and start pumping frames."""
        self.overlay.apply_profile(self._profile)
        self.overlay.setVisible(self._profile.behavior.overlay_visible)

        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        else:
            logger.warning("No system tray available; the control panel will stay open.")

        self._hotkeys.start(self._on_hotkey)
        self._apply_hotkeys()

        self.producer.start()
        self._stats_timer.start()

        if (
            self._profile.behavior.show_panel_on_start
            or not QSystemTrayIcon.isSystemTrayAvailable()
        ):
            self.show_panel()

        self.tray.set_overlay_visible(self.overlay.isVisible())
        self.tray.set_click_through(self._profile.behavior.click_through)
        self._warn_if_unsafe()
        self._guard_screen_capture()

    def quit(self) -> None:
        if self._shutting_down:
            return
        logger.info("Shutting down.")
        self._shutting_down = True
        self._app.quit()

    def _teardown(self) -> None:
        self._stats_timer.stop()
        self._save_timer.stop()
        try:
            self._save_profile_now()
            self._settings.active_profile = self._profile.name
            self._store.save_settings(self._settings)
        except ProfileStoreError as exc:
            logger.error("Could not save on exit: %s", exc)

        self._hotkeys.stop()
        self.producer.stop()
        self.overlay.clear_frame()
        self.tray.hide()

    # ------------------------------------------------------------------
    # Frames and status
    # ------------------------------------------------------------------
    def _on_frame_available(self) -> None:
        frame: Frame | None = self.producer.take_frame()
        if frame is None:
            return
        self.overlay.set_frame(frame)
        self.producer.stats.record_paint()

    def _on_source_status(self, info: SourceInfo) -> None:
        self.overlay.set_source_info(info)
        self.tray.set_source_info(info)
        self.panel.set_status(info, self.producer.stats_snapshot())

    def _on_source_failed(self, message: str) -> None:
        logger.error("Source failure: %s", message)
        self.tray.notify("OBS Overlay", message, warning=True)

    def _push_stats(self) -> None:
        stats = self.producer.stats_snapshot()
        self.overlay.set_stats(stats)
        self.panel.set_status(self.overlay._source_info, stats)

    # ------------------------------------------------------------------
    # Profile changes
    # ------------------------------------------------------------------
    def _on_profile_edited(self, section: str) -> None:
        logger.debug("Profile section %r edited", section)

        if section == SECTION_SOURCE:
            self.producer.apply_settings(self._profile.source)
            self._guard_screen_capture()
        elif section == SECTION_DISPLAY:
            self.overlay.apply_geometry()
            self.overlay.invalidate_mask()
            self.overlay.update()
            self._guard_screen_capture()
        elif section == SECTION_BEHAVIOR:
            self.overlay.refresh_mask()
            self.overlay.apply_behavior()
            self.overlay.setVisible(self._profile.behavior.overlay_visible)
            self.tray.set_click_through(self._profile.behavior.click_through)
            self.tray.set_overlay_visible(self.overlay.isVisible())
            self._warn_if_unsafe()
        elif section == SECTION_PARCELS:
            self.overlay.invalidate_mask()
            self.overlay.update()
            self._warn_if_unsafe()
        elif section == SECTION_HOTKEYS:
            self._apply_hotkeys()
        elif section in (SECTION_EDITOR, SECTION_HUD):
            self.overlay.update()

        self._schedule_save()

    def _on_layout_changed(self) -> None:
        """A drag on the overlay changed the parcels."""
        self.panel.refresh_parcels(self.overlay.editor.selection)
        self._schedule_save()

    def _on_editor_selection(self) -> None:
        self.panel._table.set_selected_ids(self.overlay.editor.selection)

    def _on_panel_selection(self, ids: list[str]) -> None:
        if self.overlay.edit_mode:
            self.overlay.editor.set_selection(ids)
            self.overlay.update()

    def _schedule_save(self) -> None:
        self._save_timer.start()

    def _save_profile_now(self) -> None:
        try:
            self._store.save_profile(self._profile)
        except ProfileStoreError as exc:
            logger.error("Could not save profile %r: %s", self._profile.name, exc)
            self.tray.notify("OBS Overlay", f"Could not save settings: {exc}", warning=True)

    def switch_profile(self, name: str) -> None:
        if name == self._profile.name:
            return
        logger.info("Switching profile %r -> %r", self._profile.name, name)
        self._save_profile_now()

        try:
            profile = self._store.load_profile(name)
        except ProfileStoreError as exc:
            logger.error("Could not load profile %r: %s", name, exc)
            self.tray.notify("OBS Overlay", str(exc), warning=True)
            return

        self._profile = profile
        self._settings.active_profile = profile.name

        self.overlay.apply_profile(profile)
        self.overlay.setVisible(profile.behavior.overlay_visible)
        self.panel.load_profile(profile)
        self.producer.apply_settings(profile.source)
        self._apply_hotkeys()
        self.tray.set_click_through(profile.behavior.click_through)
        self.tray.set_overlay_visible(self.overlay.isVisible())

        try:
            self._store.save_settings(self._settings)
        except ProfileStoreError as exc:  # pragma: no cover
            logger.error("Could not record the active profile: %s", exc)

    def reload_profile(self) -> None:
        """Re-read the active profile from disk, discarding unsaved edits."""
        name = self._profile.name
        self._profile = self._store.load_profile(name)
        self.overlay.apply_profile(self._profile)
        self.panel.load_profile(self._profile)
        self.producer.apply_settings(self._profile.source)
        self._apply_hotkeys()
        logger.info("Reloaded profile %r from disk", name)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    def show_panel(self) -> None:
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()

    def toggle_panel(self) -> None:
        if self.panel.isVisible() and self.panel.isActiveWindow():
            self.panel.hide()
        else:
            self.show_panel()

    def set_edit_mode(self, enabled: bool) -> None:
        self.overlay.set_edit_mode(enabled)

    def _on_edit_mode_changed(self, active: bool) -> None:
        self.panel.set_edit_mode(active)
        self.tray.set_edit_mode(active)
        if active:
            # The overlay must be visible to be edited.
            if not self.overlay.isVisible():
                self.set_overlay_visible(True)
            self.panel.refresh_parcels(self.overlay.editor.selection)

    def set_overlay_visible(self, visible: bool) -> None:
        self._profile.behavior.overlay_visible = visible
        self.overlay.setVisible(visible)
        if visible:
            self.overlay.apply_behavior()
        self.tray.set_overlay_visible(visible)
        self._schedule_save()

    def set_click_through(self, enabled: bool) -> None:
        self._profile.behavior.click_through = enabled
        self.overlay.apply_behavior()
        self.tray.set_click_through(enabled)
        self.panel.load_profile(self._profile)
        self._schedule_save()

    def reconnect(self) -> None:
        logger.info("Reconnect requested.")
        self.producer.request_reconnect()

    def panic(self) -> None:
        """Get the user out of any state they cannot click their way out of."""
        logger.warning("Panic requested; restoring input.")
        self._profile.behavior.click_through = True
        self._profile.behavior.overlay_visible = True
        self.overlay.set_edit_mode(False)
        self.overlay.apply_behavior()
        self.overlay.setVisible(True)
        self.tray.set_click_through(True)
        self.tray.set_overlay_visible(True)
        self.panel.load_profile(self._profile)
        self.show_panel()
        self._schedule_save()

    # ------------------------------------------------------------------
    # Hotkeys
    # ------------------------------------------------------------------
    def _apply_hotkeys(self) -> None:
        failures: dict[str, str] = self._hotkeys.apply(self._profile.hotkeys.as_mapping())
        self.panel.set_hotkey_failures(failures)
        if failures:
            logger.warning("Hotkeys unavailable: %s", ", ".join(sorted(failures)))

    def _on_hotkey(self, action: str) -> None:
        logger.debug("Hotkey fired: %s", action)
        handlers = {
            "toggle_editor": lambda: self.set_edit_mode(not self.overlay.edit_mode),
            "toggle_click_through": lambda: self.set_click_through(
                not self._profile.behavior.click_through
            ),
            "toggle_overlay": lambda: self.set_overlay_visible(not self.overlay.isVisible()),
            "toggle_panel": self.toggle_panel,
            "reload_profile": self.reload_profile,
            "panic": self.panic,
        }
        handler = handlers.get(action)
        if handler is None:
            logger.warning("No handler for hotkey action %r", action)
            return
        handler()

    # ------------------------------------------------------------------
    # Screen-capture feedback
    # ------------------------------------------------------------------
    def captured_area(self) -> geo.RectSpec | None:
        """The area the screen source captures, in virtual-desktop coordinates.

        ``None`` when the active source is not capturing the desktop.
        """
        if self._profile.source.kind is not SourceKind.SCREEN:
            return None

        from .sources.screen_source import ScreenSource

        screen = self._profile.source.screen
        probe = ScreenSource(
            monitor_index=screen.monitor_index,
            region=screen.region if screen.use_region else None,
        )
        rect = probe.captured_rect()
        return rect if rect.width > 0 and rect.height > 0 else None

    def _guard_screen_capture(self) -> None:
        """Stop the overlay photographing itself.

        Capturing the display the overlay sits on feeds the overlay back into
        its own input, which recurses into an infinite tunnel within a few
        frames. Windows can exclude a window from capture outright, so when the
        two areas overlap that is switched on rather than leaving the user to
        discover the problem visually.
        """
        area = self.captured_area()
        if area is None or not self._profile.source.screen.avoid_self_capture:
            return

        overlay_rect = self.overlay.geometry()
        overlay = geo.RectSpec(
            overlay_rect.x(), overlay_rect.y(), overlay_rect.width(), overlay_rect.height()
        )
        if not geo.intersects(area, overlay):
            return

        if self._profile.behavior.exclude_from_capture:
            return

        logger.info("Screen capture overlaps the overlay; enabling capture exclusion.")
        self._profile.behavior.exclude_from_capture = True
        applied = self.overlay.apply_behavior()
        self.panel.load_profile(self._profile)

        if applied:
            self.tray.notify(
                "OBS Overlay",
                "The overlay is inside the captured area, so it was hidden from "
                "screen capture to stop it feeding back into itself.",
            )
        else:
            self.tray.notify(
                "OBS Overlay",
                "The overlay is inside the captured area and will photograph "
                "itself. Capture exclusion is unavailable on this system — "
                "capture a different monitor or a region that excludes the "
                "overlay.",
                warning=True,
            )

    # ------------------------------------------------------------------
    # Safety
    # ------------------------------------------------------------------
    def _warn_if_unsafe(self) -> None:
        """Catch a layout that would leave the user unable to click anything."""
        if not self._profile.behavior.safety_guard:
            return
        canvas = geo.RectSpec(0, 0, self.overlay.width(), self.overlay.height())
        if not geo.is_unsafe_layout(
            self._profile.parcels,
            canvas,
            self._profile.behavior.click_through,
            self._profile.display.opacity,
        ):
            return

        logger.warning("Unsafe layout detected; re-enabling click-through.")
        self._profile.behavior.click_through = True
        self.overlay.apply_behavior()
        self.tray.set_click_through(True)
        self.tray.notify(
            "OBS Overlay",
            "This layout covers almost the whole screen. Click-through was turned "
            "back on so you can still use your desktop. Turn it off again in the "
            "Behaviour tab if that is what you meant.",
            warning=True,
        )


def create_application(argv: list[str] | None = None) -> QApplication:
    """Create the ``QApplication`` with the attributes this app needs."""
    app = QApplication(argv if argv is not None else [])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORG_NAME)
    app.setWindowIcon(app_icon())
    app.setStyleSheet(stylesheet())
    # The overlay and the panel are separate top-levels; closing the panel must
    # not end the process.
    app.setQuitOnLastWindowClosed(False)
    return app
