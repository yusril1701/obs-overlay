"""Video sources feeding the overlay.

``SpoutSource``   GPU textures shared by the OBS Spout2 plugin (Windows)
``NdiSource``     NDI video from the network
``ScreenSource``  a monitor, or a rectangle within one
``ImageSource``   a still or animated image with alpha
``DemoSource``    an animated test pattern, so the whole app — masking, the
                  editor, click-through — can be exercised with neither OBS nor
                  a GPU present

Only ``Spout`` and ``NDI`` need an optional dependency; both are imported
lazily by :mod:`obs_overlay.sources.registry` so this package always imports.
"""

from __future__ import annotations

from .base import SourceError, SourceInfo, SourceState, VideoSource
from .demo_source import DemoSource
from .image_source import ImageSource
from .registry import (
    available_sender_names,
    create_source,
    kind_available,
    ndi_available,
    spout_available,
    unavailable_reason,
)
from .screen_source import ScreenSource

__all__ = [
    "DemoSource",
    "ImageSource",
    "ScreenSource",
    "SourceError",
    "SourceInfo",
    "SourceState",
    "VideoSource",
    "available_sender_names",
    "create_source",
    "kind_available",
    "ndi_available",
    "spout_available",
    "unavailable_reason",
]
