"""Interactive parcel editing on the overlay itself.

This is the state machine behind Phase 4 of the blueprint: dragging, resizing,
snapping, multi-select and undo. It owns no widgets — the overlay window feeds
it events and asks it to paint — which keeps the interaction logic separate
from the compositing logic and makes it straightforward to reason about.

Coordinates are overlay-window logical pixels throughout.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Callable

from PyQt6.QtCore import QObject, QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
)

from ..config.models import BooleanOp, EditorSettings, Parcel, RectSpec
from ..constants import HANDLE_SIZE, MIN_PARCEL_SIZE
from ..core import geometry as geo
from ..core.geometry import Handle, SnapGuide
from ..core.mask import parcel_path
from .theme import PALETTE, color

logger = logging.getLogger(__name__)

#: How many layout states the undo stack keeps.
_UNDO_DEPTH = 64


class DragMode:
    NONE = "none"
    MOVE = "move"
    RESIZE = "resize"
    RUBBER_BAND = "rubber_band"
    CREATE = "create"


@dataclass
class _DragState:
    mode: str = DragMode.NONE
    handle: Handle = Handle.NONE
    origin: QPoint = None  # type: ignore[assignment]
    start_rects: tuple[tuple[str, RectSpec], ...] = ()
    anchor_id: str = ""
    moved: bool = False


class ParcelEditor(QObject):
    """Edits a list of parcels in response to mouse and keyboard input."""

    #: Emitted whenever the parcel list changes and should be persisted.
    parcelsChanged = pyqtSignal()
    #: Emitted when the selection changes (the control panel mirrors it).
    selectionChanged = pyqtSignal()
    #: Emitted when the user asks to leave edit mode (Escape).
    exitRequested = pyqtSignal()

    def __init__(
        self,
        get_parcels: Callable[[], list[Parcel]],
        set_parcels: Callable[[list[Parcel]], None],
        get_settings: Callable[[], EditorSettings],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._get_parcels = get_parcels
        self._set_parcels = set_parcels
        self._get_settings = get_settings

        self._selection: set[str] = set()
        self._hover_id: str = ""
        self._hover_handle: Handle = Handle.NONE
        self._drag = _DragState()
        self._guides: tuple[SnapGuide, ...] = ()
        self._rubber_band: RectSpec | None = None
        self._canvas = RectSpec()
        self._undo: list[list[Parcel]] = []
        self._redo: list[list[Parcel]] = []

    # -- state -------------------------------------------------------------
    @property
    def selection(self) -> list[str]:
        return [p.id for p in self._get_parcels() if p.id in self._selection]

    @property
    def canvas(self) -> RectSpec:
        return self._canvas

    def set_canvas(self, rect: RectSpec) -> None:
        self._canvas = rect

    def set_selection(self, ids: Iterable[str]) -> None:
        new = set(ids)
        if new != self._selection:
            self._selection = new
            self.selectionChanged.emit()

    def clear_selection(self) -> None:
        self.set_selection([])

    def select_all(self) -> None:
        self.set_selection([p.id for p in self._get_parcels() if not p.locked])

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    # -- undo --------------------------------------------------------------
    def _snapshot(self) -> None:
        """Record the current layout so the next change can be undone."""
        self._undo.append([replace(p, points=list(p.points)) for p in self._get_parcels()])
        if len(self._undo) > _UNDO_DEPTH:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self) -> bool:
        if not self._undo:
            return False
        current = [replace(p, points=list(p.points)) for p in self._get_parcels()]
        self._redo.append(current)
        self._set_parcels(self._undo.pop())
        self._prune_selection()
        self.parcelsChanged.emit()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        current = [replace(p, points=list(p.points)) for p in self._get_parcels()]
        self._undo.append(current)
        self._set_parcels(self._redo.pop())
        self._prune_selection()
        self.parcelsChanged.emit()
        return True

    def _prune_selection(self) -> None:
        live = {p.id for p in self._get_parcels()}
        pruned = self._selection & live
        if pruned != self._selection:
            self._selection = pruned
            self.selectionChanged.emit()

    # -- editing commands --------------------------------------------------
    def add_parcel(self, rect: RectSpec | None = None) -> Parcel:
        """Add a parcel, centred on the canvas when no rect is given."""
        if rect is None:
            width = max(MIN_PARCEL_SIZE, min(480, max(MIN_PARCEL_SIZE, self._canvas.width // 3)))
            height = max(MIN_PARCEL_SIZE, min(270, max(MIN_PARCEL_SIZE, self._canvas.height // 3)))
            rect = RectSpec(
                self._canvas.x + (self._canvas.width - width) // 2,
                self._canvas.y + (self._canvas.height - height) // 2,
                width,
                height,
            )
        self._snapshot()
        parcels = self._get_parcels()
        parcel = Parcel(
            name=f"Parcel {len(parcels) + 1}",
            x=rect.x,
            y=rect.y,
            width=max(MIN_PARCEL_SIZE, rect.width),
            height=max(MIN_PARCEL_SIZE, rect.height),
        )
        parcels.append(parcel)
        self._set_parcels(parcels)
        self.set_selection([parcel.id])
        self.parcelsChanged.emit()
        return parcel

    def duplicate_selection(self) -> None:
        selected = [p for p in self._get_parcels() if p.id in self._selection]
        if not selected:
            return
        self._snapshot()
        parcels = self._get_parcels()
        clones = [p.clone() for p in selected]
        parcels.extend(clones)
        self._set_parcels(parcels)
        self.set_selection([c.id for c in clones])
        self.parcelsChanged.emit()

    def delete_selection(self) -> None:
        if not self._selection:
            return
        parcels = [p for p in self._get_parcels() if p.id not in self._selection or p.locked]
        if len(parcels) == len(self._get_parcels()):
            return
        self._snapshot()
        self._set_parcels(parcels)
        self.clear_selection()
        self.parcelsChanged.emit()

    def nudge_selection(self, dx: int, dy: int) -> None:
        if not self._selection or (dx == 0 and dy == 0):
            return
        self._snapshot()
        parcels = self._get_parcels()
        for index, parcel in enumerate(parcels):
            if parcel.id in self._selection and not parcel.locked:
                parcels[index] = parcel.moved(dx, dy)
        self._set_parcels(parcels)
        self.parcelsChanged.emit()

    def apply_to_selection(self, **changes: object) -> None:
        """Set the same field(s) on every selected parcel."""
        if not self._selection:
            return
        self._snapshot()
        parcels = self._get_parcels()
        for index, parcel in enumerate(parcels):
            if parcel.id in self._selection:
                parcels[index] = replace(parcel, **changes)  # type: ignore[arg-type]
        self._set_parcels(parcels)
        self.parcelsChanged.emit()

    def align_selection(self, mode: geo.AlignMode) -> None:
        selected = [p for p in self._get_parcels() if p.id in self._selection and not p.locked]
        if len(selected) < 2:
            return
        self._snapshot()
        aligned = geo.align_rects([p.rect for p in selected], mode)
        mapping = {p.id: rect for p, rect in zip(selected, aligned)}
        self._replace_rects(mapping)

    def distribute_selection(self, horizontal: bool) -> None:
        selected = [p for p in self._get_parcels() if p.id in self._selection and not p.locked]
        if len(selected) < 3:
            return
        self._snapshot()
        spread = geo.distribute_rects([p.rect for p in selected], horizontal)
        mapping = {p.id: rect for p, rect in zip(selected, spread)}
        self._replace_rects(mapping)

    def _replace_rects(self, mapping: dict) -> None:
        parcels = self._get_parcels()
        for index, parcel in enumerate(parcels):
            rect = mapping.get(parcel.id)
            if rect is not None:
                parcels[index] = parcel.with_rect(rect)
        self._set_parcels(parcels)
        self.parcelsChanged.emit()

    def raise_selection(self, to_top: bool = False) -> None:
        self._reorder(+1, to_end=to_top)

    def lower_selection(self, to_bottom: bool = False) -> None:
        self._reorder(-1, to_end=to_bottom)

    def _reorder(self, direction: int, to_end: bool) -> None:
        parcels = self._get_parcels()
        if not self._selection or len(parcels) < 2:
            return
        self._snapshot()
        selected = [p for p in parcels if p.id in self._selection]
        others = [p for p in parcels if p.id not in self._selection]
        if to_end:
            parcels = (others + selected) if direction > 0 else (selected + others)
        else:
            parcels = list(parcels)
            indices = [i for i, p in enumerate(parcels) if p.id in self._selection]
            order = reversed(indices) if direction > 0 else indices
            for index in order:
                target = index + direction
                if 0 <= target < len(parcels) and parcels[target].id not in self._selection:
                    parcels[index], parcels[target] = parcels[target], parcels[index]
        self._set_parcels(parcels)
        self.parcelsChanged.emit()

    # -- mouse -------------------------------------------------------------
    def mouse_press(self, event: QMouseEvent) -> bool:
        point = event.position().toPoint()
        modifiers = event.modifiers()

        if event.button() == Qt.MouseButton.RightButton:
            return False  # let the window show a context menu

        if event.button() != Qt.MouseButton.LeftButton:
            return False

        parcels = self._get_parcels()
        hit_id, handle = geo.hit_test_parcels(
            parcels, point.x(), point.y(), HANDLE_SIZE, selected_ids=self.selection
        )

        # Ctrl+drag on empty space draws a brand new parcel.
        if hit_id is None and modifiers & Qt.KeyboardModifier.ControlModifier:
            self._snapshot()
            self._drag = _DragState(
                mode=DragMode.CREATE,
                origin=point,
                start_rects=(),
            )
            self._rubber_band = RectSpec(point.x(), point.y(), 0, 0)
            return True

        if hit_id is None:
            if not (modifiers & Qt.KeyboardModifier.ShiftModifier):
                self.clear_selection()
            self._drag = _DragState(mode=DragMode.RUBBER_BAND, origin=point)
            self._rubber_band = RectSpec(point.x(), point.y(), 0, 0)
            return True

        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            selection = set(self._selection)
            selection.symmetric_difference_update({hit_id})
            self.set_selection(selection)
        elif hit_id not in self._selection:
            self.set_selection([hit_id])

        if not self._selection:
            return True

        self._snapshot()
        moving = [p for p in parcels if p.id in self._selection and not p.locked]
        self._drag = _DragState(
            mode=DragMode.RESIZE if handle.is_resize else DragMode.MOVE,
            handle=handle,
            origin=point,
            start_rects=tuple((p.id, p.rect) for p in moving),
            anchor_id=hit_id,
        )
        return True

    def mouse_move(self, event: QMouseEvent) -> bool:
        point = event.position().toPoint()

        if self._drag.mode == DragMode.NONE:
            return self._update_hover(point)

        dx = point.x() - self._drag.origin.x()
        dy = point.y() - self._drag.origin.y()
        if dx or dy:
            self._drag.moved = True

        if self._drag.mode in (DragMode.RUBBER_BAND, DragMode.CREATE):
            self._rubber_band = geo.normalise(
                RectSpec(self._drag.origin.x(), self._drag.origin.y(), dx, dy)
            )
            if self._drag.mode == DragMode.RUBBER_BAND:
                self._select_within(
                    self._rubber_band,
                    additive=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
                )
            return True

        if self._drag.mode == DragMode.MOVE:
            self._apply_move(dx, dy)
            return True

        if self._drag.mode == DragMode.RESIZE:
            self._apply_resize(dx, dy, event.modifiers())
            return True

        return False

    def mouse_release(self, event: QMouseEvent) -> bool:
        if self._drag.mode == DragMode.NONE:
            return False

        mode = self._drag.mode
        band = self._rubber_band
        moved = self._drag.moved

        self._drag = _DragState()
        self._guides = ()
        self._rubber_band = None

        if mode == DragMode.CREATE and band is not None:
            if band.width >= MIN_PARCEL_SIZE and band.height >= MIN_PARCEL_SIZE:
                parcels = self._get_parcels()
                parcel = Parcel(
                    name=f"Parcel {len(parcels) + 1}",
                    x=band.x,
                    y=band.y,
                    width=band.width,
                    height=band.height,
                )
                parcels.append(parcel)
                self._set_parcels(parcels)
                self.set_selection([parcel.id])
                self.parcelsChanged.emit()
            else:
                # Too small to be intentional; undo the snapshot we took.
                if self._undo:
                    self._undo.pop()
            return True

        if mode in (DragMode.MOVE, DragMode.RESIZE):
            if moved:
                self.parcelsChanged.emit()
            elif self._undo:
                # A click that did not move anything should not cost an undo.
                self._undo.pop()
            return True

        return True

    def _update_hover(self, point: QPoint) -> bool:
        hit_id, handle = geo.hit_test_parcels(
            self._get_parcels(), point.x(), point.y(), HANDLE_SIZE, selected_ids=self.selection
        )
        changed = (hit_id or "") != self._hover_id or handle is not self._hover_handle
        self._hover_id = hit_id or ""
        self._hover_handle = handle
        return changed

    def _select_within(self, band: RectSpec, additive: bool) -> None:
        inside = {
            p.id for p in self._get_parcels() if not p.locked and geo.intersects(p.rect, band)
        }
        self.set_selection(inside | self._selection if additive else inside)

    # -- drag maths --------------------------------------------------------
    def _snap_context(self) -> tuple[list[RectSpec], EditorSettings]:
        settings = self._get_settings()
        moving_ids = {pid for pid, _ in self._drag.start_rects}
        others = [p.rect for p in self._get_parcels() if p.id not in moving_ids and p.enabled]
        return others, settings

    def _apply_move(self, dx: int, dy: int) -> None:
        if not self._drag.start_rects:
            return
        others, settings = self._snap_context()

        rects = [rect for _, rect in self._drag.start_rects]
        group = geo.bounding_rect(rects)
        moved_group = RectSpec(group.x + dx, group.y + dy, group.width, group.height)

        snapped, guides = geo.snap_moved_rect(
            moved_group,
            others,
            self._canvas,
            grid=settings.grid_size,
            threshold=settings.snap_threshold,
            snap_grid=settings.snap_to_grid,
            snap_parcels=settings.snap_to_parcels,
            snap_canvas=settings.snap_to_canvas,
        )
        self._guides = guides
        total_dx = snapped.x - group.x
        total_dy = snapped.y - group.y

        parcels = self._get_parcels()
        starts = dict(self._drag.start_rects)
        for index, parcel in enumerate(parcels):
            start = starts.get(parcel.id)
            if start is None:
                continue
            parcels[index] = parcel.with_rect(
                RectSpec(start.x + total_dx, start.y + total_dy, start.width, start.height)
            )
        self._set_parcels(parcels)

    def _apply_resize(self, dx: int, dy: int, modifiers: Qt.KeyboardModifier) -> None:
        if not self._drag.start_rects:
            return
        others, settings = self._snap_context()
        keep_aspect = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        from_center = bool(modifiers & Qt.KeyboardModifier.AltModifier)

        parcels = self._get_parcels()
        starts = dict(self._drag.start_rects)
        guides: tuple[SnapGuide, ...] = ()

        for index, parcel in enumerate(parcels):
            start = starts.get(parcel.id)
            if start is None:
                continue
            resized = geo.resize_rect(
                start,
                self._drag.handle,
                dx,
                dy,
                min_size=MIN_PARCEL_SIZE,
                keep_aspect=keep_aspect,
                from_center=from_center,
            )
            # Only the parcel under the cursor drives snapping; applying each
            # parcel's own snap would tear a multi-selection apart.
            if parcel.id == self._drag.anchor_id:
                resized, guides = geo.snap_resized_rect(
                    resized,
                    self._drag.handle,
                    others,
                    self._canvas,
                    grid=settings.grid_size,
                    threshold=settings.snap_threshold,
                    snap_grid=settings.snap_to_grid,
                    snap_parcels=settings.snap_to_parcels,
                    snap_canvas=settings.snap_to_canvas,
                )
            parcels[index] = parcel.with_rect(resized)

        self._guides = guides
        self._set_parcels(parcels)

    # -- keyboard ----------------------------------------------------------
    def key_press(self, event: QKeyEvent) -> bool:
        key = event.key()
        modifiers = event.modifiers()
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        settings = self._get_settings()

        if key == Qt.Key.Key_Escape:
            if self._selection:
                self.clear_selection()
            else:
                self.exitRequested.emit()
            return True

        if ctrl and key == Qt.Key.Key_Z:
            return self.redo() if shift else self.undo()
        if ctrl and key == Qt.Key.Key_Y:
            return self.redo()
        if ctrl and key == Qt.Key.Key_A:
            self.select_all()
            return True
        if ctrl and key == Qt.Key.Key_D:
            self.duplicate_selection()
            return True
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selection()
            return True

        step = settings.grid_size if shift else 1
        # Keyed by int, not Qt.Key: QKeyEvent.key() returns a plain int, and
        # Qt.Key is an IntEnum, so the two hash alike and the lookup works.
        deltas: dict[int, tuple[int, int]] = {
            Qt.Key.Key_Left: (-step, 0),
            Qt.Key.Key_Right: (step, 0),
            Qt.Key.Key_Up: (0, -step),
            Qt.Key.Key_Down: (0, step),
        }
        if key in deltas:
            self.nudge_selection(*deltas[key])
            return True

        if ctrl and key == Qt.Key.Key_BracketRight:
            self.raise_selection(to_top=shift)
            return True
        if ctrl and key == Qt.Key.Key_BracketLeft:
            self.lower_selection(to_bottom=shift)
            return True

        return False

    def cursor_for(self, point: QPoint) -> Qt.CursorShape:
        """Cursor that communicates what a drag from ``point`` would do."""
        _, handle = geo.hit_test_parcels(
            self._get_parcels(), point.x(), point.y(), HANDLE_SIZE, selected_ids=self.selection
        )
        return {
            Handle.TOP_LEFT: Qt.CursorShape.SizeFDiagCursor,
            Handle.BOTTOM_RIGHT: Qt.CursorShape.SizeFDiagCursor,
            Handle.TOP_RIGHT: Qt.CursorShape.SizeBDiagCursor,
            Handle.BOTTOM_LEFT: Qt.CursorShape.SizeBDiagCursor,
            Handle.TOP: Qt.CursorShape.SizeVerCursor,
            Handle.BOTTOM: Qt.CursorShape.SizeVerCursor,
            Handle.LEFT: Qt.CursorShape.SizeHorCursor,
            Handle.RIGHT: Qt.CursorShape.SizeHorCursor,
            Handle.BODY: Qt.CursorShape.SizeAllCursor,
        }.get(handle, Qt.CursorShape.CrossCursor)

    # -- painting ----------------------------------------------------------
    def paint(self, painter: QPainter, viewport: QRect) -> None:
        """Draw every editing affordance on top of the video."""
        settings = self._get_settings()
        parcels = self._get_parcels()
        selection = self._selection

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if settings.show_grid and settings.grid_size > 2:
            self._paint_grid(painter, viewport, settings.grid_size)

        # Canvas boundary, so the physical window extent is unmistakable.
        painter.setPen(QPen(color(PALETTE.text_muted, 110), 1, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(viewport.adjusted(0, 0, -1, -1))

        for parcel in parcels:
            self._paint_parcel(painter, parcel, parcel.id in selection, settings)

        for guide in self._guides:
            self._paint_guide(painter, guide, viewport)

        if self._rubber_band is not None:
            creating = self._drag.mode == DragMode.CREATE
            tint = color(PALETTE.accent if creating else PALETTE.text_muted)
            painter.setPen(QPen(tint, 1, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(color(PALETTE.accent, 40)))
            painter.drawRect(
                QRect(
                    self._rubber_band.x,
                    self._rubber_band.y,
                    self._rubber_band.width,
                    self._rubber_band.height,
                )
            )

        painter.restore()

    def _paint_grid(self, painter: QPainter, viewport: QRect, step: int) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(color(PALETTE.grid, 26), 1))
        # A coarse multiple stays legible; drawing every line at step=4 would
        # be a grey wash and thousands of draw calls.
        effective = step if step >= 16 else step * max(1, 16 // step)
        x = viewport.left() - (viewport.left() % effective)
        while x < viewport.right():
            painter.drawLine(x, viewport.top(), x, viewport.bottom())
            x += effective
        y = viewport.top() - (viewport.top() % effective)
        while y < viewport.bottom():
            painter.drawLine(viewport.left(), y, viewport.right(), y)
            y += effective
        painter.restore()

    def _paint_parcel(
        self,
        painter: QPainter,
        parcel: Parcel,
        selected: bool,
        settings: EditorSettings,
    ) -> None:
        if parcel.op is BooleanOp.SUBTRACT:
            outline = color(PALETTE.subtract_outline)
        elif parcel.locked:
            outline = color(PALETTE.parcel_outline_locked)
        elif selected:
            outline = color(PALETTE.parcel_outline_selected)
        else:
            outline = color(PALETTE.parcel_outline)

        if not parcel.enabled:
            outline.setAlpha(90)

        path = parcel_path(parcel)

        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color(PALETTE.parcel_fill_selected, 28)))
            painter.drawPath(path)

        style = Qt.PenStyle.SolidLine
        if parcel.op is BooleanOp.SUBTRACT or not parcel.enabled:
            style = Qt.PenStyle.DashLine
        painter.setPen(QPen(outline, 2 if selected else 1.5, style))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        if settings.show_labels:
            self._paint_label(painter, parcel, outline)

        if selected and not parcel.locked:
            self._paint_handles(painter, parcel.rect)

    def _paint_label(self, painter: QPainter, parcel: Parcel, tint: QColor) -> None:
        font = QFont(painter.font())
        font.setPointSizeF(max(8.0, font.pointSizeF()))
        font.setBold(True)
        painter.setFont(font)

        text = parcel.display_name
        detail = f"{parcel.width}×{parcel.height}"
        metrics = QFontMetrics(font)
        width = max(metrics.horizontalAdvance(text), metrics.horizontalAdvance(detail)) + 14
        height = metrics.height() * 2 + 8

        # Keep the badge inside the canvas even for a parcel at the top edge.
        badge_y = parcel.y - height - 6
        if badge_y < self._canvas.y:
            badge_y = parcel.y + 6
        badge = QRect(parcel.x, badge_y, width, height)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color(PALETTE.background, 205)))
        painter.drawRoundedRect(badge, 5, 5)
        painter.setPen(QPen(tint))
        painter.drawText(
            badge.adjusted(7, 4, -7, -4),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
            text,
        )
        painter.setPen(QPen(color(PALETTE.text_muted)))
        painter.drawText(
            badge.adjusted(7, 4, -7, -4),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom),
            detail,
        )

    def _paint_handles(self, painter: QPainter, rect: RectSpec) -> None:
        painter.setPen(QPen(color(PALETTE.handle_border), 1.2))
        painter.setBrush(QBrush(color(PALETTE.handle_fill)))
        for handle in geo.RESIZE_HANDLES:
            box = geo.handle_rect(rect, handle, HANDLE_SIZE)
            painter.drawRoundedRect(QRect(box.x, box.y, box.width, box.height), 2, 2)

    def _paint_guide(self, painter: QPainter, guide: SnapGuide, viewport: QRect) -> None:
        painter.setPen(QPen(color(PALETTE.guide), 1, Qt.PenStyle.DashLine))
        if guide.vertical:
            painter.drawLine(guide.position, guide.start - 12, guide.position, guide.end + 12)
        else:
            painter.drawLine(guide.start - 12, guide.position, guide.end + 12, guide.position)
