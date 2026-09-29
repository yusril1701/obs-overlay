"""Source construction and discovery.

Every optional dependency is imported lazily inside a function, so the package
stays importable on a machine with no SpoutGL, no NDI runtime and no GPU — the
condition CI runs under.
"""

from __future__ import annotations

import logging

from ..config.models import SourceKind, SourceSettings
from .base import VideoSource
from .demo_source import DemoSource

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def spout_available() -> bool:
    """True when a Spout source could actually be created on this machine."""
    from .spout_source import spout_available as _available

    return _available()


def ndi_available() -> bool:
    """True when the NDI binding can be imported."""
    from .ndi_source import ndi_available as _available

    return _available()


def kind_available(kind: SourceKind) -> bool:
    """Whether this machine can run the given source kind at all."""
    if kind is SourceKind.SPOUT:
        return spout_available()
    if kind is SourceKind.NDI:
        return ndi_available()
    # Screen, image and demo need nothing beyond Qt.
    return True


def unavailable_reason(kind: SourceKind) -> str:
    """A user-facing explanation of why a kind cannot be used, or ""."""
    if kind is SourceKind.SPOUT and not spout_available():
        return "SpoutGL is not installed. It is Windows-only:  pip install SpoutGL"
    if kind is SourceKind.NDI and not ndi_available():
        return (
            "The NDI binding is not installed:  pip install ndi-python\n"
            "The NDI Runtime must also be installed separately."
        )
    return ""


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def available_sender_names(kind: SourceKind = SourceKind.SPOUT) -> list[str]:
    """Everything the given source kind could currently connect to."""
    if kind is SourceKind.SPOUT:
        from .spout_source import list_spout_senders

        return list_spout_senders()
    if kind is SourceKind.NDI:
        from .ndi_source import list_ndi_sources

        return list_ndi_sources()
    if kind is SourceKind.SCREEN:
        from .screen_source import ScreenSource

        return ScreenSource.list_senders()
    return []


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def create_source(settings: SourceSettings) -> VideoSource:
    """Build the source described by ``settings``.

    Falls back to the test pattern when the chosen source is unavailable *and*
    the profile allows it, so the app stays usable on a machine that is missing
    an optional dependency.
    """
    kind = settings.kind

    if kind is SourceKind.DEMO:
        return DemoSource()

    if kind is SourceKind.SCREEN:
        from .screen_source import ScreenSource

        screen = settings.screen
        return ScreenSource(
            monitor_index=screen.monitor_index,
            region=screen.region if screen.use_region else None,
            target_fps=settings.target_fps,
        )

    if kind is SourceKind.IMAGE:
        from .image_source import ImageSource

        return ImageSource(path=settings.image.path, animate=settings.image.animate)

    if not kind_available(kind) and settings.fallback_to_demo:
        logger.warning(
            "%s is unavailable; falling back to the test pattern. %s",
            kind.value,
            unavailable_reason(kind),
        )
        return DemoSource()

    if kind is SourceKind.NDI:
        from .ndi_source import NdiSource

        ndi = settings.ndi
        return NdiSource(
            source_name=ndi.source_name,
            auto_select=ndi.auto_select_source,
            premultiplied=ndi.premultiplied_alpha,
            low_bandwidth=ndi.low_bandwidth,
            receive_timeout_ms=ndi.receive_timeout_ms,
        )

    from .spout_source import SpoutSource

    if not spout_available():
        # Constructing it anyway produces a precise SourceError on open(),
        # which the UI surfaces verbatim — more useful than a silent swap.
        logger.warning("SpoutGL is unavailable; the overlay will report no signal.")

    spout = settings.spout
    return SpoutSource(
        sender_name=spout.sender_name,
        auto_select=spout.auto_select_sender,
        invert_y=spout.invert_y,
        premultiplied=spout.premultiplied_alpha,
    )
