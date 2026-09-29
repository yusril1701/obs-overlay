"""NDI receiver.

Wraps the ``ndi-python`` binding, whose **import name is ``NDIlib``** even
though the PyPI package is called ``ndi-python``.

Colour and alpha
----------------
The receiver asks for ``RECV_COLOR_FORMAT_BGRX_BGRA``: NDI then delivers BGRA
when the sender has an alpha channel and BGRX when it does not. That byte order
is what Qt calls ``Format_ARGB32`` on a little-endian machine, so it maps
straight onto :data:`~obs_overlay.core.frame.PixelFormat.BGRA8888` with no
channel shuffling.

The distinction matters: in a BGRX frame the fourth byte is *padding*, not
alpha, and it is not guaranteed to be 0xFF. Handing it to Qt as alpha would
make an opaque source flicker or vanish, so BGRX frames get their alpha channel
filled in explicitly.

NDI specifies that its RGBA data "is not pre-multiplied", so the default here
is straight alpha — the opposite of the Spout/OBS path. It stays configurable
because some senders (OBS via DistroAV among them) do emit premultiplied
frames, and only looking at a soft edge will tell you which you have.

Status
------
This module is written against the binding's published API and its official
examples, but unlike the rest of the code base it could not be executed during
development: NDI needs its runtime, a licence acceptance and a live sender.
Treat the first run on real hardware as the actual test.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from typing import Any

import numpy as np

from ..core.frame import (
    Frame,
    FrameBufferPool,
    PixelFormat,
    is_valid_dimensions,
    required_buffer_size,
)
from .base import SourceError, SourceState, VideoSource

logger = logging.getLogger(__name__)

#: NDIlib_initialize is a process-wide call. It is made once and never undone:
#: calling NDIlib_destroy while any other receiver is alive would break it, and
#: the process exiting releases everything anyway.
_init_lock = threading.Lock()
_initialised = False

_INSTALL_HINT = (
    "NDI support needs the 'ndi-python' package and the NDI runtime.\n"
    "  pip install ndi-python\n"
    "and install the NDI Runtime from https://ndi.video/ (required by its licence)."
)


def _import_ndi() -> Any:
    """Import the NDI binding, turning failure into a clear message."""
    try:
        import NDIlib  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SourceError(f"{_INSTALL_HINT}\n\nImport failed: {exc}") from exc
    return NDIlib


def ndi_available() -> bool:
    """True when the NDI binding can be imported."""
    try:
        _import_ndi()
    except SourceError:
        return False
    return True


def _ensure_initialised(ndi: Any) -> None:
    """Initialise the NDI library once per process."""
    global _initialised
    with _init_lock:
        if _initialised:
            return
        if not ndi.initialize():
            raise SourceError(
                "NDIlib.initialize() failed. The NDI runtime is missing or "
                "unsupported on this CPU.\n" + _INSTALL_HINT
            )
        _initialised = True
        logger.info("NDI library initialised.")


def list_ndi_sources(timeout_ms: int = 1500) -> list[str]:
    """Names of NDI sources visible on the network.

    Discovery is mDNS-based and asynchronous, so this waits briefly rather than
    returning whatever happens to be cached at the instant it is called.
    """
    try:
        ndi = _import_ndi()
        _ensure_initialised(ndi)
    except SourceError as exc:
        logger.debug("NDI unavailable: %s", exc)
        return []

    finder = None
    try:
        finder = ndi.find_create_v2()
        if finder is None:
            return []
        ndi.find_wait_for_sources(finder, max(0, timeout_ms))
        sources = ndi.find_get_current_sources(finder)
        return [str(getattr(source, "ndi_name", "")) for source in sources if source is not None]
    except Exception as exc:  # pragma: no cover - native call
        logger.debug("NDI source discovery failed: %s", exc)
        return []
    finally:
        if finder is not None:
            with contextlib.suppress(Exception):  # pragma: no cover - native call
                ndi.find_destroy(finder)


class NdiSource(VideoSource):
    """Receives video from an NDI sender."""

    kind = "ndi"

    def __init__(
        self,
        source_name: str = "",
        auto_select: bool = True,
        premultiplied: bool = False,
        low_bandwidth: bool = False,
        receive_timeout_ms: int = 80,
    ) -> None:
        super().__init__()
        self._requested_name = source_name.strip()
        self._auto_select = auto_select
        self._premultiplied = premultiplied
        self._low_bandwidth = low_bandwidth
        self._receive_timeout_ms = max(0, receive_timeout_ms)

        self._ndi: Any = None
        self._receiver: Any = None
        self._connected_name = ""
        self._format_warned = False

    # -- identity ----------------------------------------------------------
    @property
    def display_name(self) -> str:
        return self._connected_name or self._requested_name or "(any NDI source)"

    # -- lifecycle ---------------------------------------------------------
    def open(self) -> bool:
        ndi = _import_ndi()
        _ensure_initialised(ndi)
        self._ndi = ndi
        self._set_state(SourceState.CONNECTING, "Looking for an NDI source…")

        source = self._find_source(ndi)
        if source is None:
            self._set_state(SourceState.CONNECTING, "No NDI source is publishing yet.")
            return False

        try:
            settings = ndi.RecvCreateV3()
            settings.color_format = ndi.RECV_COLOR_FORMAT_BGRX_BGRA
            bandwidth = self._bandwidth_constant(ndi)
            if bandwidth is not None:
                settings.bandwidth = bandwidth
            receiver = ndi.recv_create_v3(settings)
        except Exception as exc:  # pragma: no cover - native call
            raise SourceError(f"Could not create the NDI receiver: {exc}") from exc

        if receiver is None:
            raise SourceError("NDIlib.recv_create_v3 returned nothing.")

        try:
            ndi.recv_connect(receiver, source)
        except Exception as exc:  # pragma: no cover - native call
            self._destroy_receiver(receiver)
            raise SourceError(f"Could not connect to the NDI source: {exc}") from exc

        self._receiver = receiver
        self._connected_name = str(getattr(source, "ndi_name", "") or self._requested_name)
        logger.info("NDI receiver connected to %r", self._connected_name)
        return True

    def _bandwidth_constant(self, ndi: Any) -> int | None:
        """Bandwidth enum, looked up defensively across binding versions."""
        name = "RECV_BANDWIDTH_LOWEST" if self._low_bandwidth else "RECV_BANDWIDTH_HIGHEST"
        value = getattr(ndi, name, None)
        if value is None:
            logger.debug("NDI binding has no %s; leaving the default.", name)
        return value

    def _find_source(self, ndi: Any) -> Any:
        """Pick the NDI source to connect to.

        A configured name wins. With auto-select on, a name that is not
        currently publishing falls back to the first available source rather
        than leaving the overlay blank waiting for a name that may be a typo —
        NDI names are long ("MACHINE (OBS)") and easy to get wrong.
        """
        finder = None
        try:
            finder = ndi.find_create_v2()
            if finder is None:
                return None
            ndi.find_wait_for_sources(finder, 1000)
            sources = list(ndi.find_get_current_sources(finder) or [])
            if not sources:
                return None

            if self._requested_name:
                for source in sources:
                    if str(getattr(source, "ndi_name", "")) == self._requested_name:
                        return source
                if not self._auto_select:
                    logger.info("NDI source %r is not publishing.", self._requested_name)
                    return None
                logger.info(
                    "NDI source %r not found; using %r instead.",
                    self._requested_name,
                    getattr(sources[0], "ndi_name", "?"),
                )
            return sources[0]
        except Exception as exc:  # pragma: no cover - native call
            logger.debug("NDI discovery failed: %s", exc)
            return None
        finally:
            if finder is not None:
                with contextlib.suppress(Exception):  # pragma: no cover
                    ndi.find_destroy(finder)

    def close(self) -> None:
        receiver, self._receiver = self._receiver, None
        if receiver is not None:
            self._destroy_receiver(receiver)
        self._connected_name = ""
        self._set_state(SourceState.CLOSED)

    def _destroy_receiver(self, receiver: Any) -> None:
        try:
            self._ndi.recv_destroy(receiver)
        except Exception as exc:  # pragma: no cover - native call
            logger.debug("recv_destroy failed: %s", exc)

    # -- capture -----------------------------------------------------------
    def capture(self, pool: FrameBufferPool) -> Frame | None:
        ndi, receiver = self._ndi, self._receiver
        if ndi is None or receiver is None:
            return None

        try:
            frame_type, video, _audio, _meta = ndi.recv_capture_v2(
                receiver, self._receive_timeout_ms, want_metadata=False
            )
        except Exception as exc:  # pragma: no cover - native call
            self._set_state(SourceState.ERROR, f"NDI receive failed: {exc}")
            return None

        if frame_type != ndi.FRAME_TYPE_VIDEO or video is None:
            # NONE means no frame within the timeout; AUDIO is not our business.
            # Both are normal and must still be freed where applicable.
            self._free_non_video(ndi, receiver, frame_type, _audio)
            return None

        try:
            return self._build_frame(ndi, video, pool)
        finally:
            try:
                ndi.recv_free_video_v2(receiver, video)
            except Exception as exc:  # pragma: no cover - native call
                logger.debug("recv_free_video_v2 failed: %s", exc)

    @staticmethod
    def _free_non_video(ndi: Any, receiver: Any, frame_type: Any, audio: Any) -> None:
        if audio is None:
            return
        with contextlib.suppress(Exception):  # pragma: no cover - native call
            if frame_type == ndi.FRAME_TYPE_AUDIO:
                ndi.recv_free_audio_v2(receiver, audio)

    def _build_frame(self, ndi: Any, video: Any, pool: FrameBufferPool) -> Frame | None:
        width = int(getattr(video, "xres", 0))
        height = int(getattr(video, "yres", 0))
        if not is_valid_dimensions(width, height):
            self._set_state(SourceState.ERROR, f"NDI sent an unusable size {width}x{height}.")
            return None

        has_alpha = self._frame_has_alpha(ndi, video)
        if has_alpha is None:
            return None  # unusable pixel format; already reported

        try:
            pixels = np.asarray(video.data)
        except Exception as exc:  # pragma: no cover - native call
            self._set_state(SourceState.ERROR, f"Could not read the NDI frame: {exc}")
            return None

        if pixels.dtype != np.uint8 or pixels.size < width * height * 4:
            self._set_state(
                SourceState.ERROR,
                f"Unexpected NDI buffer: dtype={pixels.dtype}, size={pixels.size}.",
            )
            return None

        needed = required_buffer_size(width, height)
        if pool.buffer_size != needed:
            pool.resize(needed)
        buffer = pool.acquire()
        if buffer is None:
            return None

        try:
            destination = np.frombuffer(buffer.data, dtype=np.uint8, count=needed).reshape(
                height, width, 4
            )
            destination[:] = pixels.reshape(height, width, 4)[:, :, :4]
            if not has_alpha:
                # In a BGRX frame the fourth byte is padding, not alpha.
                destination[..., 3] = 255
        except Exception:
            buffer.release()
            raise

        if (width, height) != (self._width, self._height):
            self._width, self._height = width, height
            logger.info("NDI source %r: %dx%d", self.display_name, width, height)

        if self._state is not SourceState.CONNECTED:
            self._set_state(SourceState.CONNECTED)

        return Frame(
            width=width,
            height=height,
            pixel_format=PixelFormat.BGRA8888,
            buffer=buffer,
            sequence=self._next_sequence(),
            timestamp=time.perf_counter(),
            # Only meaningful when the frame actually carries alpha.
            premultiplied=self._premultiplied and has_alpha,
        )

    def _frame_has_alpha(self, ndi: Any, video: Any) -> bool | None:
        """Whether this frame's fourth byte is alpha, or ``None`` if unusable."""
        fourcc = getattr(video, "FourCC", None)
        bgra = getattr(ndi, "FOURCC_VIDEO_TYPE_BGRA", object())
        bgrx = getattr(ndi, "FOURCC_VIDEO_TYPE_BGRX", object())

        if fourcc == bgra:
            return True
        if fourcc == bgrx:
            if not self._format_warned:
                logger.info("NDI sender has no alpha channel; the overlay will be opaque.")
                self._format_warned = True
            return False

        # Asking for BGRX_BGRA should make anything else impossible, but a
        # binding or SDK change must not be silently misinterpreted as pixels.
        self._set_state(
            SourceState.ERROR,
            f"NDI delivered an unsupported pixel format (FourCC {fourcc!r}); "
            "expected BGRA or BGRX.",
        )
        return None

    # -- discovery ---------------------------------------------------------
    @staticmethod
    def list_senders() -> list[str]:
        return list_ndi_sources()
