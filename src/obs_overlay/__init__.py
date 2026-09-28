"""OBS Spout2 → Python transparent, click-through overlay for Windows.

The package is organised in layers so that everything that can be tested
without a GPU, without Windows and without OBS actually *is* testable:

``obs_overlay.config``
    Typed, versioned profile models plus an atomic on-disk store.
``obs_overlay.core``
    Pure logic: geometry/snapping math, mask building, frame buffers, stats.
``obs_overlay.sources``
    Video sources. ``SpoutSource`` talks to OBS through Spout2; ``DemoSource``
    synthesises an animated RGBA test pattern so the app is fully usable for
    layout work with neither OBS nor a GPU present.
``obs_overlay.platform``
    Win32 integration (click-through, topmost, hotkeys, capture exclusion)
    behind an interface that degrades to no-ops off Windows.
``obs_overlay.ui``
    Qt widgets: the overlay window, its two render backends, the interactive
    parcel editor, the control panel, the tray icon and the debug HUD.
"""

from __future__ import annotations

from .constants import APP_NAME, APP_VERSION, ORG_NAME

__all__ = ["APP_NAME", "APP_VERSION", "ORG_NAME", "__version__"]

__version__ = APP_VERSION
