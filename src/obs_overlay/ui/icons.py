"""Icons drawn in code rather than shipped as image files.

Everything the UI needs is a simple geometric glyph, so painting them means no
binary assets in the repository, crisp output at any DPI, and colours that come
from :mod:`obs_overlay.ui.theme` instead of being baked into a PNG.

The application icon doubles as the source for the packaged ``.ico``; see
``packaging/make_icon.py``.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from .theme import PALETTE, color


def _new_pixmap(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap


def _painter(pixmap: QPixmap) -> QPainter:
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    return painter


def app_pixmap(size: int = 256, connected: bool = True) -> QPixmap:
    """The application mark: a rounded frame cut into parcels.

    It reads as the product's one idea — a window broken into boxes with
    see-through gaps between them.
    """
    pixmap = _new_pixmap(size)
    painter = _painter(pixmap)
    try:
        unit = size / 32.0
        # Rounded backing plate.
        plate = QPainterPath()
        plate.addRoundedRect(
            QRectF(unit * 1.5, unit * 1.5, unit * 29, unit * 29), unit * 7, unit * 7
        )
        painter.fillPath(plate, QBrush(color("#1b1e24")))
        painter.setPen(QPen(color(PALETTE.border_strong), max(1.0, unit * 0.6)))
        painter.drawPath(plate)

        accent = color(PALETTE.accent if connected else PALETTE.text_disabled)

        # Three parcels of different sizes, with clear gaps between them.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(accent))
        parcels = (
            QRectF(unit * 6.5, unit * 7.0, unit * 9.5, unit * 8.0),
            QRectF(unit * 18.0, unit * 7.0, unit * 7.5, unit * 12.5),
            QRectF(unit * 6.5, unit * 17.5, unit * 9.5, unit * 7.5),
        )
        for index, rect in enumerate(parcels):
            path = QPainterPath()
            path.addRoundedRect(rect, unit * 1.6, unit * 1.6)
            painter.setOpacity(1.0 if index == 0 else 0.72 - index * 0.12)
            painter.drawPath(path)
        painter.setOpacity(1.0)

        # A gap marker showing the "see-through" idea.
        painter.setPen(
            QPen(color(PALETTE.text_muted, 150), max(1.0, unit * 0.5), Qt.PenStyle.DotLine)
        )
        painter.drawLine(QPointF(unit * 18.0, unit * 21.5), QPointF(unit * 25.5, unit * 21.5))
        painter.drawLine(QPointF(unit * 18.0, unit * 24.0), QPointF(unit * 25.5, unit * 24.0))
    finally:
        painter.end()
    return pixmap


def app_icon(connected: bool = True) -> QIcon:
    """Multi-resolution application icon."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(app_pixmap(size, connected=connected))
    return icon


# ---------------------------------------------------------------------------
# Small glyphs for buttons
# ---------------------------------------------------------------------------


