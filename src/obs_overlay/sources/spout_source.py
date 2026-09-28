"""Spout2 receiver.

Wraps the ``SpoutGL`` package (a pybind11 binding over the Spout 2.007 SDK).
Several of its sharp edges are worked around here rather than at the call site:

* ``getSenderName()`` is bound to the wrong C++ method and returns the sender
  *width* as an int. The sender name is tracked in this class instead.
* ``getSenderInfo(name).name`` is always empty (the C++ constructor never
  assigns it); only ``.width``/``.height`` are usable.
* ``receiveImage()`` returns ``True`` even when it wrote nothing — it returns
  early both on a size change and when there is no new frame. ``isFrameNew()``
  is the real "did I get pixels" signal.
* ``isUpdated()`` resets itself to ``False`` when read, so it must be read
  exactly once per iteration and stored.
* ``waitFrameSync()`` returns immediately when the sender never created a sync
  event — which is the case for OBS — so it is useless as a pacer here and
  would spin the CPU. Pacing is done by :class:`~obs_overlay.core.fps.RateLimiter`.
* ``holdFps()`` is not exposed to Python at all.

Threading: WGL contexts are thread-affine, so every method except
:meth:`list_senders` must be called from the one thread that called
:meth:`open`. The producer thread owns a source for its whole lifetime, which
satisfies this.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..core.frame import (
    Frame,
    FrameBufferPool,
    PixelFormat,
    is_valid_dimensions,
    required_buffer_size,
)
from .base import SourceError, SourceState, VideoSource

logger = logging.getLogger(__name__)

#: DXGI formats a uint8 RGBA receive buffer can represent faithfully.
#: 87 = B8G8R8A8_UNORM (what OBS produces with Color Format = BGRA)
#: 28 = R8G8B8A8_UNORM
_ALPHA_CAPABLE_FORMATS = {28, 87}
#: 88 = B8G8R8X8_UNORM — the X means the alpha byte is ignored, so the feed is
#: opaque no matter what OBS composited.
_NO_ALPHA_FORMATS = {88, 89}
#: Float/10-bit formats a byte buffer would silently truncate.
_HDR_FORMATS = {10, 24, 2, 11}


def _import_spoutgl() -> Any:
    """Import SpoutGL, converting the failure into a clear message."""
    try:
        import SpoutGL  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - platform dependent
        raise SourceError(
            "SpoutGL is not installed. Run: pip install SpoutGL "
            "(Windows only; it ships the Spout 2.007 native library)."
        ) from exc
    return SpoutGL


def spout_available() -> bool:
    """True when the SpoutGL package can be imported."""
    try:
        _import_spoutgl()
    except SourceError:
        return False
    return True


def list_spout_senders() -> list[str]:
    """Names of every active Spout sender.

    Needs no OpenGL context — it only reads Spout's shared-memory name map —
    so the control panel can call it directly from the GUI thread.
    """
    try:
        spout = _import_spoutgl()
    except SourceError:
        return []
    try:
        with spout.SpoutReceiver() as receiver:
            names = receiver.getSenderList()
        return [str(name) for name in names if name]
    except Exception as exc:  # pragma: no cover - native call
        logger.debug("Could not enumerate Spout senders: %s", exc)
        return []


class SpoutSource(VideoSource):
    """Receives frames from an OBS Spout2 sender."""

    kind = "spout"

    def __init__(
        self,
        sender_name: str = "",
        auto_select: bool = True,
        invert_y: bool = False,
        premultiplied: bool = True,
    ) -> None:
        super().__init__()
        self._requested_name = sender_name.strip()
        self._auto_select = auto_select
        self._invert_y = invert_y
        self._premultiplied = premultiplied
        #: The name actually passed to setReceiverName, which may be "" when
        #: auto-select fell back to following the active sender.
        self._pinned_name = ""
        self._receiver: Any | None = None
        self._spout: Any | None = None
        self._gl_created = False
        self._connected_name = ""
        self._sender_format = 0
        self._format_warned = False
        self._alignment_warned = False
        self._primed = False

    # -- identity ----------------------------------------------------------
    @property
    def display_name(self) -> str:
        if self._connected_name:
            return self._connected_name
        if self._requested_name:
            return self._requested_name
        return "(any sender)"

    @property
    def sender_format(self) -> int:
        """Raw DXGI format reported by the sender (0 when unknown)."""
        return self._sender_format

    @property
    def sender_has_alpha(self) -> bool | None:
        """Whether the sender's pixel format carries alpha.

        ``None`` means "unknown" — either not connected yet, or a format this
        code does not recognise.
        """
        if self._sender_format in _ALPHA_CAPABLE_FORMATS:
            return True
        if self._sender_format in _NO_ALPHA_FORMATS:
            return False
        return None

    # -- lifecycle ---------------------------------------------------------
    def open(self) -> bool:
        self._spout = _import_spoutgl()
        self._set_state(SourceState.CONNECTING)

        try:
            receiver = self._spout.SpoutReceiver()
        except Exception as exc:  # pragma: no cover - native call
            raise SourceError(f"Could not create a Spout receiver: {exc}") from exc

        # Spout needs a current WGL context on *this* thread. createOpenGL()
        # returns true immediately if one already exists, otherwise it makes a
        # hidden window and context — the supported headless path.
        try:
            if not receiver.createOpenGL():
                raise SourceError(
                    "Spout could not create an OpenGL context. A GPU with "
                    "desktop OpenGL support is required."
                )
            self._gl_created = True
        except SourceError:
            raise
        except Exception as exc:  # pragma: no cover - native call
            raise SourceError(f"Spout OpenGL setup failed: {exc}") from exc

        pinned = self._choose_sender_name(receiver)
        self._pinned_name = pinned
        try:
            # An empty name makes the receiver follow whichever sender is
            # active, rather than waiting for one particular name.
            receiver.setReceiverName(pinned)
        except Exception as exc:  # pragma: no cover - native call
            logger.debug("setReceiverName(%r) failed: %s", pinned, exc)

        self._receiver = receiver
        self._primed = False
        logger.info(
            "Spout receiver opened (requested=%r, using=%r)",
            self._requested_name or "<any>",
            pinned or "<active sender>",
        )
        return True

    def _choose_sender_name(self, receiver: Any) -> str:
        """Decide which sender name to pin the receiver to.

        With auto-select on, a configured name that is not currently
        publishing falls back to following the active sender — otherwise the
        overlay would sit blank waiting for a name that may never appear,
        which is the usual outcome of a typo or of the OBS filter still
        carrying its default name.
        """
        requested = self._requested_name
        if not requested:
            return ""
        if not self._auto_select:
            return requested

        # Enumerating senders needs no GL context; it reads shared memory.
        try:
            available = [str(name) for name in receiver.getSenderList() if name]
        except Exception as exc:  # pragma: no cover - native call
            logger.debug("Could not enumerate senders: %s", exc)
            return requested

        if requested in available:
            return requested
        if available:
            logger.info(
                "Sender %r is not publishing; following the active sender instead (available: %s).",
                requested,
                ", ".join(available),
            )
            return ""
        # Nothing is publishing yet: keep waiting for the requested name, which
        # is what the user asked for.
        return requested

    def close(self) -> None:
        receiver, self._receiver = self._receiver, None
        if receiver is not None:
            try:
                receiver.releaseReceiver()
            except Exception as exc:  # pragma: no cover - native call
                logger.debug("releaseReceiver failed: %s", exc)
            if self._gl_created:
                try:
                    receiver.closeOpenGL()
                except Exception as exc:  # pragma: no cover - native call
                    logger.debug("closeOpenGL failed: %s", exc)
        self._gl_created = False
        self._connected_name = ""
        self._pinned_name = ""
        self._primed = False
        self._set_state(SourceState.CLOSED)

    # -- capture -----------------------------------------------------------
    def capture(self, pool: FrameBufferPool) -> Frame | None:
        receiver = self._receiver
        if receiver is None:
            return None

        spout = self._spout
        assert spout is not None

        # Must be read exactly once per iteration: reading it clears the flag.
        try:
            updated = bool(receiver.isUpdated())
        except Exception as exc:  # pragma: no cover - native call
            self._set_state(SourceState.ERROR, f"isUpdated failed: {exc}")
            return None

        if not self._primed:
            # Documented first-call pattern: a NULL buffer just establishes the
            # connection and lets the sender's size become known.
            try:
                receiver.receiveImage(None, spout.GL_RGBA, self._invert_y, 0)
            except Exception as exc:  # pragma: no cover - native call
                logger.debug("Priming receiveImage failed: %s", exc)
            self._primed = True

        width, height = self._read_dimensions(receiver)
        if not is_valid_dimensions(width, height):
            if self._state is not SourceState.CONNECTING:
                self._set_state(SourceState.CONNECTING, "Waiting for a Spout sender…")
            self._width = self._height = 0
            return None

        if updated or width != self._width or height != self._height:
            self._on_resolution_changed(receiver, width, height)

        needed = required_buffer_size(width, height)
        if pool.buffer_size != needed:
            pool.resize(needed)

        buffer = pool.acquire()
        if buffer is None:
            # Consumer is behind; skip this frame rather than queueing latency.
            return None

        try:
            view = memoryview(buffer.data)[:needed]
            received = bool(receiver.receiveImage(view, spout.GL_RGBA, self._invert_y, 0))
        except Exception as exc:  # pragma: no cover - native call
            buffer.release()
            self._set_state(SourceState.ERROR, f"receiveImage failed: {exc}")
            return None

        if not received:
            buffer.release()
            self._set_state(SourceState.CONNECTING, "Sender not available.")
            return None

        # receiveImage returns True without writing anything when there is no
        # new frame, so this is the only trustworthy "got pixels" signal.
        try:
            is_new = bool(receiver.isFrameNew())
        except Exception:  # pragma: no cover - native call
            is_new = True

        if not is_new:
            buffer.release()
            return None

        # Guards the documented empty-first-buffer case.
        try:
            if spout.helpers.isBufferEmpty(view):
                buffer.release()
                return None
        except Exception:  # pragma: no cover - native call
            pass

        if self._state is not SourceState.CONNECTED:
            self._set_state(SourceState.CONNECTED)

        return Frame(
            width=width,
            height=height,
            pixel_format=PixelFormat.RGBA8888,
            buffer=buffer,
            sequence=self._next_sequence(),
            timestamp=time.perf_counter(),
            premultiplied=self._premultiplied,
        )

    # -- internals ---------------------------------------------------------
    def _read_dimensions(self, receiver: Any) -> tuple:
        try:
            return int(receiver.getSenderWidth()), int(receiver.getSenderHeight())
        except Exception as exc:  # pragma: no cover - native call
            logger.debug("Reading sender dimensions failed: %s", exc)
            return 0, 0

    def _on_resolution_changed(self, receiver: Any, width: int, height: int) -> None:
        self._width, self._height = width, height
        self._connected_name = self._resolve_sender_name(receiver)

        try:
            self._sender_format = int(receiver.getSenderFormat())
        except Exception:  # pragma: no cover - native call
            self._sender_format = 0

        logger.info(
            "Spout sender %r: %dx%d (DXGI format %d)",
            self._connected_name or "<unknown>",
            width,
            height,
            self._sender_format,
        )
        self._warn_about_format()

        # Spout's ReceiveImage does not handle row padding: "the width should
        # be a multiple of 4".
        if width % 4 and not self._alignment_warned:
            logger.warning(
                "Sender width %d is not a multiple of 4; Spout may deliver skewed rows. "
                "Set the OBS canvas to a multiple-of-4 width.",
                width,
            )
            self._alignment_warned = True

    def _resolve_sender_name(self, receiver: Any) -> str:
        """Best available sender name.

        ``getSenderName()`` cannot be used — the binding points it at
        ``GetSenderWidth`` — so a pinned name wins and otherwise the active
        sender is queried.
        """
        if self._pinned_name:
            return self._pinned_name
        try:
            active = receiver.getActiveSender()
        except Exception:  # pragma: no cover - native call
            return ""
        return str(active) if active else ""

    def _warn_about_format(self) -> None:
        if self._format_warned:
            return
        has_alpha = self.sender_has_alpha
        if has_alpha is False:
            logger.warning(
                "Sender format %d carries no alpha channel — the overlay will be opaque. "
                "In OBS set Settings > Advanced > Color Format to BGRA (8-bit).",
                self._sender_format,
            )
            self._format_warned = True
        elif self._sender_format in _HDR_FORMATS:
            logger.warning(
                "Sender uses a high-precision format (%d); it will be truncated to 8-bit.",
                self._sender_format,
            )
            self._format_warned = True

    # -- discovery ---------------------------------------------------------
    @staticmethod
    def list_senders() -> list[str]:
        return list_spout_senders()
