"""Source construction and discovery, keeping Windows-only imports lazy.

Nothing here imports ``SpoutGL`` at module load, so the package stays
importable on Linux/macOS for the test suite.
"""

from __future__ import annotations

import logging

from ..config.models import SourceKind, SourceSettings
from .base import VideoSource
from .demo_source import DemoSource

logger = logging.getLogger(__name__)


def spout_available() -> bool:
    """True when a Spout source could actually be created on this machine."""
    from .spout_source import spout_available as _available

    return _available()


def available_sender_names() -> list[str]:
    """Every Spout sender currently publishing, newest discovery order."""
    from .spout_source import list_spout_senders

    return list_spout_senders()


def create_source(settings: SourceSettings) -> VideoSource:
    """Build the source described by ``settings``.

    Falls back to the test pattern when Spout is unavailable *and* the profile
    allows it, so the app stays usable on a machine without the plugin.
    """
    if settings.kind is SourceKind.DEMO:
        return DemoSource()

    from .spout_source import SpoutSource
    from .spout_source import spout_available as _available

    if not _available():
        if settings.fallback_to_demo:
            logger.warning("SpoutGL is unavailable; falling back to the test pattern.")
            return DemoSource()
        # Constructing it anyway produces a precise SourceError on open(),
        # which the UI surfaces verbatim — more useful than a silent swap.
        logger.warning("SpoutGL is unavailable; the overlay will report no signal.")

    return SpoutSource(
        sender_name=settings.sender_name,
        auto_select=settings.auto_select_sender,
        invert_y=settings.invert_y,
        premultiplied=settings.premultiplied_alpha,
    )
