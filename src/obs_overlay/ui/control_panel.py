"""The configuration window.

Hidden by default — the overlay is meant to be invisible chrome — and summoned
with a hotkey or from the tray. It edits the active :class:`Profile` in place
and emits which *section* changed, so the app only redoes the work that
section affects (reopening the source is expensive; repainting is not).

Every widget population goes through :meth:`ControlPanel._load`, guarded by
``_loading``, so programmatic updates never echo back as user edits.
"""

from __future__ import annotations

import contextlib
import logging

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import paths
from ..config.models import (
    Anchor,
    AppSettings,
    FitMode,
    GeometryMode,
    HudCorner,
    Parcel,
    Profile,
    RectSpec,
    ScaleQuality,
    SourceKind,
)
from ..config.store import ConfigStore, ProfileStoreError
from ..constants import APP_NAME, APP_VERSION, MAX_TARGET_FPS, MIN_TARGET_FPS
from ..core import geometry as geo
from ..core.fps import StatsSnapshot
from ..sources.base import SourceInfo, SourceState
from ..sources.registry import (
    available_sender_names,
    ndi_available,
    spout_available,
    unavailable_reason,
)
from . import widgets as W
from .icons import app_icon
from .parcel_table import ParcelTable, apply_edit
from .theme import PALETTE, stylesheet

logger = logging.getLogger(__name__)

EM_DASH = "—"
MIDDLE_DOT = "·"

#: Sections the app can react to independently.
SECTION_SOURCE = "source"
SECTION_DISPLAY = "display"
SECTION_BEHAVIOR = "behavior"
SECTION_EDITOR = "editor"
SECTION_HUD = "hud"
SECTION_PARCELS = "parcels"
SECTION_HOTKEYS = "hotkeys"


