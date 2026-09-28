"""Video sources feeding the overlay.

``SpoutSource`` receives GPU textures shared by the OBS Spout2 plugin.
``DemoSource`` synthesises an animated RGBA test pattern so the whole app —
masking, the editor, click-through — can be exercised with neither OBS nor a
GPU present.
"""

from __future__ import annotations

from .base import SourceError, SourceInfo, SourceState, VideoSource
from .demo_source import DemoSource
from .registry import available_sender_names, create_source, spout_available

__all__ = [
    "DemoSource",
    "SourceError",
    "SourceInfo",
    "SourceState",
    "VideoSource",
    "available_sender_names",
    "create_source",
    "spout_available",
]
