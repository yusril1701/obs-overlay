"""Turning parcels into a window mask and a painting clip path.

Two related but deliberately different products come out of the same parcel
list:

``build_path``
    A :class:`QPainterPath` used to *clip the painting*. Antialiased, so
    rounded and elliptical parcels get smooth edges.
``build_region``
    A :class:`QRegion` handed to ``QWidget.setMask``. Masks are 1-bit — Windows
    either keeps a pixel or discards it — so this is the jagged approximation
    that defines the window's physical shape and therefore its hit-testing.

The region is grown by a pixel relative to the path so the mask never clips
the antialiased edge the painter produced; the result is a soft edge over
whatever is behind the overlay rather than a hard staircase.

Rectangle-only layouts take a fast path that composes ``QRegion`` objects
directly: a handful of rectangles instead of the scanline decomposition a
bitmap round-trip would produce, which matters because Windows walks that list
on every hit test.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QBitmap, QImage, QPainter, QPainterPath, QPolygonF, QRegion

from ..config.models import BooleanOp, Parcel, RectSpec, ShapeType

logger = logging.getLogger(__name__)

#: Bitmap masks above this many pixels are refused; a huge virtual desktop
#: would otherwise allocate an unreasonable temporary.
_MAX_MASK_PIXELS = 64_000_000


def to_qrect(rect: RectSpec) -> QRect:
    return QRect(rect.x, rect.y, rect.width, rect.height)


def from_qrect(rect: QRect) -> RectSpec:
    return RectSpec(rect.x(), rect.y(), rect.width(), rect.height())


def _clamped_radius(parcel: Parcel) -> float:
    """Corner radius that cannot exceed half the smaller side."""
    return float(max(0, min(parcel.corner_radius, parcel.width // 2, parcel.height // 2)))


def parcel_path(parcel: Parcel) -> QPainterPath:
    """The outline of a single parcel as a painter path."""
    path = QPainterPath()
    rect = QRectF(float(parcel.x), float(parcel.y), float(parcel.width), float(parcel.height))

    if parcel.shape is ShapeType.ELLIPSE:
        path.addEllipse(rect)
    elif parcel.shape is ShapeType.ROUNDED_RECT:
        radius = _clamped_radius(parcel)
        if radius <= 0:
            path.addRect(rect)
        else:
            path.addRoundedRect(rect, radius, radius)
    elif parcel.shape is ShapeType.POLYGON:
        # Vertices are stored as fractions of the bounding box, so moving or
        # resizing a polygon parcel needs no per-vertex bookkeeping.
        points = [
            QPointF(parcel.x + fx * parcel.width, parcel.y + fy * parcel.height)
            for fx, fy in parcel.effective_points()
        ]
        path.addPolygon(QPolygonF(points))
        path.closeSubpath()
    else:
        path.addRect(rect)

    return path


def build_path(parcels: Sequence[Parcel]) -> QPainterPath:
    """Combined outline of every enabled parcel.

    Parcels compose in list order, so a ``SUBTRACT`` parcel only cuts into the
    parcels declared before it — the same rule the editor shows and the same
    one :func:`~obs_overlay.core.geometry.covered_area` evaluates.
    """
    combined = QPainterPath()
    for parcel in parcels:
        if not parcel.enabled or parcel.width <= 0 or parcel.height <= 0:
            continue
        piece = parcel_path(parcel)
        if parcel.op is BooleanOp.SUBTRACT:
            combined = combined.subtracted(piece)
        else:
            combined = combined.united(piece)
    return combined


def _is_rect_only(parcels: Iterable[Parcel]) -> bool:
    """True when every enabled parcel is a plain, un-rounded rectangle."""
    for parcel in parcels:
        if not parcel.enabled:
            continue
        if parcel.shape is ShapeType.RECT:
            continue
        if parcel.shape is ShapeType.ROUNDED_RECT and _clamped_radius(parcel) <= 0:
            continue
        return False
    return True


def _region_rect_only(parcels: Sequence[Parcel], grow: int) -> QRegion:
    region = QRegion()
    for parcel in parcels:
        if not parcel.enabled or parcel.width <= 0 or parcel.height <= 0:
            continue
        rect = to_qrect(parcel.rect)
        if parcel.op is BooleanOp.SUBTRACT:
            # Shrink a subtracted rect by the same margin the additive ones
            # grow by, so the two stay symmetric and no sliver survives.
            region = region.subtracted(QRegion(rect.adjusted(grow, grow, -grow, -grow)))
        else:
            region = region.united(QRegion(rect.adjusted(-grow, -grow, grow, grow)))
    return region


def _region_from_path(path: QPainterPath, bounds: RectSpec, grow: int) -> QRegion | None:
    """Rasterise a path into a 1-bit mask region.

    Returns ``None`` when the bounds are unusable, letting the caller fall back
    to a simpler construction rather than showing nothing.
    """
    if bounds.width <= 0 or bounds.height <= 0:
        return None
    if bounds.width * bounds.height > _MAX_MASK_PIXELS:
        logger.warning(
            "Mask bitmap of %dx%d is too large; falling back to bounding boxes.",
            bounds.width,
            bounds.height,
        )
        return None

    bitmap = QBitmap(bounds.width, bounds.height)
    bitmap.fill(Qt.GlobalColor.color0)

    painter = QPainter()
    if not painter.begin(bitmap):  # pragma: no cover - only on a broken paint device
        logger.error("Could not begin painting the mask bitmap.")
        return None
    try:
        # No antialiasing: a 1-bit target would dither the edge into a speckled
        # mask, which reads as noise rather than a soft edge.
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.translate(-bounds.x, -bounds.y)
        painter.setBrush(Qt.GlobalColor.color1)
        if grow > 0:
            # Stroking as well as filling dilates the shape by half the pen
            # width on each side, covering the antialiased fringe the canvas
            # paints.
            pen = painter.pen()
            pen.setColor(Qt.GlobalColor.color1)
            pen.setWidth(grow * 2)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)
    finally:
        painter.end()

    region = QRegion(bitmap)
    if bounds.x or bounds.y:
        region.translate(bounds.x, bounds.y)
    return region


def build_region(
    parcels: Sequence[Parcel],
    bounds: RectSpec | None = None,
    grow: int = 1,
) -> QRegion:
    """The window mask for a parcel list.

    ``bounds`` is the overlay window's rect in its own coordinates; it sizes
    the temporary bitmap used for non-rectangular shapes. ``grow`` dilates the
    mask so antialiased edges are not clipped.

    An empty result is meaningful: it hides the window entirely. Callers that
    do not want that (mask disabled) simply do not call this.
    """
    enabled = [p for p in parcels if p.enabled and p.width > 0 and p.height > 0]
    if not enabled:
        return QRegion()

    grow = max(0, grow)

    if _is_rect_only(enabled):
        return _region_rect_only(enabled, grow)

    if bounds is None:
        from .geometry import bounding_rect  # local import avoids a cycle

        raw = bounding_rect([p.rect for p in enabled])
        bounds = RectSpec(
            raw.x - grow - 1,
            raw.y - grow - 1,
            raw.width + 2 * (grow + 1),
            raw.height + 2 * (grow + 1),
        )

    region = _region_from_path(build_path(enabled), bounds, grow)
    if region is not None:
        return region

    # Last resort: bounding boxes. Coarser, but the overlay still works.
    logger.warning("Falling back to bounding-box mask.")
    return _region_rect_only(enabled, grow)


# ---------------------------------------------------------------------------
# Image masks ("gambar siluet hitam-putih" from the blueprint)
# ---------------------------------------------------------------------------


def region_from_image(image: QImage, threshold: int = 128, invert: bool = False) -> QRegion:
    """Build a region from a black-and-white silhouette.

    White (luminance ≥ ``threshold``) keeps the window; black cuts it away, per
    the blueprint. Transparent pixels always count as cut-away, so a PNG with
    an alpha channel works as expected too.
    """
    if image.isNull():
        return QRegion()

    threshold = max(0, min(255, threshold))
    width, height = image.width(), image.height()
    if width * height > _MAX_MASK_PIXELS:
        raise ValueError("Mask image is too large.")

    # ARGB32 gives a predictable layout for the per-pixel test below.
    source = image.convertToFormat(QImage.Format.Format_ARGB32)
    bitmap = QBitmap(width, height)
    bitmap.fill(Qt.GlobalColor.color0)

    painter = QPainter()
    if not painter.begin(bitmap):  # pragma: no cover
        return QRegion()
    try:
        painter.setPen(Qt.GlobalColor.color1)
        for y in range(height):
            run_start = -1
            for x in range(width):
                pixel = source.pixelColor(x, y)
                keep = pixel.alpha() >= 128 and pixel.lightness() >= threshold
                if invert:
                    keep = not keep and pixel.alpha() >= 128
                if keep and run_start < 0:
                    run_start = x
                elif not keep and run_start >= 0:
                    painter.drawLine(run_start, y, x - 1, y)
                    run_start = -1
            if run_start >= 0:
                painter.drawLine(run_start, y, width - 1, y)
    finally:
        painter.end()

    return QRegion(bitmap)


def region_from_image_file(path: str, threshold: int = 128, invert: bool = False) -> QRegion:
    """Load a silhouette from disk and convert it to a region."""
    image = QImage(path)
    if image.isNull():
        raise ValueError(f"Could not load mask image: {path}")
    return region_from_image(image, threshold=threshold, invert=invert)


def _row_runs(region: QRegion, y: int, left: int, right_edge: int) -> list[tuple[int, int]]:
    """Half-open ``[start, end)`` spans of ``region`` on scanline ``y``."""
    runs: list[tuple[int, int]] = []
    start = -1
    for x in range(left, right_edge + 1):
        inside = x <= right_edge - 1 and region.contains(QPoint(x, y))
        if inside and start < 0:
            start = x
        elif not inside and start >= 0:
            runs.append((start, x))
            start = -1
    return runs


def parcels_from_region(region: QRegion, max_parcels: int = 256) -> list[Parcel]:
    """Approximate an arbitrary region with rectangular parcels.

    PyQt6 dropped ``QRegion.rects()``, so the region is sampled scanline by
    scanline: horizontal runs are found per row, then runs with identical
    extents on consecutive rows are merged into one rectangle. The largest
    rectangles are kept. Good enough to import a silhouette into the editor,
    where the user can tidy it up.
    """
    bounds = region.boundingRect()
    if bounds.isEmpty():
        return []

    from .geometry import rects_to_parcels

    left = bounds.left()
    right_edge = bounds.right() + 1  # exclusive
    finished: list[RectSpec] = []
    # extent -> y at which this run started
    open_runs: dict[tuple[int, int], int] = {}

    for y in range(bounds.top(), bounds.bottom() + 2):
        current = (
            dict.fromkeys(_row_runs(region, y, left, right_edge), y) if y <= bounds.bottom() else {}
        )
        for extent, start_y in list(open_runs.items()):
            if extent in current:
                # Still open: keep the original start row.
                current[extent] = start_y
            else:
                finished.append(RectSpec(extent[0], start_y, extent[1] - extent[0], y - start_y))
        open_runs = current

        if len(finished) > max_parcels * 8:
            break

    finished.sort(key=lambda r: -(r.width * r.height))
    return rects_to_parcels(finished[:max_parcels], name_prefix="Region")