class ControlPanel(QWidget):
    """Tabbed settings window for the overlay."""

    profileEdited = pyqtSignal(str)
    profileSwitched = pyqtSignal(str)
    editModeRequested = pyqtSignal(bool)
    reconnectRequested = pyqtSignal()
    quitRequested = pyqtSignal()
    #: Rows selected in the parcel table, mirrored onto the overlay editor.
    parcelSelectionChanged = pyqtSignal(list)

    def __init__(
        self,
        profile: Profile,
        settings: AppSettings,
        store: ConfigStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._profile = profile
        self._settings = settings
        self._store = store
        self._loading = False
        self._hotkey_failures: dict[str, str] = {}

        self.setWindowTitle(f"{APP_NAME} — Control Panel")
        self.setWindowIcon(app_icon())
        self.setStyleSheet(stylesheet())
        self.setMinimumSize(880, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)

        layout.addWidget(self._build_header())

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_source_tab(), "Source")
        self._tabs.addTab(self._build_display_tab(), "Display")
        self._tabs.addTab(self._build_parcels_tab(), "Parcels")
        self._tabs.addTab(self._build_behavior_tab(), "Behaviour")
        self._tabs.addTab(self._build_editor_tab(), "Editor")
        self._tabs.addTab(self._build_hotkeys_tab(), "Hotkeys")
        self._tabs.addTab(self._build_profiles_tab(), "Profiles")
        self._tabs.addTab(self._build_about_tab(), "About")
        layout.addWidget(self._tabs, 1)

        self._status = W.StatusLine("")
        layout.addWidget(self._status)

        # Live readouts refresh on a timer rather than on every frame: at
        # 60 fps a per-frame update would spend more time laying out labels
        # than painting the overlay.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(500)
        self._refresh_timer.timeout.connect(self._refresh_live_readouts)

        self._latest_stats = StatsSnapshot()
        self._latest_info = SourceInfo()

        self.load_profile(profile)

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    def _build_header(self) -> QWidget:
        self._profile_combo = QComboBox()
        self._profile_combo.setMinimumWidth(200)
        self._profile_combo.currentIndexChanged.connect(self._on_profile_selected)

        self._connection_label = QLabel("—")
        self._connection_label.setProperty("role", "hint")

        self._edit_button = W.button(
            "Edit layout", lambda: self.editModeRequested.emit(True), role="primary"
        )
        self._edit_button.setToolTip("Show the parcel editor on the overlay.")

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(W.heading_label(APP_NAME))
        layout.addSpacing(8)
        layout.addWidget(QLabel("Profile:"))
        layout.addWidget(self._profile_combo)
        layout.addWidget(self._connection_label, 1)
        layout.addWidget(self._edit_button)
        return container

    # ------------------------------------------------------------------
    # Source tab
    # ------------------------------------------------------------------
    def _build_source_tab(self) -> QWidget:
        group = QGroupBox("Video source")
        layout = W.form()

        self._source_kind = W.combo(
            (
                ("OBS via Spout2", SourceKind.SPOUT),
                ("NDI (network)", SourceKind.NDI),
                ("Screen capture", SourceKind.SCREEN),
                ("Image file", SourceKind.IMAGE),
                ("Built-in test pattern", SourceKind.DEMO),
            )
        )
        self._source_kind.currentIndexChanged.connect(self._on_source_kind_changed)
        layout.addRow("Source", self._source_kind)

        self._kind_warning = W.hint_label("")
        layout.addRow("", self._kind_warning)

        # Only the active kind's settings are shown, but every kind's values
        # are kept in the profile, so switching back and forth loses nothing.
        self._source_pages = QStackedWidget()
        self._source_page_index: dict[SourceKind, int] = {}
        for kind, builder in (
            (SourceKind.SPOUT, self._build_spout_page),
            (SourceKind.NDI, self._build_ndi_page),
            (SourceKind.SCREEN, self._build_screen_page),
            (SourceKind.IMAGE, self._build_image_page),
            (SourceKind.DEMO, self._build_demo_page),
        ):
            self._source_page_index[kind] = self._source_pages.addWidget(builder())
        layout.addRow(self._source_pages)

        self._target_fps = W.spin(MIN_TARGET_FPS, MAX_TARGET_FPS, 60, suffix=" fps")
        self._target_fps.valueChanged.connect(lambda v: self._edit(SECTION_SOURCE, target_fps=v))
        layout.addRow("Target rate", self._target_fps)

        self._auto_reconnect = W.checkbox("Reconnect automatically")
        self._auto_reconnect.toggled.connect(lambda v: self._edit(SECTION_SOURCE, auto_reconnect=v))
        layout.addRow("", self._auto_reconnect)

        self._fallback_demo = W.checkbox(
            "Fall back to the test pattern when the source is unavailable",
            tooltip="Off by default: during a live stream an empty overlay is safer "
            "than a test pattern appearing unannounced.",
        )
        self._fallback_demo.toggled.connect(
            lambda v: self._edit(SECTION_SOURCE, fallback_to_demo=v)
        )
        layout.addRow("", self._fallback_demo)

        group.setLayout(layout)

        status_group = QGroupBox("Connection")
        status_layout = W.form()
        self._status_state = QLabel("—")
        self._status_resolution = QLabel("—")
        self._status_fps = QLabel("—")
        self._status_frames = QLabel("—")
        self._status_detail = W.hint_label("")
        status_layout.addRow("State", self._status_state)
        status_layout.addRow("Resolution", self._status_resolution)
        status_layout.addRow("Frame rate", self._status_fps)
        status_layout.addRow("Frames", self._status_frames)
        status_layout.addRow("", self._status_detail)
        status_layout.addRow(
            "", W.row(W.button("Reconnect now", lambda: self.reconnectRequested.emit()))
        )
        status_group.setLayout(status_layout)

        return W.column(group, status_group, self._spacer(), margins=4)

    # -- per-kind pages ----------------------------------------------------
    def _build_spout_page(self) -> QWidget:
        layout = W.form()

        self._sender_combo = QComboBox()
        self._sender_combo.setEditable(True)
        self._sender_combo.setMinimumWidth(260)
        sender_edit = self._sender_combo.lineEdit()
        if sender_edit is not None:
            sender_edit.editingFinished.connect(self._on_sender_text_changed)
        self._sender_combo.activated.connect(self._on_sender_text_changed)
        refresh = W.button("Refresh", self.refresh_senders, tooltip="Re-scan for Spout senders.")
        layout.addRow("Sender name", W.row(self._sender_combo, refresh, stretch_last=False))

        self._auto_select = W.checkbox(
            "Use any available sender when the named one is missing",
            tooltip="Leave the name empty to always follow whichever sender OBS makes active.",
        )
        self._auto_select.toggled.connect(lambda v: self._edit_spout(auto_select_sender=v))
        layout.addRow("", self._auto_select)

        self._invert_y = W.checkbox(
            "Flip vertically during receive",
            tooltip="Use this if the feed arrives upside down. Cheaper than flipping "
            "in the Display tab because Spout does it for free.",
        )
        self._invert_y.toggled.connect(lambda v: self._edit_spout(invert_y=v))
        layout.addRow("", self._invert_y)

        self._premultiplied = W.checkbox(
            "Sender uses premultiplied alpha",
            tooltip="Leave this on for the OBS 'Spout Filter', which composites "
            "with premultiplied alpha. Turning it off for such a sender produces "
            "dark fringes around soft edges; leaving it on for a straight-alpha "
            "sender washes them out.",
        )
        self._premultiplied.toggled.connect(lambda v: self._edit_spout(premultiplied_alpha=v))
        layout.addRow("", self._premultiplied)

        return self._page(layout)

    def _build_ndi_page(self) -> QWidget:
        layout = W.form()

        self._ndi_combo = QComboBox()
        self._ndi_combo.setEditable(True)
        self._ndi_combo.setMinimumWidth(280)
        ndi_edit = self._ndi_combo.lineEdit()
        if ndi_edit is not None:
            ndi_edit.editingFinished.connect(self._on_ndi_text_changed)
        self._ndi_combo.activated.connect(self._on_ndi_text_changed)
        refresh = W.button(
            "Scan", self.refresh_ndi_sources, tooltip="Look for NDI sources on the network."
        )
        layout.addRow("NDI source", W.row(self._ndi_combo, refresh, stretch_last=False))

        self._ndi_auto = W.checkbox("Use any available source when the named one is missing")
        self._ndi_auto.toggled.connect(lambda v: self._edit_ndi(auto_select_source=v))
        layout.addRow("", self._ndi_auto)

        self._ndi_premultiplied = W.checkbox(
            "Source uses premultiplied alpha",
            tooltip="Off by default: the NDI specification says its RGBA data is "
            "not premultiplied. Turn it on if soft edges look washed out.",
        )
        self._ndi_premultiplied.toggled.connect(lambda v: self._edit_ndi(premultiplied_alpha=v))
        layout.addRow("", self._ndi_premultiplied)

        self._ndi_low_bandwidth = W.checkbox(
            "Low bandwidth (proxy resolution)",
            tooltip="Much less network traffic at a lower resolution. Useful for "
            "laying out parcels over a slow link.",
        )
        self._ndi_low_bandwidth.toggled.connect(lambda v: self._edit_ndi(low_bandwidth=v))
        layout.addRow("", self._ndi_low_bandwidth)

        layout.addRow(
            "",
            W.hint_label(
                "NDI needs the 'ndi-python' package and the NDI Runtime, which is "
                "installed separately because of its licence."
            ),
        )
        return self._page(layout)

    def _build_screen_page(self) -> QWidget:
        layout = W.form()

        self._screen_monitor = QComboBox()
        self._screen_monitor.currentIndexChanged.connect(self._on_screen_monitor_changed)
        layout.addRow("Monitor", self._screen_monitor)

        self._screen_use_region = W.checkbox("Capture only part of the monitor")
        self._screen_use_region.toggled.connect(self._on_screen_region_toggled)
        layout.addRow("", self._screen_use_region)

        self._screen_x = W.spin(0, 32000, 0, suffix=" px")
        self._screen_y = W.spin(0, 32000, 0, suffix=" px")
        self._screen_w = W.spin(1, 32000, 1280, suffix=" px")
        self._screen_h = W.spin(1, 32000, 720, suffix=" px")
        for box in (self._screen_x, self._screen_y, self._screen_w, self._screen_h):
            box.valueChanged.connect(self._on_screen_region_changed)
        layout.addRow(
            "Region",
            W.row(
                QLabel("X"),
                self._screen_x,
                QLabel("Y"),
                self._screen_y,
                QLabel("W"),
                self._screen_w,
                QLabel("H"),
                self._screen_h,
            ),
        )
        layout.addRow("", W.hint_label("Coordinates are relative to the chosen monitor."))

        self._screen_avoid_self = W.checkbox(
            "Hide the overlay from its own capture",
            tooltip="Capturing the display the overlay sits on makes it photograph "
            "itself, producing an infinite tunnel. This turns on capture exclusion "
            "automatically when the two overlap.",
        )
        self._screen_avoid_self.toggled.connect(lambda v: self._edit_screen(avoid_self_capture=v))
        layout.addRow("", self._screen_avoid_self)

        return self._page(layout)

    def _build_image_page(self) -> QWidget:
        layout = W.form()

        self._image_path = QLineEdit()
        self._image_path.setMinimumWidth(280)
        self._image_path.setPlaceholderText("Choose a PNG, GIF or WebP…")
        self._image_path.editingFinished.connect(self._on_image_path_changed)
        browse = W.button("Browse…", self._browse_image)
        layout.addRow("Image file", W.row(self._image_path, browse, stretch_last=True))

        self._image_animate = W.checkbox(
            "Play animation",
            tooltip="Applies to GIF and animated WebP. Off shows the first frame only.",
        )
        self._image_animate.toggled.connect(lambda v: self._edit_image(animate=v))
        layout.addRow("", self._image_animate)

        layout.addRow(
            "",
            W.hint_label(
                "A PNG with transparency is the quickest way to put a logo or a "
                "frame on screen — no OBS, no network."
            ),
        )
        return self._page(layout)

    def _build_demo_page(self) -> QWidget:
        layout = W.form()
        layout.addRow(
            "",
            W.hint_label(
                "An animated pattern with genuinely transparent areas. Use it to lay "
                "out parcels before OBS is running, and to confirm that the alpha "
                "path works end to end."
            ),
        )
        return self._page(layout)

    @staticmethod
    def _page(layout: object) -> QWidget:
        page = QWidget()
        page.setLayout(layout)  # type: ignore[arg-type]
        return page

    # -- per-kind editing --------------------------------------------------
    def _edit_group(self, group: object, **changes: object) -> None:
        """Apply changes to one source sub-group and announce the section."""
        if self._loading:
            return
        for key, value in changes.items():
            if hasattr(group, key):
                setattr(group, key, value)
            else:  # pragma: no cover - programming error
                logger.warning("Unknown source setting %s", key)
        self._emit(SECTION_SOURCE)

    def _edit_spout(self, **changes: object) -> None:
        self._edit_group(self._profile.source.spout, **changes)

    def _edit_ndi(self, **changes: object) -> None:
        self._edit_group(self._profile.source.ndi, **changes)

    def _edit_screen(self, **changes: object) -> None:
        self._edit_group(self._profile.source.screen, **changes)

    def _edit_image(self, **changes: object) -> None:
        self._edit_group(self._profile.source.image, **changes)

    def _on_source_kind_changed(self) -> None:
        kind = self._source_kind.currentData()
        self._show_source_page(kind)
        if self._loading:
            return
        self._edit(SECTION_SOURCE, kind=kind)
        self._refresh_current_source_list()

    def _show_source_page(self, kind: SourceKind) -> None:
        index = self._source_page_index.get(kind)
        if index is not None:
            self._source_pages.setCurrentIndex(index)
        reason = unavailable_reason(kind) if kind is not None else ""
        self._kind_warning.setText(reason)
        self._kind_warning.setProperty("role", "error" if reason else "hint")
        style = self._kind_warning.style()
        if style is not None:
            style.unpolish(self._kind_warning)
            style.polish(self._kind_warning)

    # -- Spout -------------------------------------------------------------
    def _on_sender_text_changed(self) -> None:
        if self._loading:
            return
        self._edit_spout(sender_name=self._sender_combo.currentText().strip())

    def refresh_senders(self) -> None:
        """Re-scan Spout and repopulate the sender list."""
        current = self._sender_combo.currentText()
        names = available_sender_names(SourceKind.SPOUT)
        self._loading = True
        try:
            self._sender_combo.clear()
            self._sender_combo.addItems(names)
            self._sender_combo.setEditText(current)
        finally:
            self._loading = False

        if not spout_available():
            self._status.show_message(unavailable_reason(SourceKind.SPOUT), "error")
        elif names:
            self._status.show_message(f"Found {len(names)} Spout sender(s).", "success")
        else:
            self._status.show_message(
                "No Spout senders found. In OBS, add the 'Spout2 Output' filter to "
                "the scene or source you want to send.",
                "hint",
            )

    # -- NDI ---------------------------------------------------------------
    def _on_ndi_text_changed(self) -> None:
        if self._loading:
            return
        self._edit_ndi(source_name=self._ndi_combo.currentText().strip())

    def refresh_ndi_sources(self) -> None:
        """Scan the network for NDI sources."""
        if not ndi_available():
            self._status.show_message(unavailable_reason(SourceKind.NDI), "error")
            return

        self._status.show_message("Scanning the network for NDI sources…", "hint")
        QApplication.processEvents()

        current = self._ndi_combo.currentText()
        names = available_sender_names(SourceKind.NDI)
        self._loading = True
        try:
            self._ndi_combo.clear()
            self._ndi_combo.addItems(names)
            self._ndi_combo.setEditText(current)
        finally:
            self._loading = False

        if names:
            self._status.show_message(f"Found {len(names)} NDI source(s).", "success")
        else:
            self._status.show_message(
                "No NDI sources found. Check that the sender is on the same network "
                "and that discovery (mDNS) is not blocked by a firewall.",
                "hint",
            )

    # -- Screen ------------------------------------------------------------
    def _on_screen_monitor_changed(self) -> None:
        index = self._screen_monitor.currentData()
        if index is not None:
            self._edit_screen(monitor_index=int(index))

    def _on_screen_region_toggled(self, enabled: bool) -> None:
        for box in (self._screen_x, self._screen_y, self._screen_w, self._screen_h):
            box.setEnabled(enabled)
        self._edit_screen(use_region=enabled)

    def _on_screen_region_changed(self) -> None:
        self._edit_screen(
            region=RectSpec(
                self._screen_x.value(),
                self._screen_y.value(),
                max(1, self._screen_w.value()),
                max(1, self._screen_h.value()),
            )
        )

    def _populate_capture_monitors(self) -> None:
        self._screen_monitor.clear()
        for index, screen in enumerate(QGuiApplication.screens()):
            rect = screen.geometry()
            self._screen_monitor.addItem(
                f"{index}: {screen.name()} ({rect.width()}×{rect.height()})", index
            )

    # -- Image -------------------------------------------------------------
    def _on_image_path_changed(self) -> None:
        if self._loading:
            return
        self._edit_image(path=self._image_path.text().strip())

    def _browse_image(self) -> None:
        from ..sources.image_source import supported_image_filter

        start = self._profile.source.image.path or str(paths.data_dir())
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose an image", start, supported_image_filter()
        )
        if not path:
            return
        self._image_path.setText(path)
        self._edit_image(path=path)

    def _refresh_current_source_list(self) -> None:
        """Populate the picker for whichever source kind is selected."""
        kind = self._source_kind.currentData()
        if kind is SourceKind.SPOUT:
            self.refresh_senders()
        elif kind is SourceKind.SCREEN:
            self._populate_capture_monitors()
            W.select_data(self._screen_monitor, self._profile.source.screen.monitor_index)

    # ------------------------------------------------------------------
    # Display tab
    # ------------------------------------------------------------------
    def _build_display_tab(self) -> QWidget:
        placement = QGroupBox("Placement")
        layout = W.form()

        self._geometry_mode = W.combo(
            (
                ("Primary monitor", GeometryMode.PRIMARY),
                ("Specific monitor", GeometryMode.MONITOR),
                ("All monitors (virtual desktop)", GeometryMode.VIRTUAL),
                ("Custom rectangle", GeometryMode.CUSTOM),
            )
        )
        self._geometry_mode.currentIndexChanged.connect(self._on_geometry_mode_changed)
        layout.addRow("Covers", self._geometry_mode)

        self._monitor_combo = QComboBox()
        self._monitor_combo.currentIndexChanged.connect(self._on_monitor_changed)
        layout.addRow("Monitor", self._monitor_combo)

        self._custom_x = W.spin(-32000, 32000, 0, suffix=" px")
        self._custom_y = W.spin(-32000, 32000, 0, suffix=" px")
        self._custom_w = W.spin(1, 32000, 1920, suffix=" px")
        self._custom_h = W.spin(1, 32000, 1080, suffix=" px")
        for box in (self._custom_x, self._custom_y, self._custom_w, self._custom_h):
            box.valueChanged.connect(self._on_custom_rect_changed)
        layout.addRow(
            "Rectangle",
            W.row(
                QLabel("X"),
                self._custom_x,
                QLabel("Y"),
                self._custom_y,
                QLabel("W"),
                self._custom_w,
                QLabel("H"),
                self._custom_h,
            ),
        )
        placement.setLayout(layout)

        framing = QGroupBox("Framing")
        frame_layout = W.form()

        self._fit_mode = W.combo(
            (
                ("Contain (fit, keep aspect)", FitMode.CONTAIN),
                ("None (1:1 pixels)", FitMode.NONE),
                ("Cover (fill, keep aspect)", FitMode.COVER),
                ("Stretch (fill, distort)", FitMode.STRETCH),
            )
        )
        self._fit_mode.currentIndexChanged.connect(
            lambda: self._edit(SECTION_DISPLAY, fit_mode=self._fit_mode.currentData())
        )
        frame_layout.addRow("Fit", self._fit_mode)
        frame_layout.addRow(
            "",
            W.hint_label(
                "The blueprint's behaviour is 'None': pixels are drawn 1:1 and the "
                "parcels alone decide what is visible. 'Contain' is the default "
                "because an OBS canvas and a monitor often differ in size."
            ),
        )

        self._anchor = W.combo(
            (
                ("Top left", Anchor.TOP_LEFT),
                ("Top centre", Anchor.TOP_CENTER),
                ("Top right", Anchor.TOP_RIGHT),
                ("Centre left", Anchor.CENTER_LEFT),
                ("Centre", Anchor.CENTER),
                ("Centre right", Anchor.CENTER_RIGHT),
                ("Bottom left", Anchor.BOTTOM_LEFT),
                ("Bottom centre", Anchor.BOTTOM_CENTER),
                ("Bottom right", Anchor.BOTTOM_RIGHT),
            )
        )
        self._anchor.currentIndexChanged.connect(
            lambda: self._edit(SECTION_DISPLAY, anchor=self._anchor.currentData())
        )
        frame_layout.addRow("Anchor", self._anchor)

        self._zoom = W.dspin(0.05, 20.0, 1.0, step=0.05, decimals=2, suffix="×")
        self._zoom.valueChanged.connect(lambda v: self._edit(SECTION_DISPLAY, zoom=v))
        frame_layout.addRow("Zoom", self._zoom)

        self._offset_x = W.spin(-32000, 32000, 0, suffix=" px")
        self._offset_y = W.spin(-32000, 32000, 0, suffix=" px")
        self._offset_x.valueChanged.connect(lambda v: self._edit(SECTION_DISPLAY, offset_x=v))
        self._offset_y.valueChanged.connect(lambda v: self._edit(SECTION_DISPLAY, offset_y=v))
        frame_layout.addRow(
            "Offset", W.row(QLabel("X"), self._offset_x, QLabel("Y"), self._offset_y)
        )

        self._opacity = W.PercentSlider(1.0)
        self._opacity.valueChanged.connect(lambda v: self._edit(SECTION_DISPLAY, opacity=v))
        frame_layout.addRow("Opacity", self._opacity)

        self._flip_h = W.checkbox("Mirror horizontally")
        self._flip_v = W.checkbox("Mirror vertically")
        self._flip_h.toggled.connect(lambda v: self._edit(SECTION_DISPLAY, flip_horizontal=v))
        self._flip_v.toggled.connect(lambda v: self._edit(SECTION_DISPLAY, flip_vertical=v))
        frame_layout.addRow("Mirror", W.row(self._flip_h, self._flip_v))

        self._scale_quality = W.combo(
            (("Smooth (bilinear)", ScaleQuality.SMOOTH), ("Fast (nearest)", ScaleQuality.FAST))
        )
        self._scale_quality.currentIndexChanged.connect(
            lambda: self._edit(SECTION_DISPLAY, scale_quality=self._scale_quality.currentData())
        )
        frame_layout.addRow("Scaling", self._scale_quality)
        framing.setLayout(frame_layout)

        return W.column(placement, framing, self._spacer(), margins=4)

    def _on_geometry_mode_changed(self) -> None:
        mode = self._geometry_mode.currentData()
        self._monitor_combo.setEnabled(mode is GeometryMode.MONITOR)
        for box in (self._custom_x, self._custom_y, self._custom_w, self._custom_h):
            box.setEnabled(mode is GeometryMode.CUSTOM)
        self._edit(SECTION_DISPLAY, geometry_mode=mode)

    def _on_monitor_changed(self) -> None:
        index = self._monitor_combo.currentData()
        if index is not None:
            self._edit(SECTION_DISPLAY, monitor_index=int(index))

    def _on_custom_rect_changed(self) -> None:
        self._edit(
            SECTION_DISPLAY,
            custom_rect=RectSpec(
                self._custom_x.value(),
                self._custom_y.value(),
                self._custom_w.value(),
                self._custom_h.value(),
            ),
        )

    def _populate_monitors(self) -> None:
        self._monitor_combo.clear()
        for index, screen in enumerate(QGuiApplication.screens()):
            rect = screen.geometry()
            primary = " – primary" if screen == QGuiApplication.primaryScreen() else ""
            self._monitor_combo.addItem(
                f"{index}: {screen.name()} ({rect.width()}×{rect.height()}){primary}", index
            )

    # ------------------------------------------------------------------
    # Parcels tab
    # ------------------------------------------------------------------
    def _build_parcels_tab(self) -> QWidget:
        self._table = ParcelTable(lambda: self._profile.parcels)
        self._table.parcelEdited.connect(self._on_parcel_edited)
        self._table.selectionUpdated.connect(self._on_table_selection)

        toolbar = W.row(
            W.button("Add", self._add_parcel),
            W.button("Duplicate", self._duplicate_parcels),
            W.button("Delete", self._delete_parcels, role="danger"),
            W.button("Grid layout…", self._generate_grid),
            W.button("Select all", lambda: self._table.selectAll()),
            stretch_last=False,
        )

        align_bar = W.row(
            QLabel("Align:"),
            W.button("Left", lambda: self._align(geo.AlignMode.LEFT)),
            W.button("Centre", lambda: self._align(geo.AlignMode.H_CENTER)),
            W.button("Right", lambda: self._align(geo.AlignMode.RIGHT)),
            W.button("Top", lambda: self._align(geo.AlignMode.TOP)),
            W.button("Middle", lambda: self._align(geo.AlignMode.V_CENTER)),
            W.button("Bottom", lambda: self._align(geo.AlignMode.BOTTOM)),
            W.button("Spread H", lambda: self._distribute(True)),
            W.button("Spread V", lambda: self._distribute(False)),
            stretch_last=False,
        )

        self._coverage_label = W.hint_label("")

        group = QGroupBox("Parcels (boxes cut out of the overlay window)")
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.addWidget(toolbar)
        layout.addWidget(align_bar)
        layout.addWidget(self._table, 1)
        layout.addWidget(self._coverage_label)
        layout.addWidget(
            W.hint_label(
                "Mode 'Cut' subtracts a parcel from the ones declared above it, which is "
                "how you make a hole in a box. Drag the boxes directly on screen with "
                "Edit layout."
            )
        )
        group.setLayout(layout)
        return W.column(group, margins=4)

    def _selected_parcel_ids(self) -> list[str]:
        return self._table.selected_ids()

    def _on_parcel_edited(self, parcel_id: str, changes: dict) -> None:
        index = self._profile.index_of(parcel_id)
        if index < 0:
            return
        self._profile.parcels[index] = apply_edit(self._profile.parcels[index], changes)
        self._emit(SECTION_PARCELS)
        self._update_coverage()

    def _on_table_selection(self, ids: list[str]) -> None:
        self.parcelSelectionChanged.emit(ids)

    def _add_parcel(self) -> None:
        canvas = self._canvas_rect()
        width = max(120, canvas.width // 4)
        height = max(80, canvas.height // 4)
        parcel = Parcel(
            name=f"Parcel {len(self._profile.parcels) + 1}",
            x=canvas.x + (canvas.width - width) // 2,
            y=canvas.y + (canvas.height - height) // 2,
            width=width,
            height=height,
        )
        self._profile.parcels.append(parcel)
        self._emit(SECTION_PARCELS)
        self.refresh_parcels([parcel.id])

    def _duplicate_parcels(self) -> None:
        ids = set(self._selected_parcel_ids())
        clones = [p.clone() for p in self._profile.parcels if p.id in ids]
        if not clones:
            self._status.show_message("Select a parcel to duplicate first.", "hint")
            return
        self._profile.parcels.extend(clones)
        self._emit(SECTION_PARCELS)
        self.refresh_parcels([c.id for c in clones])

    def _delete_parcels(self) -> None:
        ids = set(self._selected_parcel_ids())
        if not ids:
            self._status.show_message("Select a parcel to delete first.", "hint")
            return
        remaining = [p for p in self._profile.parcels if p.id not in ids]
        if len(remaining) == len(self._profile.parcels):
            return
        self._profile.parcels = remaining
        self._emit(SECTION_PARCELS)
        self.refresh_parcels([])

    def _generate_grid(self) -> None:
        columns, ok = QInputDialog.getInt(self, "Grid layout", "Columns:", 3, 1, 32)
        if not ok:
            return
        rows, ok = QInputDialog.getInt(self, "Grid layout", "Rows:", 2, 1, 32)
        if not ok:
            return
        gap, ok = QInputDialog.getInt(self, "Grid layout", "Gap (px):", 16, 0, 512)
        if not ok:
            return

        rects = geo.grid_layout(self._canvas_rect(), columns, rows, gap=gap)
        if not rects:
            self._status.show_message(
                "That grid does not fit in the overlay area. Try fewer cells or a smaller gap.",
                "error",
            )
            return

        answer = QMessageBox.question(
            self,
            "Grid layout",
            f"Replace the current {len(self._profile.parcels)} parcel(s) with "
            f"{len(rects)} grid cells?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._profile.parcels = geo.rects_to_parcels(rects, corner_radius=16)
        self._emit(SECTION_PARCELS)
        self.refresh_parcels([])

    def _align(self, mode: geo.AlignMode) -> None:
        ids = list(self._selected_parcel_ids())
        selected = [p for p in self._profile.parcels if p.id in ids and not p.locked]
        if len(selected) < 2:
            self._status.show_message("Select at least two parcels to align.", "hint")
            return
        aligned = geo.align_rects([p.rect for p in selected], mode)
        mapping = {p.id: rect for p, rect in zip(selected, aligned)}
        self._apply_rects(mapping, ids)

    def _distribute(self, horizontal: bool) -> None:
        ids = list(self._selected_parcel_ids())
        selected = [p for p in self._profile.parcels if p.id in ids and not p.locked]
        if len(selected) < 3:
            self._status.show_message("Select at least three parcels to spread.", "hint")
            return
        spread = geo.distribute_rects([p.rect for p in selected], horizontal)
        mapping = {p.id: rect for p, rect in zip(selected, spread)}
        self._apply_rects(mapping, ids)

    def _apply_rects(self, mapping: dict, keep_selected: list[str]) -> None:
        for index, parcel in enumerate(self._profile.parcels):
            rect = mapping.get(parcel.id)
            if rect is not None:
                self._profile.parcels[index] = parcel.with_rect(rect)
        self._emit(SECTION_PARCELS)
        self.refresh_parcels(keep_selected)

    def _canvas_rect(self) -> RectSpec:
        """The overlay's area, used to place new parcels sensibly."""
        display = self._profile.display
        if display.geometry_mode is GeometryMode.CUSTOM and display.custom_rect.width > 0:
            return RectSpec(0, 0, display.custom_rect.width, display.custom_rect.height)
        screens = QGuiApplication.screens()
        if not screens:
            return RectSpec(0, 0, 1920, 1080)
        if display.geometry_mode is GeometryMode.MONITOR and 0 <= display.monitor_index < len(
            screens
        ):
            rect = screens[display.monitor_index].geometry()
        else:
            primary = QGuiApplication.primaryScreen() or screens[0]
            rect = primary.geometry()
        return RectSpec(0, 0, rect.width(), rect.height())

    def _update_coverage(self) -> None:
        canvas = self._canvas_rect()
        ratio = geo.coverage_ratio(self._profile.parcels, canvas)
        count = len(self._profile.active_parcels())
        message = (
            f"{count} active parcel(s) covering {ratio * 100:.1f}% of "
            f"{canvas.width}×{canvas.height}."
        )
        if geo.is_unsafe_layout(
            self._profile.parcels,
            canvas,
            self._profile.behavior.click_through,
            self._profile.display.opacity,
        ):
            message += (
                "  ⚠ This nearly covers the screen with click-through off — "
                "you may not be able to reach anything behind it."
            )
            self._coverage_label.setProperty("role", "error")
        else:
            self._coverage_label.setProperty("role", "hint")
        self._coverage_label.setText(message)
        style = self._coverage_label.style()
        if style is not None:
            style.unpolish(self._coverage_label)
            style.polish(self._coverage_label)

    def refresh_parcels(self, selected_ids: list[str] | None = None) -> None:
        """Rebuild the table from the profile (called after editor drags too)."""
        self._table.refresh(selected_ids)
        self._update_coverage()

    # ------------------------------------------------------------------
    # Behaviour tab
    # ------------------------------------------------------------------
    def _build_behavior_tab(self) -> QWidget:
        group = QGroupBox("Window behaviour")
        layout = W.form()

        self._click_through = W.checkbox(
            "Click through the overlay (ghost mode)",
            tooltip="Mouse input passes to whatever is behind. Automatically "
            "suspended while the layout editor is open.",
        )
        self._click_through.toggled.connect(lambda v: self._edit(SECTION_BEHAVIOR, click_through=v))
        layout.addRow("Input", self._click_through)

        self._always_on_top = W.checkbox("Always on top")
        self._always_on_top.toggled.connect(lambda v: self._edit(SECTION_BEHAVIOR, always_on_top=v))
        layout.addRow("", self._always_on_top)

        self._reassert = W.spin(0, 600000, 3000, suffix=" ms", step=500, width=120)
        self._reassert.setToolTip(
            "Re-apply always-on-top on this interval. 0 disables it. "
            "Some fullscreen applications steal the topmost position."
        )
        self._reassert.valueChanged.connect(
            lambda v: self._edit(SECTION_BEHAVIOR, topmost_reassert_ms=v)
        )
        layout.addRow("Re-assert every", self._reassert)

        self._hide_taskbar = W.checkbox("Hide from taskbar and Alt-Tab")
        self._hide_taskbar.toggled.connect(
            lambda v: self._edit(SECTION_BEHAVIOR, hide_from_taskbar=v)
        )
        layout.addRow("", self._hide_taskbar)

        self._no_activate = W.checkbox("Never take keyboard focus")
        self._no_activate.toggled.connect(lambda v: self._edit(SECTION_BEHAVIOR, no_activate=v))
        layout.addRow("", self._no_activate)

        self._exclude_capture = W.checkbox(
            "Hide the overlay from screen capture",
            tooltip="Stops the overlay feeding back into OBS when you capture the "
            "same display. Needs Windows 10 version 2004 or newer.",
        )
        self._exclude_capture.toggled.connect(
            lambda v: self._edit(SECTION_BEHAVIOR, exclude_from_capture=v)
        )
        layout.addRow("", self._exclude_capture)

        self._mask_enabled = W.checkbox(
            "Cut the window into parcels",
            tooltip="Turn off to show the whole feed as one rectangle.",
        )
        self._mask_enabled.toggled.connect(lambda v: self._edit(SECTION_BEHAVIOR, mask_enabled=v))
        layout.addRow("Masking", self._mask_enabled)

        self._safety_guard = W.checkbox(
            "Warn before a layout that could trap the mouse",
            tooltip="Blocks a nearly full-screen, opaque, non-click-through overlay "
            "that you would not be able to click past.",
        )
        self._safety_guard.toggled.connect(lambda v: self._edit(SECTION_BEHAVIOR, safety_guard=v))
        layout.addRow("Safety", self._safety_guard)

        self._minimize_tray = W.checkbox("Keep running in the system tray when closed")
        self._minimize_tray.toggled.connect(
            lambda v: self._edit(SECTION_BEHAVIOR, minimize_to_tray=v)
        )
        layout.addRow("", self._minimize_tray)

        self._show_panel_start = W.checkbox("Open this panel at startup")
        self._show_panel_start.toggled.connect(
            lambda v: self._edit(SECTION_BEHAVIOR, show_panel_on_start=v)
        )
        layout.addRow("", self._show_panel_start)

        group.setLayout(layout)

        hud_group = QGroupBox("Debug overlay")
        hud_layout = W.form()
        self._hud_enabled = W.checkbox("Show the statistics panel on the overlay")
        self._hud_enabled.toggled.connect(lambda v: self._edit(SECTION_HUD, enabled=v))
        hud_layout.addRow("HUD", self._hud_enabled)

        self._hud_corner = W.combo(
            (
                ("Top left", HudCorner.TOP_LEFT),
                ("Top right", HudCorner.TOP_RIGHT),
                ("Bottom left", HudCorner.BOTTOM_LEFT),
                ("Bottom right", HudCorner.BOTTOM_RIGHT),
            )
        )
        self._hud_corner.currentIndexChanged.connect(
            lambda: self._edit(SECTION_HUD, corner=self._hud_corner.currentData())
        )
        hud_layout.addRow("Corner", self._hud_corner)
        hud_group.setLayout(hud_layout)

        return W.column(group, hud_group, self._spacer(), margins=4)

    # ------------------------------------------------------------------
    # Editor tab
    # ------------------------------------------------------------------
    def _build_editor_tab(self) -> QWidget:
        group = QGroupBox("Layout editor")
        layout = W.form()

        self._grid_size = W.spin(1, 512, 10, suffix=" px")
        self._grid_size.valueChanged.connect(lambda v: self._edit(SECTION_EDITOR, grid_size=v))
        layout.addRow("Grid size", self._grid_size)

        self._snap_grid = W.checkbox("Snap to grid")
        self._snap_parcels = W.checkbox("Snap to other parcels")
        self._snap_canvas = W.checkbox("Snap to screen edges and centre")
        self._snap_grid.toggled.connect(lambda v: self._edit(SECTION_EDITOR, snap_to_grid=v))
        self._snap_parcels.toggled.connect(lambda v: self._edit(SECTION_EDITOR, snap_to_parcels=v))
        self._snap_canvas.toggled.connect(lambda v: self._edit(SECTION_EDITOR, snap_to_canvas=v))
        layout.addRow("Snapping", W.column(self._snap_grid, self._snap_parcels, self._snap_canvas))

        self._snap_threshold = W.spin(0, 128, 8, suffix=" px")
        self._snap_threshold.valueChanged.connect(
            lambda v: self._edit(SECTION_EDITOR, snap_threshold=v)
        )
        layout.addRow("Snap distance", self._snap_threshold)

        self._show_grid = W.checkbox("Draw the grid")
        self._show_guides = W.checkbox("Show alignment guides")
        self._show_labels = W.checkbox("Show parcel names and sizes")
        self._show_grid.toggled.connect(lambda v: self._edit(SECTION_EDITOR, show_grid=v))
        self._show_guides.toggled.connect(lambda v: self._edit(SECTION_EDITOR, show_guides=v))
        self._show_labels.toggled.connect(lambda v: self._edit(SECTION_EDITOR, show_labels=v))
        layout.addRow("Guides", W.column(self._show_grid, self._show_guides, self._show_labels))

        self._backdrop = W.PercentSlider(0.35, 0, 95)
        self._backdrop.valueChanged.connect(
            lambda v: self._edit(SECTION_EDITOR, backdrop_opacity=v)
        )
        layout.addRow("Editor dimming", self._backdrop)
        group.setLayout(layout)

        shortcuts = QGroupBox("Editor shortcuts")
        shortcut_layout = W.form()
        for keys, description in (
            ("Drag", "Move the selected parcels"),
            (
                "Drag a handle",
                "Resize; hold Shift to keep the aspect ratio, Alt to resize about the centre",
            ),
            ("Ctrl + drag", "Draw a new parcel"),
            ("Shift + click", "Add to or remove from the selection"),
            ("Arrow keys", "Nudge by one pixel; Shift nudges by the grid size"),
            ("Ctrl + D", "Duplicate"),
            ("Delete", "Remove"),
            ("Ctrl + A", "Select all"),
            ("Ctrl + Z / Ctrl + Shift + Z", "Undo / redo"),
            ("Ctrl + [ / Ctrl + ]", "Send backward / bring forward"),
            ("Esc", "Clear the selection, then leave edit mode"),
        ):
            shortcut_layout.addRow(keys, W.hint_label(description))
        shortcuts.setLayout(shortcut_layout)

        return W.column(group, shortcuts, self._spacer(), margins=4)

    # ------------------------------------------------------------------
    # Hotkeys tab
    # ------------------------------------------------------------------
    def _build_hotkeys_tab(self) -> QWidget:
        group = QGroupBox("Global hotkeys")
        layout = W.form()
        self._hotkey_edits: dict[str, W.HotkeyEdit] = {}
        self._hotkey_status: dict[str, QLabel] = {}

        for action, label in (
            ("toggle_editor", "Toggle the layout editor"),
            ("toggle_click_through", "Toggle click-through"),
            ("toggle_overlay", "Show or hide the overlay"),
            ("toggle_panel", "Show or hide this panel"),
            ("reload_profile", "Reload the active profile from disk"),
            ("panic", "Panic: restore input and show this panel"),
        ):
            edit = W.HotkeyEdit()
            edit.hotkeyChanged.connect(
                lambda value, name=action: self._on_hotkey_changed(name, value)
            )
            status = QLabel("")
            status.setProperty("role", "hint")
            self._hotkey_edits[action] = edit
            self._hotkey_status[action] = status
            layout.addRow(label, W.column(edit, status, spacing=2))

        layout.addRow(
            "",
            W.hint_label(
                "Global hotkeys work even while another application has focus. "
                "If one is already taken by another program, the reason appears "
                "under it and you can pick a different combination. F12 is "
                "reserved by Windows and cannot be used."
            ),
        )
        group.setLayout(layout)
        return W.column(group, self._spacer(), margins=4)

    def _on_hotkey_changed(self, action: str, value: str) -> None:
        if self._loading:
            return
        setattr(self._profile.hotkeys, action, value)
        self._emit(SECTION_HOTKEYS)

    def set_hotkey_failures(self, failures: dict[str, str]) -> None:
        """Show, per action, why a hotkey could not be registered."""
        self._hotkey_failures = dict(failures)
        for action, label in self._hotkey_status.items():
            reason = failures.get(action, "")
            label.setText(reason)
            label.setProperty("role", "error" if reason else "hint")
            style = label.style()
            if style is not None:
                style.unpolish(label)
                style.polish(label)

    # ------------------------------------------------------------------
    # Profiles tab
    # ------------------------------------------------------------------
    def _build_profiles_tab(self) -> QWidget:
        group = QGroupBox("Profiles")
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.addWidget(
            W.hint_label(
                "A profile holds one complete setup: source, placement, parcels, "
                "behaviour and hotkeys. Keep one per scene and switch between them."
            )
        )
        layout.addWidget(
            W.row(
                W.button("New…", self._new_profile),
                W.button("Duplicate…", self._duplicate_profile),
                W.button("Rename…", self._rename_profile),
                W.button("Delete", self._delete_profile, role="danger"),
                stretch_last=False,
            )
        )
        layout.addWidget(
            W.row(
                W.button("Import…", self._import_profile),
                W.button("Export…", self._export_profile),
                W.button("Open folder", self._open_data_folder),
                stretch_last=False,
            )
        )
        self._profiles_hint = W.hint_label("")
        layout.addWidget(self._profiles_hint)
        layout.addStretch(1)
        group.setLayout(layout)
        return W.column(group, margins=4)

    def _new_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "New profile", "Name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if self._store.exists(name):
            self._status.show_message(f"A profile named {name!r} already exists.", "error")
            return
        try:
            self._store.save_profile(Profile.default(name))
        except ProfileStoreError as exc:
            self._status.show_message(str(exc), "error")
            return
        self.refresh_profiles()
        self.profileSwitched.emit(name)

    def _duplicate_profile(self) -> None:
        source = self._profile.name
        name, ok = QInputDialog.getText(
            self, "Duplicate profile", "New name:", text=f"{source} copy"
        )
        if not ok or not name.strip():
            return
        try:
            self._store.save_profile(self._profile)
            self._store.duplicate_profile(source, name.strip())
        except ProfileStoreError as exc:
            self._status.show_message(str(exc), "error")
            return
        self.refresh_profiles()
        self.profileSwitched.emit(name.strip())

    def _rename_profile(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Rename profile", "New name:", text=self._profile.name
        )
        if not ok or not name.strip() or name.strip() == self._profile.name:
            return
        try:
            self._store.save_profile(self._profile)
            renamed = self._store.rename_profile(self._profile.name, name.strip())
        except ProfileStoreError as exc:
            self._status.show_message(str(exc), "error")
            return
        self.refresh_profiles()
        self.profileSwitched.emit(renamed.name)

    def _delete_profile(self) -> None:
        names = self._store.list_profiles()
        if len(names) <= 1:
            self._status.show_message("The last profile cannot be deleted.", "error")
            return
        answer = QMessageBox.question(
            self,
            "Delete profile",
            f"Delete the profile {self._profile.name!r}? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        doomed = self._profile.name
        try:
            self._store.delete_profile(doomed)
        except ProfileStoreError as exc:
            self._status.show_message(str(exc), "error")
            return
        remaining = [n for n in self._store.list_profiles() if n != doomed]
        self.refresh_profiles()
        if remaining:
            self.profileSwitched.emit(remaining[0])

    def _import_profile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import profile", str(paths.profiles_dir()), "Profiles (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            imported = self._store.import_profile(paths.Path(path))
        except ProfileStoreError as exc:
            self._status.show_message(str(exc), "error")
            return
        self.refresh_profiles()
        self.profileSwitched.emit(imported.name)
        self._status.show_message(f"Imported as {imported.name!r}.", "success")

    def _export_profile(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export profile",
            str(paths.data_dir() / f"{self._profile.name}.json"),
            "Profiles (*.json)",
        )
        if not path:
            return
        try:
            self._store.export_profile(self._profile, paths.Path(path))
        except ProfileStoreError as exc:
            self._status.show_message(str(exc), "error")
            return
        self._status.show_message(f"Exported to {path}", "success")

    def _open_data_folder(self) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        paths.ensure_dirs()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.data_dir())))

    def refresh_profiles(self) -> None:
        names = self._store.list_profiles()
        self._loading = True
        try:
            self._profile_combo.clear()
            self._profile_combo.addItems(names)
            index = self._profile_combo.findText(self._profile.name)
            if index >= 0:
                self._profile_combo.setCurrentIndex(index)
        finally:
            self._loading = False
        self._profiles_hint.setText(f"{len(names)} profile(s) stored in {paths.profiles_dir()}")

    def _on_profile_selected(self) -> None:
        if self._loading:
            return
        name = self._profile_combo.currentText()
        if name and name != self._profile.name:
            self.profileSwitched.emit(name)

    # ------------------------------------------------------------------
    # About tab
    # ------------------------------------------------------------------
    def _build_about_tab(self) -> QWidget:
        group = QGroupBox("About")
        layout = W.form()
        layout.addRow("Application", QLabel(f"{APP_NAME} {APP_VERSION}"))

        import sys

        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

        layout.addRow("Python", QLabel(sys.version.split()[0]))
        layout.addRow("Qt / PyQt", QLabel(f"{QT_VERSION_STR} / {PYQT_VERSION_STR}"))

        self._spout_label = QLabel("—")
        layout.addRow("SpoutGL", self._spout_label)

        self._ndi_label = QLabel("—")
        layout.addRow("NDI", self._ndi_label)

        layout.addRow("Data folder", QLabel(str(paths.data_dir())))
        layout.addRow("Log file", QLabel(str(paths.logs_dir())))
        layout.addRow(
            "",
            W.row(
                W.button("Open data folder", self._open_data_folder),
                W.button("Quit", lambda: self.quitRequested.emit(), role="danger"),
                stretch_last=False,
            ),
        )
        group.setLayout(layout)

        help_group = QGroupBox("Getting a transparent feed out of OBS")
        help_layout = QVBoxLayout()
        for step in (
            "1. Install the Spout2 plugin for OBS and restart OBS.",
            "2. Settings → Advanced → Color Format: set it to BGRA (8-bit). "
            "Without this the feed has no alpha channel and the overlay is opaque.",
            "3. Right-click the scene or source you want to send → Filters → "
            "add 'Spout2 Output' and give it a sender name.",
            "4. Make sure the scene background is genuinely transparent "
            "(no colour source behind it).",
            "5. Back here, press Refresh on the Source tab and pick the sender.",
        ):
            help_layout.addWidget(W.hint_label(step))
        help_group.setLayout(help_layout)

        return W.column(group, help_group, self._spacer(), margins=4)

    # ------------------------------------------------------------------
    # Loading / editing
    # ------------------------------------------------------------------
    @staticmethod
    def _spacer() -> QWidget:
        """Pushes the groups above it to the top of a tab."""
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        return spacer

    def load_profile(self, profile: Profile) -> None:
        """Point the panel at a (possibly different) profile and repopulate."""
        self._profile = profile
        self._loading = True
        try:
            source = profile.source
            W.select_data(self._source_kind, source.kind)
            self._target_fps.setValue(source.target_fps)
            self._auto_reconnect.setChecked(source.auto_reconnect)
            self._fallback_demo.setChecked(source.fallback_to_demo)

            self._sender_combo.setEditText(source.spout.sender_name)
            self._auto_select.setChecked(source.spout.auto_select_sender)
            self._invert_y.setChecked(source.spout.invert_y)
            self._premultiplied.setChecked(source.spout.premultiplied_alpha)

            self._ndi_combo.setEditText(source.ndi.source_name)
            self._ndi_auto.setChecked(source.ndi.auto_select_source)
            self._ndi_premultiplied.setChecked(source.ndi.premultiplied_alpha)
            self._ndi_low_bandwidth.setChecked(source.ndi.low_bandwidth)

            self._populate_capture_monitors()
            W.select_data(self._screen_monitor, source.screen.monitor_index)
            self._screen_use_region.setChecked(source.screen.use_region)
            self._screen_x.setValue(source.screen.region.x)
            self._screen_y.setValue(source.screen.region.y)
            self._screen_w.setValue(max(1, source.screen.region.width))
            self._screen_h.setValue(max(1, source.screen.region.height))
            self._screen_avoid_self.setChecked(source.screen.avoid_self_capture)
            for box in (self._screen_x, self._screen_y, self._screen_w, self._screen_h):
                box.setEnabled(source.screen.use_region)

            self._image_path.setText(source.image.path)
            self._image_animate.setChecked(source.image.animate)

            self._show_source_page(source.kind)

            display = profile.display
            self._populate_monitors()
            W.select_data(self._geometry_mode, display.geometry_mode)
            W.select_data(self._monitor_combo, display.monitor_index)
            self._custom_x.setValue(display.custom_rect.x)
            self._custom_y.setValue(display.custom_rect.y)
            self._custom_w.setValue(max(1, display.custom_rect.width))
            self._custom_h.setValue(max(1, display.custom_rect.height))
            W.select_data(self._fit_mode, display.fit_mode)
            W.select_data(self._anchor, display.anchor)
            self._zoom.setValue(display.zoom)
            self._offset_x.setValue(display.offset_x)
            self._offset_y.setValue(display.offset_y)
            self._opacity.setValue(display.opacity)
            self._flip_h.setChecked(display.flip_horizontal)
            self._flip_v.setChecked(display.flip_vertical)
            W.select_data(self._scale_quality, display.scale_quality)

            behavior = profile.behavior
            self._click_through.setChecked(behavior.click_through)
            self._always_on_top.setChecked(behavior.always_on_top)
            self._reassert.setValue(behavior.topmost_reassert_ms)
            self._hide_taskbar.setChecked(behavior.hide_from_taskbar)
            self._no_activate.setChecked(behavior.no_activate)
            self._exclude_capture.setChecked(behavior.exclude_from_capture)
            self._mask_enabled.setChecked(behavior.mask_enabled)
            self._safety_guard.setChecked(behavior.safety_guard)
            self._minimize_tray.setChecked(behavior.minimize_to_tray)
            self._show_panel_start.setChecked(behavior.show_panel_on_start)

            editor = profile.editor
            self._grid_size.setValue(editor.grid_size)
            self._snap_grid.setChecked(editor.snap_to_grid)
            self._snap_parcels.setChecked(editor.snap_to_parcels)
            self._snap_canvas.setChecked(editor.snap_to_canvas)
            self._snap_threshold.setValue(editor.snap_threshold)
            self._show_grid.setChecked(editor.show_grid)
            self._show_guides.setChecked(editor.show_guides)
            self._show_labels.setChecked(editor.show_labels)
            self._backdrop.setValue(editor.backdrop_opacity)

            hud = profile.hud
            self._hud_enabled.setChecked(hud.enabled)
            W.select_data(self._hud_corner, hud.corner)

            for action, edit in self._hotkey_edits.items():
                edit.setText(getattr(profile.hotkeys, action, ""))

            self._spout_label.setText(
                "installed" if spout_available() else "not installed (Windows only)"
            )
            self._ndi_label.setText(
                "installed" if ndi_available() else "not installed (needs the NDI Runtime)"
            )
        finally:
            self._loading = False

        self._on_geometry_mode_changed_visual_only()
        self.refresh_profiles()
        self.refresh_parcels([])
        # Only scan for the kind actually in use: an NDI scan takes a second
        # and a Spout scan loads a native library, neither of which should
        # happen just because a profile was opened.
        self._refresh_current_source_list()

    def _on_geometry_mode_changed_visual_only(self) -> None:
        mode = self._geometry_mode.currentData()
        self._monitor_combo.setEnabled(mode is GeometryMode.MONITOR)
        for box in (self._custom_x, self._custom_y, self._custom_w, self._custom_h):
            box.setEnabled(mode is GeometryMode.CUSTOM)

    def _edit(self, section: str, **changes: object) -> None:
        """Apply widget changes to the profile and announce the section."""
        if self._loading:
            return
        target = {
            SECTION_SOURCE: self._profile.source,
            SECTION_DISPLAY: self._profile.display,
            SECTION_BEHAVIOR: self._profile.behavior,
            SECTION_EDITOR: self._profile.editor,
            SECTION_HUD: self._profile.hud,
        }.get(section)
        if target is None:
            logger.warning("Unknown settings section %r", section)
            return
        for key, value in changes.items():
            if hasattr(target, key):
                setattr(target, key, value)
            else:
                logger.warning("Unknown setting %s.%s", section, key)
        self._emit(section)
        if section in (SECTION_BEHAVIOR, SECTION_DISPLAY):
            self._update_coverage()

    def _emit(self, section: str) -> None:
        self.profileEdited.emit(section)

    # ------------------------------------------------------------------
    # Live readouts
    # ------------------------------------------------------------------
    def set_status(self, info: SourceInfo, stats: StatsSnapshot) -> None:
        self._latest_info = info
        self._latest_stats = stats

    def _refresh_live_readouts(self) -> None:
        info, stats = self._latest_info, self._latest_stats
        tint = {
            SourceState.CONNECTED: PALETTE.success,
            SourceState.CONNECTING: PALETTE.warning,
            SourceState.ERROR: PALETTE.danger,
        }.get(info.state, PALETTE.text_muted)

        self._status_state.setText(info.state.value.title())
        self._status_state.setStyleSheet(f"color: {tint};")
        self._status_resolution.setText(info.resolution)
        self._status_fps.setText(f"{stats.fps:.1f} fps (target {self._profile.source.target_fps})")
        self._status_frames.setText(
            f"{stats.frames_received} received, {stats.frames_dropped} dropped "
            f"({stats.drop_ratio * 100:.1f}%)"
        )
        self._status_detail.setText(info.detail)
        name = info.name or EM_DASH
        self._connection_label.setText(
            f"{name}  {MIDDLE_DOT}  {info.resolution}  {MIDDLE_DOT}  {stats.fps:.0f} fps"
        )
        self._connection_label.setStyleSheet(f"color: {tint};")

    def set_edit_mode(self, active: bool) -> None:
        self._edit_button.setText("Finish editing" if active else "Edit layout")
        with contextlib.suppress(TypeError):
            self._edit_button.clicked.disconnect()
        self._edit_button.clicked.connect(lambda: self.editModeRequested.emit(not active))

    # ------------------------------------------------------------------
    # Window events
    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_timer.start()
        self._refresh_live_readouts()
        self.refresh_parcels(self._table.selected_ids())

    def hideEvent(self, event) -> None:
        self._refresh_timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event: QCloseEvent | None) -> None:
        # Closing the panel never quits the app: the overlay is the product,
        # and the tray icon is how you get back here.
        if event is not None:
            event.ignore()
        self.hide()
