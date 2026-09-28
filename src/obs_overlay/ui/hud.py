"""The debug heads-up display.

Answers the three questions that come up when an overlay looks wrong: is a
sender connected, at what resolution, and are frames arriving on time.
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPen

from ..config.models import HudCorner, HudSettings
from ..core.fps import StatsSnapshot
from ..sources.base import SourceInfo, SourceState
from .theme import PALETTE, color

_MARGIN = 14
_PADDING = 10
_LINE_GAP = 3


def _state_color(state: SourceState) -> QColor:
    return {
        SourceState.CONNECTED: color(PALETTE.success),
        SourceState.CONNECTING: color(PALETTE.warning),
        SourceState.ERROR: color(PALETTE.danger),
    }.get(state, color(PALETTE.text_disabled))


def _rows(
    settings: HudSettings,
    stats: StatsSnapshot,
    info: SourceInfo,
    target_fps: int,
) -> list[tuple[str, str, QColor | None]]:
    rows: list[tuple[str, str, QColor | None]] = [
        ("Status", info.state.value.title(), _state_color(info.state))
    ]
    if settings.show_source:
        rows.append(("Sender", info.name or "-", None))
        rows.append(("Size", info.resolution, None))
    if settings.show_fps:
        # Colour the reading by how far it is from what the user asked for.
        ratio = (stats.fps / target_fps) if target_fps else 0.0
        if info.state is not SourceState.CONNECTED:
            tint = None
        elif ratio >= 0.9:
            tint = color(PALETTE.success)
        elif ratio >= 0.6:
            tint = color(PALETTE.warning)
        else:
            tint = color(PALETTE.danger)
        rows.append(("FPS", f"{stats.fps:5.1f} / {target_fps}", tint))
    if settings.show_dropped:
        drop_pct = stats.drop_ratio * 100.0
        tint = color(PALETTE.warning) if drop_pct >= 5.0 else None
        rows.append(
            ("Frames", f"{stats.frames_received} (-{stats.frames_dropped}, {drop_pct:.1f}%)", tint)
        )
    if settings.show_latency:
        rows.append(("Age", f"{stats.last_frame_age_ms:.0f} ms", None))
        rows.append(("Jitter", f"{stats.jitter_ms:.1f} ms", None))
    if info.detail:
        rows.append(("Note", info.detail, color(PALETTE.text_muted)))
    return rows


def paint_hud(
    painter: QPainter,
    viewport: QRect,
    settings: HudSettings,
    stats: StatsSnapshot,
    info: SourceInfo,
    target_fps: int,
) -> None:
    """Draw the HUD panel in the configured corner of ``viewport``."""
    if not settings.enabled:
        return

    rows = _rows(settings, stats, info, target_fps)
    if not rows:
        return

    font = QFont("Consolas")
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(9)
    metrics = QFontMetrics(font)

    label_width = max(metrics.horizontalAdvance(label) for label, _, _ in rows)
    value_width = max(metrics.horizontalAdvance(value) for _, value, _ in rows)
    line_height = metrics.height() + _LINE_GAP
    panel_width = label_width + value_width + _PADDING * 2 + 12
    panel_height = line_height * len(rows) + _PADDING * 2 - _LINE_GAP

    left = (
        viewport.left() + _MARGIN
        if settings.corner in (HudCorner.TOP_LEFT, HudCorner.BOTTOM_LEFT)
        else viewport.right() - panel_width - _MARGIN
    )
    top = (
        viewport.top() + _MARGIN
        if settings.corner in (HudCorner.TOP_LEFT, HudCorner.TOP_RIGHT)
        else viewport.bottom() - panel_height - _MARGIN
    )
    panel = QRect(int(left), int(top), int(panel_width), int(panel_height))

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setFont(font)

    painter.setPen(QPen(color(PALETTE.border_strong, 180), 1))
    painter.setBrush(QBrush(color(PALETTE.background, 214)))
    painter.drawRoundedRect(panel, 7, 7)

    y = panel.top() + _PADDING
    for label, value, tint in rows:
        painter.setPen(QPen(color(PALETTE.text_muted)))
        painter.drawText(
            QRect(panel.left() + _PADDING, y, label_width, line_height),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            label,
        )
        painter.setPen(QPen(tint or color(PALETTE.text)))
        painter.drawText(
            QRect(panel.left() + _PADDING + label_width + 12, y, value_width, line_height),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            value,
        )
        y += line_height

    painter.restore()
