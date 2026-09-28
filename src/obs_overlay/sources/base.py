"""The video source interface.

A source owns its connection and hands out :class:`~obs_overlay.core.frame.Frame`
objects backed by pooled memory. It acquires the buffer itself because only the
source knows how big the next frame will be — the Spout sender can change
resolution between two calls.

Every implementation must be safe to ``close()`` twice and to ``capture()``
while disconnected (returning ``None`` rather than raising), because the
producer thread calls both from its polling loop.
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass
from enum import Enum

from ..core.frame import Frame, FrameBufferPool, PixelFormat

logger = logging.getLogger(__name__)


class SourceState(str, Enum):
    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    CLOSED = "closed"


class SourceError(RuntimeError):
    """Unrecoverable problem with a video source."""


@dataclass(frozen=True)
class SourceInfo:
    """What the UI shows about the current connection."""

    name: str = ""
    width: int = 0
    height: int = 0
    state: SourceState = SourceState.IDLE
    detail: str = ""

    @property
    def resolution(self) -> str:
        if self.width > 0 and self.height > 0:
            return f"{self.width}×{self.height}"
        return "-"


class VideoSource(abc.ABC):
    """Base class for everything that can produce frames."""

    #: Human-readable kind, shown in the UI.
    kind: str = "source"

    def __init__(self) -> None:
        self._state = SourceState.IDLE
        self._width = 0
        self._height = 0
        self._last_error = ""
        self._sequence = 0

    # -- lifecycle ---------------------------------------------------------
    @abc.abstractmethod
    def open(self) -> bool:
        """Prepare the source. Returns True when it is ready to capture.

        Implementations should return ``False`` (and set ``last_error``) for an
        expected, retryable condition such as "no sender yet", and raise
        :class:`SourceError` only for a genuinely unrecoverable setup failure.
        """

    @abc.abstractmethod
    def close(self) -> None:
        """Release every resource. Must tolerate being called repeatedly."""

    @abc.abstractmethod
    def capture(self, pool: FrameBufferPool) -> Frame | None:
        """Grab the next frame, or ``None`` when none is available yet.

        Returning ``None`` is normal: the sender may not have produced a new
        frame since the last call, or the pool may be momentarily empty.
        """

    # -- state -------------------------------------------------------------
    @property
    def state(self) -> SourceState:
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._state is SourceState.CONNECTED

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def pixel_format(self) -> PixelFormat:
        return PixelFormat.RGBA8888

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def display_name(self) -> str:
        return self.kind

    def describe(self) -> SourceInfo:
        return SourceInfo(
            name=self.display_name,
            width=self._width,
            height=self._height,
            state=self._state,
            detail=self._last_error,
        )

    # -- helpers for subclasses -------------------------------------------
    def _set_state(self, state: SourceState, error: str = "") -> None:
        if state is not self._state or error != self._last_error:
            logger.debug("%s state: %s -> %s %s", self.kind, self._state, state, error)
        self._state = state
        self._last_error = error

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    # -- discovery ---------------------------------------------------------
    @staticmethod
    def list_senders() -> list[str]:
        """Names of senders this kind of source could connect to."""
        return []

    # -- context manager ---------------------------------------------------
    def __enter__(self) -> VideoSource:
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