def _draw_plus(painter: QPainter, size: int, tint: QColor) -> None:
    unit = size / 16.0
    painter.setPen(QPen(tint, unit * 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(QPointF(unit * 8, unit * 3.5), QPointF(unit * 8, unit * 12.5))
    painter.drawLine(QPointF(unit * 3.5, unit * 8), QPointF(unit * 12.5, unit * 8))


def _draw_minus(painter: QPainter, size: int, tint: QColor) -> None:
    unit = size / 16.0
    painter.setPen(QPen(tint, unit * 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(QPointF(unit * 3.5, unit * 8), QPointF(unit * 12.5, unit * 8))


def _draw_copy(painter: QPainter, size: int, tint: QColor) -> None:
    unit = size / 16.0
    painter.setPen(QPen(tint, unit * 1.4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(unit * 2.5, unit * 2.5, unit * 8, unit * 8), unit, unit)
    painter.drawRoundedRect(QRectF(unit * 5.5, unit * 5.5, unit * 8, unit * 8), unit, unit)


def _draw_eye(painter: QPainter, size: int, tint: QColor) -> None:
    unit = size / 16.0
    painter.setPen(QPen(tint, unit * 1.4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(unit * 2, unit * 8)
    path.quadTo(unit * 8, unit * 2, unit * 14, unit * 8)
    path.quadTo(unit * 8, unit * 14, unit * 2, unit * 8)
    painter.drawPath(path)
    painter.setBrush(QBrush(tint))
    painter.drawEllipse(QPointF(unit * 8, unit * 8), unit * 1.8, unit * 1.8)


def _draw_lock(painter: QPainter, size: int, tint: QColor) -> None:
    unit = size / 16.0
    painter.setPen(QPen(tint, unit * 1.4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(unit * 5, unit * 7)
    path.lineTo(unit * 5, unit * 5)
    path.arcTo(QRectF(unit * 5, unit * 2, unit * 6, unit * 6), 180, -180)
    path.lineTo(unit * 11, unit * 7)
    painter.drawPath(path)
    painter.setBrush(QBrush(tint))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(QRectF(unit * 3.5, unit * 7, unit * 9, unit * 6.5), unit, unit)


def _draw_refresh(painter: QPainter, size: int, tint: QColor) -> None:
    unit = size / 16.0
    painter.setPen(QPen(tint, unit * 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    rect = QRectF(unit * 3, unit * 3, unit * 10, unit * 10)
    painter.drawArc(rect, 60 * 16, 260 * 16)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(tint))
    arrow = QPainterPath()
    arrow.moveTo(unit * 11.2, unit * 2.2)
    arrow.lineTo(unit * 14.2, unit * 5.0)
    arrow.lineTo(unit * 10.2, unit * 5.6)
    arrow.closeSubpath()
    painter.drawPath(arrow)


def _draw_grid(painter: QPainter, size: int, tint: QColor) -> None:
    unit = size / 16.0
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(tint))
    for row in range(2):
        for col in range(2):
            painter.drawRoundedRect(
                QRectF(unit * (3 + col * 5.5), unit * (3 + row * 5.5), unit * 4.5, unit * 4.5),
                unit * 0.8,
                unit * 0.8,
            )


def _draw_gear(painter: QPainter, size: int, tint: QColor) -> None:
    unit = size / 16.0
    painter.setPen(QPen(tint, unit * 1.5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(unit * 8, unit * 8), unit * 3, unit * 3)
    painter.setPen(QPen(tint, unit * 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    import math

    for index in range(6):
        angle = math.radians(index * 60)
        inner = 4.6
        outer = 6.6
        painter.drawLine(
            QPointF(unit * (8 + inner * math.cos(angle)), unit * (8 + inner * math.sin(angle))),
            QPointF(unit * (8 + outer * math.cos(angle)), unit * (8 + outer * math.sin(angle))),
        )


_GLYPHS: dict[str, Callable[[QPainter, int, QColor], None]] = {
    "add": _draw_plus,
    "remove": _draw_minus,
    "duplicate": _draw_copy,
    "visibility": _draw_eye,
    "lock": _draw_lock,
    "refresh": _draw_refresh,
    "grid": _draw_grid,
    "settings": _draw_gear,
}


def glyph_icon(name: str, size: int = 16, tint: str | None = None) -> QIcon:
    """A small monochrome button glyph.

    Unknown names return an empty icon rather than raising: a missing glyph
    should never take the window down.
    """
    draw = _GLYPHS.get(name)
    if draw is None:
        return QIcon()
    tint_color = color(tint or PALETTE.text)
    icon = QIcon()
    for scale in (1, 2):
        pixmap = _new_pixmap(size * scale)
        painter = _painter(pixmap)
        try:
            draw(painter, size * scale, tint_color)
        finally:
            painter.end()
        pixmap.setDevicePixelRatio(float(scale))
        icon.addPixmap(pixmap)
    return icon


def status_pixmap(size: int, state: str) -> QPixmap:
    """Tray badge: a filled dot whose colour encodes the connection state."""
    tint = {
        "connected": PALETTE.success,
        "connecting": PALETTE.warning,
        "error": PALETTE.danger,
    }.get(state, PALETTE.text_disabled)

    pixmap = app_pixmap(size, connected=state == "connected")
    painter = _painter(pixmap)
    try:
        radius = size * 0.17
        centre = QPointF(size - radius - size * 0.06, size - radius - size * 0.06)
        painter.setPen(QPen(color(PALETTE.background), max(1.0, size * 0.05)))
        painter.setBrush(QBrush(color(tint)))
        painter.drawEllipse(centre, radius, radius)
    finally:
        painter.end()
    return pixmap


def tray_icon(state: str = "idle") -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64):
        icon.addPixmap(status_pixmap(size, state))
    return icon
