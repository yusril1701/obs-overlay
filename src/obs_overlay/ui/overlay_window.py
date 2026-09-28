"""The transparent, click-through overlay window.

Everything is painted by one top-level widget rather than a tree of child
widgets. That is deliberate: on Windows, Qt gives a frameless
``WA_TranslucentBackground`` top-level a layered window flushed with
``UpdateLayeredWindowIndirect(..., ULW_ALPHA)``, and keeping the whole surface
under one ``paintEvent`` avoids the child-widget compositing quirks that show
up on that path.

Two modes:

*Overlay mode* — the window is masked to the parcels, click-through, and never
takes focus. The mask is what makes the "parsel" idea physical: Windows hit
tests against the masked shape, so everything between the boxes belongs to
whatever is behind.

*Edit mode* — the mask is removed and input is accepted, so the whole canvas
can be seen and the parcels dragged. The video is dimmed outside the parcels
and full strength inside, which shows at a glance what each box is cropping.

Ordering rule when creating the window: ``WA_TranslucentBackground`` must be
set before the native window exists (Qt only promotes the surface format to an
8-bit alpha buffer while ``QWindow::handle()`` is still null — QTBUG-85714),
and ``FramelessWindowHint`` is required or Qt never applies ``WS_EX_LAYERED``
at all.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QCursor,
    QFont,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QRegion,
    QScreen,
)
from PyQt6.QtWidgets import QMenu, QWidget

from ..config.models import (
    GeometryMode,
    Parcel,
    Profile,
    RectSpec,
    ScaleQuality,
)
from ..core import geometry as geo
from ..core.fps import StatsSnapshot
from ..core.frame import Frame, PixelFormat
from ..core.mask import build_path, build_region
from ..native.base import WindowController
from ..sources.base import SourceInfo, SourceState
from .editor import ParcelEditor
from .hud import paint_hud
from .theme import PALETTE, color

logger = logging.getLogger(__name__)

# Keyed by (pixel byte order, alpha is premultiplied).
#
# Choosing the premultiplied variant matters: OBS composites its scene with the
# premultiplied "over" operator, so the Spout filter's output already has its
# colour channels multiplied by alpha. Describing that data as straight alpha
# makes Qt multiply by alpha a second time, which shows up as dark fringes
# around every antialiased edge.
_QIMAGE_FORMATS = {
    (PixelFormat.RGBA8888, False): QImage.Format.Format_RGBA8888,
    (PixelFormat.RGBA8888, True): QImage.Format.Format_RGBA8888_Premultiplied,
    (PixelFormat.BGRA8888, False): QImage.Format.Format_ARGB32,
    (PixelFormat.BGRA8888, True): QImage.Format.Format_ARGB32_Premultiplied,
}


class OverlayWindow(QWidget):
    """Frameless, always-on-top, per-pixel-alpha overlay."""

    #: Emitted when the parcel layout changed and should be saved.
    layoutChanged = pyqtSignal()
    #: Emitted when edit mode is entered or left.
    editModeChanged = pyqtSignal(bool)
    #: Emitted when the user picks "Control panel" from the context menu.
    panelRequested = pyqtSignal()
    #: Emitted when the user picks "Quit" from the context menu.
    quitRequested = pyqtSignal()

    def __init__(
        self,
        profile: Profile,
        controller: WindowController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._profile = profile
        self._controller = controller

        # -- window setup, in the order Qt requires ------------------------
        # Tool keeps it off the taskbar and out of Alt-Tab even before the
        # native controller runs; the translucency attribute must be set here,
        # while the native window still does not exist.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowTitle("OBS Overlay")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

        # -- frame state ---------------------------------------------------
        self._frame: Frame | None = None
        self._image: QImage | None = None
        self._source_info = SourceInfo()
        self._stats = StatsSnapshot()

        # -- mask caching --------------------------------------------------
        self._mask_key: tuple | None = None
        self._cached_region: QRegion | None = None
        self._cached_path: QPainterPath | None = None
        self._path_key: tuple | None = None

        # -- edit mode -----------------------------------------------------
        self._edit_mode = False
        self.editor = ParcelEditor(
            get_parcels=lambda: self._profile.parcels,
            set_parcels=self._set_parcels,
            get_settings=lambda: self._profile.editor,
            parent=self,
        )
        self.editor.parcelsChanged.connect(self._on_parcels_changed)
        self.editor.selectionChanged.connect(self.update)
        self.editor.exitRequested.connect(lambda: self.set_edit_mode(False))

        # -- topmost keep-alive --------------------------------------------
        self._topmost_timer = QTimer(self)
        self._topmost_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._topmost_timer.timeout.connect(self._reassert_topmost)

        self._native_applied = False

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------
    @property
    def profile(self) -> Profile:
        return self._profile

    def apply_profile(self, profile: Profile, move_window: bool = True) -> None:
        """Adopt a profile: geometry, mask, native styles and repaint."""
        self._profile = profile
        self.editor.set_canvas(RectSpec(0, 0, self.width(), self.height()))
        if move_window:
            self.apply_geometry()
        self.invalidate_mask()
        self.apply_behavior()
        self.update()

    def _set_parcels(self, parcels: list[Parcel]) -> None:
        self._profile.parcels = parcels

    def _on_parcels_changed(self) -> None:
        self.invalidate_mask()
        self.update()
        self.layoutChanged.emit()

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------
    def target_screen(self) -> QScreen | None:
        """The screen this overlay should cover, per the display settings."""
        screens = QGuiApplication.screens()
        if not screens:
            return None
        display = self._profile.display
        if display.geometry_mode is GeometryMode.MONITOR:
            index = display.monitor_index
            if 0 <= index < len(screens):
                return screens[index]
            logger.warning(
                "Monitor %d is not connected; falling back to the primary screen.", index
            )
        return QGuiApplication.primaryScreen() or screens[0]

    def target_geometry(self) -> QRect:
        """Where the window should sit, in logical (device-independent) pixels."""
        display = self._profile.display

        if display.geometry_mode is GeometryMode.CUSTOM:
            rect = display.custom_rect
            if rect.width > 0 and rect.height > 0:
                return QRect(rect.x, rect.y, rect.width, rect.height)
            logger.warning("Custom geometry is empty; falling back to the primary screen.")

        if display.geometry_mode is GeometryMode.VIRTUAL:
            combined = QRect()
            for screen in QGuiApplication.screens():
                combined = combined.united(screen.geometry())
            if not combined.isEmpty():
                return combined

        target = self.target_screen()
        if target is None:
            return QRect(0, 0, 1280, 720)
        return target.geometry()

    def apply_geometry(self) -> None:
        rect = self.target_geometry()
        if rect.isEmpty():
            logger.error("Refusing to apply an empty overlay geometry.")
            return
        if self.geometry() != rect:
            self.setGeometry(rect)
        self.editor.set_canvas(RectSpec(0, 0, rect.width(), rect.height()))

    # ------------------------------------------------------------------
    # Masking
    # ------------------------------------------------------------------
    def _mask_signature(self) -> tuple:
        """Everything that can change the mask, so it is rebuilt only then."""
        return (
            self.width(),
            self.height(),
            self._profile.behavior.mask_enabled,
            tuple(
                (
                    p.id,
                    p.x,
                    p.y,
                    p.width,
                    p.height,
                    p.shape.value,
                    p.corner_radius,
                    p.op.value,
                    p.enabled,
                    tuple(p.points),
                )
                for p in self._profile.parcels
            ),
        )

    def invalidate_mask(self) -> None:
        self._mask_key = None
        self._path_key = None
        self._cached_region = None
        self._cached_path = None
        self.refresh_mask()

    def clip_path(self) -> QPainterPath:
        """Painter path covering the parcels, cached between changes."""
        key = self._mask_signature()
        if self._path_key != key or self._cached_path is None:
            self._cached_path = build_path(self._profile.parcels)
            self._path_key = key
        return self._cached_path

    def refresh_mask(self) -> None:
        """Apply (or remove) the window mask.

        Edit mode always clears the mask: the user needs to see and click the
        whole canvas, including the empty space where a parcel might go.
        """
        if self._edit_mode or not self._profile.behavior.mask_enabled:
            if self.mask() != QRegion():
                self.clearMask()
            self._mask_key = None
            return

        key = self._mask_signature()
        if key == self._mask_key and self._cached_region is not None:
            return

        bounds = RectSpec(0, 0, self.width(), self.height())
        region = build_region(self._profile.parcels, bounds)
        self._cached_region = region
        self._mask_key = key
        self.setMask(region)

    # ------------------------------------------------------------------
    # Native behaviour
    # ------------------------------------------------------------------
    def apply_behavior(self) -> None:
        """Push the profile's behaviour flags down to the native window."""
        behavior = self._profile.behavior
        if not self._controller.supported:
            return
        if not self._native_applied and not self._attach_controller():
            return

        # Click-through is suppressed while editing, whatever the profile says
        # — otherwise the editor could not receive a single click.
        self._controller.set_click_through(behavior.click_through and not self._edit_mode)
        self._controller.set_tool_window(behavior.hide_from_taskbar)
        self._controller.set_no_activate(behavior.no_activate and not self._edit_mode)
        self._controller.set_topmost(behavior.always_on_top)
        self._controller.set_excluded_from_capture(behavior.exclude_from_capture)

        interval = behavior.topmost_reassert_ms
        if behavior.always_on_top and interval > 0:
            self._topmost_timer.start(max(250, interval))
        else:
            self._topmost_timer.stop()

    def _attach_controller(self) -> bool:
        handle = int(self.winId())
        if not self._controller.attach(handle):
            return False
        self._native_applied = True
        logger.info("Native window control attached: %s", self._controller.describe())
        return True

    def _reassert_topmost(self) -> None:
        if self.isVisible() and self._profile.behavior.always_on_top:
            self._controller.reassert_topmost()

    # ------------------------------------------------------------------
    # Frames
    # ------------------------------------------------------------------
    def set_frame(self, frame: Frame | None) -> None:
        """Adopt a new frame, releasing the previous one.

        The ``QImage`` is a *view* onto the frame's pooled buffer — no copy —
        so the frame must stay alive for exactly as long as the image is used
        for painting. Ownership of ``frame`` transfers to this widget.
        """
        previous = self._frame
        self._frame = frame

        if frame is None:
            self._image = None
        else:
            image_format = _QIMAGE_FORMATS.get(
                (frame.pixel_format, frame.premultiplied), QImage.Format.Format_RGBA8888
            )
            try:
                # PyQt6's stub types `data` as `bytes`, but the binding accepts
                # any writable buffer and, crucially, does not copy it — the
                # QImage is a view onto the pooled frame, which is the whole
                # point. Verified by mutating the buffer and seeing the change.
                self._image = QImage(  # type: ignore[call-overload]
                    frame.buffer.data,
                    frame.width,
                    frame.height,
                    frame.stride,
                    image_format,
                )
            except Exception:
                logger.exception(
                    "Could not wrap frame %dx%d as a QImage", frame.width, frame.height
                )
                self._image = None
                self._frame = None
                frame.release()

        if previous is not None:
            previous.release()
        self.update()

    def clear_frame(self) -> None:
        self.set_frame(None)

    def set_source_info(self, info: SourceInfo) -> None:
        self._source_info = info
        if info.state is not SourceState.CONNECTED:
            # Stop showing a stale picture from a sender that has gone away.
            self.clear_frame()
        else:
            self.update()

    def set_stats(self, stats: StatsSnapshot) -> None:
        self._stats = stats
        if self._profile.hud.enabled:
            self.update()

    def video_rect(self) -> RectSpec:
        """Where the current frame is drawn inside the window."""
        if self._image is None:
            return RectSpec()
        display = self._profile.display
        return geo.fit_rect(
            self._image.width(),
            self._image.height(),
            RectSpec(0, 0, self.width(), self.height()),
            mode=display.fit_mode,
            anchor=display.anchor,
            zoom=display.zoom,
            offset_x=display.offset_x,
            offset_y=display.offset_y,
        )

    # ------------------------------------------------------------------
    # Edit mode
    # ------------------------------------------------------------------
    @property
    def edit_mode(self) -> bool:
        return self._edit_mode

    def set_edit_mode(self, enabled: bool) -> None:
        if enabled == self._edit_mode:
            return
        self._edit_mode = enabled
        self.refresh_mask()
        self.apply_behavior()

        if enabled:
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
            self.show()
            self.raise_()
            self.activateWindow()
            self.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self.unsetCursor()
            self.editor.clear_selection()

        self.update()
        self.editModeChanged.emit(enabled)
        logger.info("Edit mode %s", "entered" if enabled else "left")

    def toggle_edit_mode(self) -> None:
        self.set_edit_mode(not self._edit_mode)

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(
                QPainter.RenderHint.SmoothPixmapTransform,
                self._profile.display.scale_quality is ScaleQuality.SMOOTH,
            )
            viewport = self.rect()

            if self._edit_mode:
                self._paint_edit_backdrop(painter, viewport)

            if self._image is not None:
                self._paint_video(painter)
            elif self._edit_mode or self._profile.behavior.mask_enabled is False:
                self._paint_placeholder(painter, viewport)

            if self._edit_mode:
                self.editor.paint(painter, viewport)

            paint_hud(
                painter,
                viewport,
                self._profile.hud,
                self._stats,
                self._source_info,
                self._profile.source.target_fps,
            )
        finally:
            painter.end()

    def _paint_edit_backdrop(self, painter: QPainter, viewport: QRect) -> None:
        opacity = self._profile.editor.backdrop_opacity
        if opacity <= 0:
            return
        painter.fillRect(viewport, color(PALETTE.background, int(opacity * 255)))

    def _paint_video(self, painter: QPainter) -> None:
        assert self._image is not None
        destination = self.video_rect()
        if destination.width <= 0 or destination.height <= 0:
            return

        target = QRect(destination.x, destination.y, destination.width, destination.height)
        display = self._profile.display

        painter.save()
        if display.flip_horizontal or display.flip_vertical:
            centre = target.center()
            painter.translate(centre)
            painter.scale(
                -1.0 if display.flip_horizontal else 1.0, -1.0 if display.flip_vertical else 1.0
            )
            painter.translate(-centre)

        if self._edit_mode:
            # Show the whole frame faintly so the user can see what lies
            # outside the parcels, then the parcels at full strength.
            painter.setOpacity(display.opacity * 0.22)
            painter.drawImage(target, self._image)
            painter.setOpacity(display.opacity)
            self._clip_to_parcels(painter)
            painter.drawImage(target, self._image)
        else:
            painter.setOpacity(display.opacity)
            if self._profile.behavior.mask_enabled:
                self._clip_to_parcels(painter)
            painter.drawImage(target, self._image)
        painter.restore()

    def _clip_to_parcels(self, painter: QPainter) -> None:
        """Restrict painting to the parcels.

        A region clip is used when the layout is rectangles only — it is the
        cheap path and the result is identical. Anything else clips to the
        painter path so rounded and elliptical parcels keep their shape.
        """
        parcels = [p for p in self._profile.parcels if p.enabled]
        if not parcels:
            # No parcels means nothing shows; clipping to an empty region is
            # the honest representation of that.
            painter.setClipRect(QRect())
            return
        path = self.clip_path()
        if path.isEmpty():
            painter.setClipRect(QRect())
            return
        painter.setClipPath(path)

    def _paint_placeholder(self, painter: QPainter, viewport: QRect) -> None:
        """ "Waiting for OBS" panel, shown when there is no picture."""
        info = self._source_info
        if info.state is SourceState.ERROR:
            headline = "Source error"
            tint = color(PALETTE.danger)
        else:
            headline = "Waiting for a Spout sender…"
            tint = color(PALETTE.warning)

        lines = [
            info.detail or "Start OBS and add the Spout2 output filter to your scene.",
            f"Expecting sender: {self._profile.source.sender_name or '(any)'}",
        ]

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        font = QFont(painter.font())
        font.setPointSize(13)
        font.setBold(True)
        painter.setFont(font)

        panel = QRect(0, 0, 520, 132)
        panel.moveCenter(viewport.center())

        painter.setPen(QPen(color(PALETTE.border_strong), 1))
        painter.setBrush(QBrush(color(PALETTE.background, 225)))
        painter.drawRoundedRect(panel, 10, 10)

        painter.setPen(QPen(tint))
        painter.drawText(
            panel.adjusted(20, 16, -20, 0),
            int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter),
            headline,
        )

        font.setBold(False)
        font.setPointSize(10)
        painter.setFont(font)
        painter.setPen(QPen(color(PALETTE.text_muted)))
        painter.drawText(
            panel.adjusted(20, 52, -20, -16),
            int(
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap
            ),
            "\n".join(lines),
        )
        painter.restore()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Qt can destroy and recreate the native window (flag changes, screen
        # moves), which loses every ex-style we set. Re-apply on every show.
        self._native_applied = False
        self.apply_behavior()
        self.refresh_mask()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.editor.set_canvas(RectSpec(0, 0, self.width(), self.height()))
        self.invalidate_mask()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self._edit_mode:
            event.ignore()
            return
        if self.editor.mouse_press(event):
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._edit_mode:
            event.ignore()
            return
        if self.editor.mouse_move(event):
            self.update()
        self.setCursor(QCursor(self.editor.cursor_for(event.position().toPoint())))
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if not self._edit_mode:
            event.ignore()
            return
        if self.editor.mouse_release(event):
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._edit_mode and self.editor.key_press(event):
            self.update()
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:
        if not self._edit_mode:
            event.ignore()
            return
        menu = self._build_context_menu(event.pos())
        menu.exec(event.globalPos())
        event.accept()

    def _build_context_menu(self, position: QPoint) -> QMenu:
        menu = QMenu(self)
        editor = self.editor
        has_selection = bool(editor.selection)

        add = menu.addAction("Add parcel here")
        add.triggered.connect(
            lambda: editor.add_parcel(RectSpec(position.x(), position.y(), 320, 180))
        )

        duplicate = menu.addAction("Duplicate\tCtrl+D")
        duplicate.setEnabled(has_selection)
        duplicate.triggered.connect(editor.duplicate_selection)

        delete = menu.addAction("Delete\tDel")
        delete.setEnabled(has_selection)
        delete.triggered.connect(editor.delete_selection)

        menu.addSeparator()
        undo = menu.addAction("Undo\tCtrl+Z")
        undo.setEnabled(editor.can_undo)
        undo.triggered.connect(editor.undo)
        redo = menu.addAction("Redo\tCtrl+Shift+Z")
        redo.setEnabled(editor.can_redo)
        redo.triggered.connect(editor.redo)

        menu.addSeparator()
        order = menu.addMenu("Order")
        order.setEnabled(has_selection)
        order.addAction("Bring to front", lambda: editor.raise_selection(to_top=True))
        order.addAction("Bring forward", lambda: editor.raise_selection())
        order.addAction("Send backward", lambda: editor.lower_selection())
        order.addAction("Send to back", lambda: editor.lower_selection(to_bottom=True))

        align = menu.addMenu("Align")
        align.setEnabled(len(editor.selection) >= 2)
        for label, mode in (
            ("Left", geo.AlignMode.LEFT),
            ("Horizontal centre", geo.AlignMode.H_CENTER),
            ("Right", geo.AlignMode.RIGHT),
            ("Top", geo.AlignMode.TOP),
            ("Vertical centre", geo.AlignMode.V_CENTER),
            ("Bottom", geo.AlignMode.BOTTOM),
        ):
            align.addAction(label, lambda m=mode: editor.align_selection(m))
        align.addSeparator()
        align.addAction("Distribute horizontally", lambda: editor.distribute_selection(True))
        align.addAction("Distribute vertically", lambda: editor.distribute_selection(False))

        menu.addSeparator()
        menu.addAction("Control panel…", self.panelRequested.emit)
        menu.addAction("Leave edit mode\tEsc", lambda: self.set_edit_mode(False))
        return menu

    def closeEvent(self, event) -> None:
        self._topmost_timer.stop()
        self.clear_frame()
        super().closeEvent(event)

    def sizeHint(self) -> QSize:
        rect = self.target_geometry()
        return QSize(rect.width(), rect.height())
