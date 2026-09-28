"""Editor geometry: hit-testing, resizing, snapping, alignment, fitting.

Deliberately free of Qt and of any platform API — every function here is a
pure transformation over :class:`~obs_overlay.config.models.RectSpec` values,
which is what makes the interactive editor testable without a display.

Coordinates are always *canvas* coordinates: logical pixels relative to the
overlay window's top-left corner.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

from ..config.models import Anchor, BooleanOp, FitMode, Parcel, RectSpec, ShapeType
from ..constants import HANDLE_HIT_SLACK, HANDLE_SIZE, MIN_PARCEL_SIZE

# ---------------------------------------------------------------------------
# Rect helpers
# ---------------------------------------------------------------------------


def normalise(rect: RectSpec) -> RectSpec:
    """Return an equivalent rect with non-negative width/height."""
    x, y, width, height = rect.x, rect.y, rect.width, rect.height
    if width < 0:
        x += width
        width = -width
    if height < 0:
        y += height
        height = -height
    return RectSpec(x, y, width, height)


def right(rect: RectSpec) -> int:
    return rect.x + rect.width


def bottom(rect: RectSpec) -> int:
    return rect.y + rect.height


def center_x(rect: RectSpec) -> int:
    return rect.x + rect.width // 2


def center_y(rect: RectSpec) -> int:
    return rect.y + rect.height // 2


def contains_point(rect: RectSpec, px: int, py: int) -> bool:
    return rect.x <= px < right(rect) and rect.y <= py < bottom(rect)


def intersects(a: RectSpec, b: RectSpec) -> bool:
    return not (right(a) <= b.x or right(b) <= a.x or bottom(a) <= b.y or bottom(b) <= a.y)


def intersection(a: RectSpec, b: RectSpec) -> RectSpec:
    """Overlap of two rects; zero-sized when they do not touch."""
    x0 = max(a.x, b.x)
    y0 = max(a.y, b.y)
    x1 = min(right(a), right(b))
    y1 = min(bottom(a), bottom(b))
    if x1 <= x0 or y1 <= y0:
        return RectSpec(x0, y0, 0, 0)
    return RectSpec(x0, y0, x1 - x0, y1 - y0)


def bounding_rect(rects: Sequence[RectSpec]) -> RectSpec:
    """Smallest rect containing all of ``rects`` (empty for an empty input)."""
    if not rects:
        return RectSpec(0, 0, 0, 0)
    x0 = min(r.x for r in rects)
    y0 = min(r.y for r in rects)
    x1 = max(right(r) for r in rects)
    y1 = max(bottom(r) for r in rects)
    return RectSpec(x0, y0, x1 - x0, y1 - y0)


def clamp_rect(rect: RectSpec, bounds: RectSpec, allow_partial: bool = True) -> RectSpec:
    """Keep ``rect`` reachable inside ``bounds``.

    With ``allow_partial`` the rect may hang off the edge as long as a margin
    stays visible, which is what a layout editor wants; otherwise it is pushed
    fully inside.
    """
    if bounds.width <= 0 or bounds.height <= 0:
        return rect
    if allow_partial:
        margin = max(MIN_PARCEL_SIZE, min(48, rect.width, rect.height))
        min_x = bounds.x - rect.width + margin
        max_x = right(bounds) - margin
        min_y = bounds.y - rect.height + margin
        max_y = bottom(bounds) - margin
    else:
        min_x = bounds.x
        max_x = max(bounds.x, right(bounds) - rect.width)
        min_y = bounds.y
        max_y = max(bounds.y, bottom(bounds) - rect.height)
    return RectSpec(
        min(max(rect.x, min_x), max_x),
        min(max(rect.y, min_y), max_y),
        rect.width,
        rect.height,
    )


# ---------------------------------------------------------------------------
# Handles
# ---------------------------------------------------------------------------


class Handle(Enum):
    """Which part of a parcel a drag grabbed."""

    NONE = "none"
    BODY = "body"
    TOP_LEFT = "top_left"
    TOP = "top"
    TOP_RIGHT = "top_right"
    RIGHT = "right"
    BOTTOM_RIGHT = "bottom_right"
    BOTTOM = "bottom"
    BOTTOM_LEFT = "bottom_left"
    LEFT = "left"

    # -- edge membership ---------------------------------------------------
    @property
    def moves_left(self) -> bool:
        return self in (Handle.TOP_LEFT, Handle.LEFT, Handle.BOTTOM_LEFT)

    @property
    def moves_right(self) -> bool:
        return self in (Handle.TOP_RIGHT, Handle.RIGHT, Handle.BOTTOM_RIGHT)

    @property
    def moves_top(self) -> bool:
        return self in (Handle.TOP_LEFT, Handle.TOP, Handle.TOP_RIGHT)

    @property
    def moves_bottom(self) -> bool:
        return self in (Handle.BOTTOM_LEFT, Handle.BOTTOM, Handle.BOTTOM_RIGHT)

    @property
    def is_corner(self) -> bool:
        return self in (
            Handle.TOP_LEFT,
            Handle.TOP_RIGHT,
            Handle.BOTTOM_LEFT,
            Handle.BOTTOM_RIGHT,
        )

    @property
    def is_resize(self) -> bool:
        return self not in (Handle.NONE, Handle.BODY)


#: Clockwise from the top-left, which is the order the editor paints them in.
RESIZE_HANDLES: tuple[Handle, ...] = (
    Handle.TOP_LEFT,
    Handle.TOP,
    Handle.TOP_RIGHT,
    Handle.RIGHT,
    Handle.BOTTOM_RIGHT,
    Handle.BOTTOM,
    Handle.BOTTOM_LEFT,
    Handle.LEFT,
)


def handle_center(rect: RectSpec, handle: Handle) -> tuple[int, int]:
    """Centre point of a resize handle on ``rect``."""
    mid_x = rect.x + rect.width // 2
    mid_y = rect.y + rect.height // 2
    x = rect.x if handle.moves_left else right(rect) if handle.moves_right else mid_x
    y = rect.y if handle.moves_top else bottom(rect) if handle.moves_bottom else mid_y
    return x, y


def handle_rect(rect: RectSpec, handle: Handle, size: int = HANDLE_SIZE) -> RectSpec:
    """Screen rect of the handle's grab area."""
    cx, cy = handle_center(rect, handle)
    half = max(1, size // 2)
    return RectSpec(cx - half, cy - half, half * 2, half * 2)


def hit_test_handle(
    rect: RectSpec,
    px: int,
    py: int,
    size: int = HANDLE_SIZE,
    slack: int = HANDLE_HIT_SLACK,
) -> Handle:
    """Which handle (or the body) is under the point.

    Handles win over the body, and corners win over edges, so a click in the
    corner region never starts a move by accident.
    """
    grab = size + slack
    for handle in (
        Handle.TOP_LEFT,
        Handle.TOP_RIGHT,
        Handle.BOTTOM_LEFT,
        Handle.BOTTOM_RIGHT,
        Handle.TOP,
        Handle.BOTTOM,
        Handle.LEFT,
        Handle.RIGHT,
    ):
        area = handle_rect(rect, handle, grab)
        if contains_point(area, px, py):
            return handle
    if contains_point(rect, px, py):
        return Handle.BODY
    return Handle.NONE


def hit_test_parcels(
    parcels: Sequence[Parcel],
    px: int,
    py: int,
    size: int = HANDLE_SIZE,
    slack: int = HANDLE_HIT_SLACK,
    selected_ids: Sequence[str] = (),
) -> tuple[str | None, Handle]:
    """Find the topmost parcel under a point.

    Later parcels are on top, so the list is scanned in reverse. Selected
    parcels are probed first: their handles must stay grabbable even when a
    newer parcel overlaps them.
    """
    selected = set(selected_ids)
    ordered = [p for p in reversed(parcels) if p.id in selected]
    ordered += [p for p in reversed(parcels) if p.id not in selected]

    for parcel in ordered:
        if not parcel.enabled or parcel.locked:
            continue
        handle = hit_test_handle(parcel.rect, px, py, size, slack)
        if handle is not Handle.NONE:
            return parcel.id, handle
    return None, Handle.NONE


# ---------------------------------------------------------------------------
# Resizing
# ---------------------------------------------------------------------------


def resize_rect(
    rect: RectSpec,
    handle: Handle,
    dx: int,
    dy: int,
    min_size: int = MIN_PARCEL_SIZE,
    keep_aspect: bool = False,
    from_center: bool = False,
) -> RectSpec:
    """Apply a drag delta to one handle of ``rect``.

    The opposite edge stays fixed (or the centre does, with ``from_center``).
    Dragging an edge past its opposite clamps at ``min_size`` rather than
    flipping the rect, which keeps the interaction predictable.
    """
    if handle is Handle.BODY:
        return RectSpec(rect.x + dx, rect.y + dy, rect.width, rect.height)
    if not handle.is_resize:
        return rect

    left_edge, top_edge = rect.x, rect.y
    right_edge, bottom_edge = right(rect), bottom(rect)

    if from_center:
        if handle.moves_left:
            left_edge += dx
            right_edge -= dx
        elif handle.moves_right:
            right_edge += dx
            left_edge -= dx
        if handle.moves_top:
            top_edge += dy
            bottom_edge -= dy
        elif handle.moves_bottom:
            bottom_edge += dy
            top_edge -= dy
    else:
        if handle.moves_left:
            left_edge += dx
        elif handle.moves_right:
            right_edge += dx
        if handle.moves_top:
            top_edge += dy
        elif handle.moves_bottom:
            bottom_edge += dy

    # Enforce the minimum size by pushing the *dragged* edge back, so dragging
    # an edge past its opposite clamps instead of flipping the rect.
    if right_edge - left_edge < min_size:
        if from_center:
            mid = (left_edge + right_edge) // 2
            left_edge, right_edge = mid - min_size // 2, mid - min_size // 2 + min_size
        elif handle.moves_left:
            left_edge = right_edge - min_size
        else:
            right_edge = left_edge + min_size
    if bottom_edge - top_edge < min_size:
        if from_center:
            mid = (top_edge + bottom_edge) // 2
            top_edge, bottom_edge = mid - min_size // 2, mid - min_size // 2 + min_size
        elif handle.moves_top:
            top_edge = bottom_edge - min_size
        else:
            bottom_edge = top_edge + min_size

    if keep_aspect and rect.width > 0 and rect.height > 0:
        left_edge, top_edge, right_edge, bottom_edge = _apply_aspect(
            rect, handle, left_edge, top_edge, right_edge, bottom_edge, min_size, from_center
        )

    return RectSpec(left_edge, top_edge, right_edge - left_edge, bottom_edge - top_edge)


def _apply_aspect(
    original: RectSpec,
    handle: Handle,
    left_edge: int,
    top_edge: int,
    right_edge: int,
    bottom_edge: int,
    min_size: int,
    from_center: bool,
) -> tuple[int, int, int, int]:
    """Force a resized rect back onto ``original``'s aspect ratio.

    Constraining the *result* rather than the drag delta is what makes edge
    handles work: dragging the right edge with the ratio locked has to change
    the height too, and there is no ``dy`` in that gesture to carry it.

    The anchor is whatever the drag leaves fixed — the opposite corner or edge,
    or the centre with ``from_center`` — so the shape grows away from the hand.
    """
    aspect = original.width / original.height
    new_width = right_edge - left_edge
    new_height = bottom_edge - top_edge

    if handle.is_corner:
        # Follow whichever axis the user pushed further from the ratio.
        if new_width / aspect >= new_height:
            new_height = round(new_width / aspect)
        else:
            new_width = round(new_height * aspect)
    elif handle.moves_left or handle.moves_right:
        new_height = round(new_width / aspect)
    else:
        new_width = round(new_height * aspect)

    # Scale both axes together so the minimum size never breaks the ratio.
    if new_width < min_size or new_height < min_size:
        scale = max(min_size / max(1, new_width), min_size / max(1, new_height))
        new_width = max(min_size, round(new_width * scale))
        new_height = max(min_size, round(new_height * scale))

    if from_center:
        centre_x = (left_edge + right_edge) // 2
        centre_y = (top_edge + bottom_edge) // 2
        left_edge = centre_x - new_width // 2
        top_edge = centre_y - new_height // 2
    else:
        if handle.moves_left:
            left_edge = right_edge - new_width
        if handle.moves_top:
            top_edge = bottom_edge - new_height

    return left_edge, top_edge, left_edge + new_width, top_edge + new_height


# ---------------------------------------------------------------------------
# Snapping
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SnapGuide:
    """An alignment line the editor draws while a snap is active."""

    vertical: bool
    position: int
    start: int
    end: int

    def extended(self, start: int, end: int) -> SnapGuide:
        return SnapGuide(self.vertical, self.position, min(self.start, start), max(self.end, end))


@dataclass(frozen=True)
class SnapResult:
    """Outcome of a snap query: a delta to apply plus guides to draw."""

    dx: int = 0
    dy: int = 0
    guides: tuple[SnapGuide, ...] = ()

    @property
    def snapped(self) -> bool:
        return self.dx != 0 or self.dy != 0


def snap_to_grid(value: int, grid: int) -> int:
    """Round ``value`` to the nearest multiple of ``grid``."""
    if grid <= 1:
        return value
    return round(value / grid) * grid


@dataclass(frozen=True)
class _Candidate:
    position: int
    span_start: int
    span_end: int


def _target_lines(
    others: Sequence[RectSpec],
    canvas: RectSpec | None,
    use_parcels: bool,
    use_canvas: bool,
) -> tuple[list[_Candidate], list[_Candidate]]:
    """Vertical and horizontal lines worth snapping to."""
    vertical: list[_Candidate] = []
    horizontal: list[_Candidate] = []

    if use_parcels:
        for rect in others:
            for pos in (rect.x, center_x(rect), right(rect)):
                vertical.append(_Candidate(pos, rect.y, bottom(rect)))
            for pos in (rect.y, center_y(rect), bottom(rect)):
                horizontal.append(_Candidate(pos, rect.x, right(rect)))

    if use_canvas and canvas is not None and canvas.width > 0 and canvas.height > 0:
        for pos in (canvas.x, center_x(canvas), right(canvas)):
            vertical.append(_Candidate(pos, canvas.y, bottom(canvas)))
        for pos in (canvas.y, center_y(canvas), bottom(canvas)):
            horizontal.append(_Candidate(pos, canvas.x, right(canvas)))

    return vertical, horizontal


def _best_snap(
    probes: Sequence[int],
    candidates: Sequence[_Candidate],
    threshold: int,
) -> tuple[int, _Candidate | None, int | None]:
    """Smallest delta that brings any probe onto any candidate line."""
    best_delta = 0
    best_distance = threshold + 1
    best_candidate: _Candidate | None = None
    best_probe: int | None = None
    for probe in probes:
        for candidate in candidates:
            distance = abs(candidate.position - probe)
            if distance < best_distance:
                best_distance = distance
                best_delta = candidate.position - probe
                best_candidate = candidate
                best_probe = probe
    if best_distance > threshold:
        return 0, None, None
    return best_delta, best_candidate, best_probe


def compute_snap(
    rect: RectSpec,
    others: Sequence[RectSpec] = (),
    canvas: RectSpec | None = None,
    *,
    grid: int = 0,
    threshold: int = 8,
    snap_to_grid_enabled: bool = False,
    snap_to_parcels: bool = True,
    snap_to_canvas: bool = True,
    probe_left: bool = True,
    probe_right: bool = True,
    probe_top: bool = True,
    probe_bottom: bool = True,
    probe_centers: bool = True,
) -> SnapResult:
    """Find the nudge that aligns ``rect`` with its neighbours or the grid.

    Edge probes are selectable so a resize only snaps the edges it is actually
    moving. Object snapping wins over grid snapping when both are in range,
    because aligning to a neighbour is almost always what the user meant.
    """
    if threshold <= 0:
        return SnapResult()

    probes_x: list[int] = []
    probes_y: list[int] = []
    if probe_left:
        probes_x.append(rect.x)
    if probe_right:
        probes_x.append(right(rect))
    if probe_top:
        probes_y.append(rect.y)
    if probe_bottom:
        probes_y.append(bottom(rect))
    if probe_centers and probe_left and probe_right:
        probes_x.append(center_x(rect))
    if probe_centers and probe_top and probe_bottom:
        probes_y.append(center_y(rect))

    vertical, horizontal = _target_lines(others, canvas, snap_to_parcels, snap_to_canvas)

    dx, vcand, vprobe = _best_snap(probes_x, vertical, threshold)
    dy, hcand, hprobe = _best_snap(probes_y, horizontal, threshold)

    guides: list[SnapGuide] = []
    if vcand is not None and vprobe is not None:
        guides.append(
            SnapGuide(
                vertical=True,
                position=vcand.position,
                start=min(vcand.span_start, rect.y + dy),
                end=max(vcand.span_end, bottom(rect) + dy),
            )
        )
    if hcand is not None and hprobe is not None:
        guides.append(
            SnapGuide(
                vertical=False,
                position=hcand.position,
                start=min(hcand.span_start, rect.x + dx),
                end=max(hcand.span_end, right(rect) + dx),
            )
        )

    # Grid snapping only fills the axes object snapping did not claim.
    if snap_to_grid_enabled and grid > 1:
        if dx == 0 and probe_left:
            grid_dx = snap_to_grid(rect.x, grid) - rect.x
            if abs(grid_dx) <= threshold:
                dx = grid_dx
        if dy == 0 and probe_top:
            grid_dy = snap_to_grid(rect.y, grid) - rect.y
            if abs(grid_dy) <= threshold:
                dy = grid_dy

    return SnapResult(dx=dx, dy=dy, guides=tuple(guides))


def snap_moved_rect(
    rect: RectSpec,
    others: Sequence[RectSpec],
    canvas: RectSpec | None,
    *,
    grid: int,
    threshold: int,
    snap_grid: bool,
    snap_parcels: bool,
    snap_canvas: bool,
) -> tuple[RectSpec, tuple[SnapGuide, ...]]:
    """Snap a rect that is being *moved* (all four edges probe)."""
    result = compute_snap(
        rect,
        others,
        canvas,
        grid=grid,
        threshold=threshold,
        snap_to_grid_enabled=snap_grid,
        snap_to_parcels=snap_parcels,
        snap_to_canvas=snap_canvas,
    )
    return RectSpec(rect.x + result.dx, rect.y + result.dy, rect.width, rect.height), result.guides


def snap_resized_rect(
    rect: RectSpec,
    handle: Handle,
    others: Sequence[RectSpec],
    canvas: RectSpec | None,
    *,
    grid: int,
    threshold: int,
    snap_grid: bool,
    snap_parcels: bool,
    snap_canvas: bool,
    min_size: int = MIN_PARCEL_SIZE,
) -> tuple[RectSpec, tuple[SnapGuide, ...]]:
    """Snap a rect that is being *resized*: only the dragged edges move."""
    result = compute_snap(
        rect,
        others,
        canvas,
        grid=grid,
        threshold=threshold,
        snap_to_grid_enabled=snap_grid,
        snap_to_parcels=snap_parcels,
        snap_to_canvas=snap_canvas,
        probe_left=handle.moves_left,
        probe_right=handle.moves_right,
        probe_top=handle.moves_top,
        probe_bottom=handle.moves_bottom,
        probe_centers=False,
    )
    if not result.snapped:
        return rect, result.guides

    left_edge, top_edge = rect.x, rect.y
    right_edge, bottom_edge = right(rect), bottom(rect)
    if handle.moves_left:
        left_edge += result.dx
    elif handle.moves_right:
        right_edge += result.dx
    if handle.moves_top:
        top_edge += result.dy
    elif handle.moves_bottom:
        bottom_edge += result.dy

    width = max(min_size, right_edge - left_edge)
    height = max(min_size, bottom_edge - top_edge)
    return RectSpec(left_edge, top_edge, width, height), result.guides


# ---------------------------------------------------------------------------
# Align / distribute
# ---------------------------------------------------------------------------


class AlignMode(str, Enum):
    LEFT = "left"
    H_CENTER = "h_center"
    RIGHT = "right"
    TOP = "top"
    V_CENTER = "v_center"
    BOTTOM = "bottom"


def align_rects(
    rects: Sequence[RectSpec],
    mode: AlignMode,
    reference: RectSpec | None = None,
) -> list[RectSpec]:
    """Align rects to each other's bounding box, or to ``reference``."""
    if len(rects) < 2 and reference is None:
        return list(rects)
    frame = reference if reference is not None else bounding_rect(rects)
    result: list[RectSpec] = []
    for rect in rects:
        x, y = rect.x, rect.y
        if mode is AlignMode.LEFT:
            x = frame.x
        elif mode is AlignMode.RIGHT:
            x = right(frame) - rect.width
        elif mode is AlignMode.H_CENTER:
            x = frame.x + (frame.width - rect.width) // 2
        elif mode is AlignMode.TOP:
            y = frame.y
        elif mode is AlignMode.BOTTOM:
            y = bottom(frame) - rect.height
        elif mode is AlignMode.V_CENTER:
            y = frame.y + (frame.height - rect.height) // 2
        result.append(RectSpec(x, y, rect.width, rect.height))
    return result


def distribute_rects(rects: Sequence[RectSpec], horizontal: bool) -> list[RectSpec]:
    """Even out the *gaps* between rects along one axis.

    Distributing gaps (rather than centres) is what users expect when the rects
    have different sizes. The outermost two stay put.
    """
    if len(rects) < 3:
        return list(rects)

    indexed = list(enumerate(rects))
    indexed.sort(key=lambda item: item[1].x if horizontal else item[1].y)
    ordered = [rect for _, rect in indexed]

    first, last = ordered[0], ordered[-1]
    if horizontal:
        span = right(last) - first.x
        occupied = sum(r.width for r in ordered)
    else:
        span = bottom(last) - first.y
        occupied = sum(r.height for r in ordered)

    gap = (span - occupied) / (len(ordered) - 1)
    placed: list[RectSpec] = [first]
    cursor = float(right(first) if horizontal else bottom(first))
    for rect in ordered[1:-1]:
        cursor += gap
        if horizontal:
            placed.append(RectSpec(round(cursor), rect.y, rect.width, rect.height))
            cursor += rect.width
        else:
            placed.append(RectSpec(rect.x, round(cursor), rect.width, rect.height))
            cursor += rect.height
    placed.append(last)

    # Restore the caller's original ordering.
    result: list[RectSpec] = [RectSpec()] * len(rects)
    for (original_index, _), new_rect in zip(indexed, placed):
        result[original_index] = new_rect
    return result


# ---------------------------------------------------------------------------
# Video fitting
# ---------------------------------------------------------------------------


def _anchor_offsets(anchor: Anchor, free_x: int, free_y: int) -> tuple[int, int]:
    left_third = anchor in (Anchor.TOP_LEFT, Anchor.CENTER_LEFT, Anchor.BOTTOM_LEFT)
    right_third = anchor in (Anchor.TOP_RIGHT, Anchor.CENTER_RIGHT, Anchor.BOTTOM_RIGHT)
    top_third = anchor in (Anchor.TOP_LEFT, Anchor.TOP_CENTER, Anchor.TOP_RIGHT)
    bottom_third = anchor in (Anchor.BOTTOM_LEFT, Anchor.BOTTOM_CENTER, Anchor.BOTTOM_RIGHT)

    offset_x = 0 if left_third else free_x if right_third else free_x // 2
    offset_y = 0 if top_third else free_y if bottom_third else free_y // 2
    return offset_x, offset_y


def fit_rect(
    source_width: int,
    source_height: int,
    canvas: RectSpec,
    mode: FitMode = FitMode.CONTAIN,
    anchor: Anchor = Anchor.CENTER,
    zoom: float = 1.0,
    offset_x: int = 0,
    offset_y: int = 0,
) -> RectSpec:
    """Where to draw a ``source_width`` × ``source_height`` frame on ``canvas``.

    ``FitMode.NONE`` is the blueprint's 1:1 behaviour — no scaling at all, so
    the video never distorts and the mask alone decides what is visible.
    """
    if source_width <= 0 or source_height <= 0 or canvas.width <= 0 or canvas.height <= 0:
        return RectSpec(canvas.x, canvas.y, 0, 0)

    zoom = max(0.01, zoom)

    if mode is FitMode.STRETCH:
        width = max(1, round(canvas.width * zoom))
        height = max(1, round(canvas.height * zoom))
    else:
        if mode is FitMode.NONE:
            scale = 1.0
        elif mode is FitMode.COVER:
            scale = max(canvas.width / source_width, canvas.height / source_height)
        else:  # CONTAIN
            scale = min(canvas.width / source_width, canvas.height / source_height)
        scale *= zoom
        width = max(1, round(source_width * scale))
        height = max(1, round(source_height * scale))

    anchor_x, anchor_y = _anchor_offsets(anchor, canvas.width - width, canvas.height - height)
    return RectSpec(canvas.x + anchor_x + offset_x, canvas.y + anchor_y + offset_y, width, height)


def map_point_to_source(
    point: tuple[int, int],
    destination: RectSpec,
    source_width: int,
    source_height: int,
) -> tuple[int, int] | None:
    """Inverse of :func:`fit_rect` for a single point.

    Returns ``None`` when the point falls outside the drawn video, which the
    HUD uses to report the pixel under the cursor.
    """
    if destination.width <= 0 or destination.height <= 0:
        return None
    if not contains_point(destination, point[0], point[1]):
        return None
    rel_x = (point[0] - destination.x) / destination.width
    rel_y = (point[1] - destination.y) / destination.height
    return (
        min(source_width - 1, max(0, int(rel_x * source_width))),
        min(source_height - 1, max(0, int(rel_y * source_height))),
    )


# ---------------------------------------------------------------------------
# Coverage (safety guard)
# ---------------------------------------------------------------------------


def covered_area(parcels: Sequence[Parcel], bounds: RectSpec) -> int:
    """Exact area of ``bounds`` covered by the parcel stack, in pixels².

    Uses coordinate compression: every parcel edge becomes a grid line, and
    each resulting cell is uniformly inside or outside a given parcel, so the
    union/subtract stack can be evaluated cell by cell. Exact for rectangles;
    ellipses and polygons are approximated by their bounding box, which
    over-estimates and therefore keeps the safety guard on the cautious side.
    """
    if bounds.width <= 0 or bounds.height <= 0:
        return 0

    active = [p for p in parcels if p.enabled]
    if not active:
        return 0

    clipped: list[tuple[RectSpec, BooleanOp]] = []
    for parcel in active:
        rect = intersection(parcel.rect, bounds)
        if rect.width > 0 and rect.height > 0:
            clipped.append((rect, parcel.op))
    if not clipped:
        return 0

    xs = sorted({bounds.x, right(bounds), *(v for r, _ in clipped for v in (r.x, right(r)))})
    ys = sorted({bounds.y, bottom(bounds), *(v for r, _ in clipped for v in (r.y, bottom(r)))})
    xs = [v for v in xs if bounds.x <= v <= right(bounds)]
    ys = [v for v in ys if bounds.y <= v <= bottom(bounds)]
    if len(xs) < 2 or len(ys) < 2:
        return 0

    total = 0
    for row in range(len(ys) - 1):
        y0, y1 = ys[row], ys[row + 1]
        cell_height = y1 - y0
        if cell_height <= 0:
            continue
        for col in range(len(xs) - 1):
            x0, x1 = xs[col], xs[col + 1]
            cell_width = x1 - x0
            if cell_width <= 0:
                continue
            inside = False
            # Later parcels win, exactly as the mask builder composes them.
            for rect, op in clipped:
                if rect.x <= x0 and x1 <= right(rect) and rect.y <= y0 and y1 <= bottom(rect):
                    inside = op is BooleanOp.UNION
            if inside:
                total += cell_width * cell_height
    return total


def coverage_ratio(parcels: Sequence[Parcel], bounds: RectSpec) -> float:
    """Fraction of ``bounds`` (0..1) the parcels cover."""
    area = bounds.width * bounds.height
    if area <= 0:
        return 0.0
    return min(1.0, covered_area(parcels, bounds) / area)


def is_unsafe_layout(
    parcels: Sequence[Parcel],
    bounds: RectSpec,
    click_through: bool,
    opacity: float,
    threshold: float = 0.92,
) -> bool:
    """True when the overlay would trap the user's input.

    A nearly full-screen, nearly opaque window that still accepts clicks would
    swallow every interaction with the desktop behind it — and with
    click-through off, the user could not get to the tray icon to fix it.
    """
    if click_through:
        return False
    if opacity < 0.5:
        return False
    return coverage_ratio(parcels, bounds) >= threshold


# ---------------------------------------------------------------------------
# Layout generators (used by the "quick layout" menu)
# ---------------------------------------------------------------------------


def grid_layout(
    bounds: RectSpec,
    columns: int,
    rows: int,
    gap: int = 16,
    margin: int = 48,
) -> list[RectSpec]:
    """Evenly spaced ``columns`` × ``rows`` grid inside ``bounds``."""
    columns = max(1, columns)
    rows = max(1, rows)
    inner_width = bounds.width - 2 * margin - gap * (columns - 1)
    inner_height = bounds.height - 2 * margin - gap * (rows - 1)
    if inner_width <= 0 or inner_height <= 0:
        return []
    cell_width = inner_width // columns
    cell_height = inner_height // rows
    if cell_width < MIN_PARCEL_SIZE or cell_height < MIN_PARCEL_SIZE:
        return []
    return [
        RectSpec(
            bounds.x + margin + col * (cell_width + gap),
            bounds.y + margin + row * (cell_height + gap),
            cell_width,
            cell_height,
        )
        for row in range(rows)
        for col in range(columns)
    ]


def rects_to_parcels(
    rects: Iterable[RectSpec],
    shape: ShapeType = ShapeType.RECT,
    corner_radius: int = 16,
    name_prefix: str = "Parcel",
) -> list[Parcel]:
    """Wrap plain rects into parcels, numbered for the parcel table."""
    return [
        Parcel(
            name=f"{name_prefix} {index + 1}",
            x=rect.x,
            y=rect.y,
            width=rect.width,
            height=rect.height,
            shape=shape,
            corner_radius=corner_radius,
        )
        for index, rect in enumerate(rects)
    ]
