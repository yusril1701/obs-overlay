"""Framework-independent core logic.

Nothing in :mod:`obs_overlay.core.geometry` imports Qt, which keeps the
editor's arithmetic unit-testable on any platform. :mod:`obs_overlay.core.mask`
is the one Qt-aware module here: it turns parcels into a ``QRegion``.
"""

from __future__ import annotations

from .fps import FrameStats
from .frame import Frame, FrameBufferPool, PixelFormat, PooledBuffer
from .geometry import Handle, SnapGuide, SnapResult

__all__ = [
    "Frame",
    "FrameBufferPool",
    "FrameStats",
    "Handle",
    "PixelFormat",
    "PooledBuffer",
    "SnapGuide",
    "SnapResult",
]
