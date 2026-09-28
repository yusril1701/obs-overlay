"""Frame representation and a recycling buffer pool.

A 1920×1080 RGBA frame is 8 MB. Allocating one per frame at 60 fps would churn
half a gigabyte per second through the allocator, so the receiver thread fills
buffers borrowed from a small fixed pool and the GUI thread hands them back
once it has painted.

Ownership rule: exactly one party owns a :class:`PooledBuffer` at a time. The
producer owns it from ``acquire`` until it publishes the frame; the consumer
owns it from then until ``release``. When the pool is empty the producer drops
the frame instead of blocking, which keeps latency bounded — a late frame is
worth less than a fresh one.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum

from ..constants import MAX_FRAME_DIMENSION


class PixelFormat(str, Enum):
    """Byte order of a frame's pixels, in memory order."""

    RGBA8888 = "rgba8888"
    BGRA8888 = "bgra8888"

    @property
    def bytes_per_pixel(self) -> int:
        return 4


class BufferPoolExhausted(RuntimeError):
    """No buffer was free within the requested timeout."""


class PooledBuffer:
    """A borrowed slab of memory belonging to a :class:`FrameBufferPool`."""

    __slots__ = ("_data", "_generation", "_lock", "_pool", "_released")

    def __init__(self, pool: FrameBufferPool, data: bytearray, generation: int) -> None:
        self._pool = pool
        self._data = data
        self._generation = generation
        self._released = False
        self._lock = threading.Lock()

    @property
    def data(self) -> bytearray:
        return self._data

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def released(self) -> bool:
        return self._released

    def __len__(self) -> int:
        return len(self._data)

    def release(self) -> None:
        """Hand the memory back. Safe to call more than once."""
        with self._lock:
            if self._released:
                return
            self._released = True
        self._pool._recycle(self)

    def __enter__(self) -> PooledBuffer:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()


class FrameBufferPool:
    """Fixed-size pool of equally sized byte buffers.

    ``resize`` is what happens when the Spout sender changes resolution: the
    pool starts a new *generation*, and buffers from older generations are
    dropped rather than recycled when they come back.
    """

    def __init__(self, buffer_size: int, count: int = 3) -> None:
        if buffer_size < 0:
            raise ValueError("buffer_size must be >= 0")
        if count < 1:
            raise ValueError("count must be >= 1")
        self._lock = threading.Lock()
        self._available_changed = threading.Condition(self._lock)
        self._buffer_size = buffer_size
        self._count = count
        self._generation = 0
        self._free: list[bytearray] = [bytearray(buffer_size) for _ in range(count)]
        self._outstanding = 0

    # -- introspection -----------------------------------------------------
    @property
    def buffer_size(self) -> int:
        with self._lock:
            return self._buffer_size

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def free_count(self) -> int:
        with self._lock:
            return len(self._free)

    @property
    def outstanding(self) -> int:
        with self._lock:
            return self._outstanding

    # -- lifecycle ---------------------------------------------------------
    def resize(self, buffer_size: int) -> None:
        """Change the buffer size, invalidating everything currently lent out."""
        if buffer_size < 0:
            raise ValueError("buffer_size must be >= 0")
        with self._lock:
            if buffer_size == self._buffer_size:
                return
            self._buffer_size = buffer_size
            self._generation += 1
            self._free = [bytearray(buffer_size) for _ in range(self._count)]
            self._outstanding = 0
            self._available_changed.notify_all()

    def acquire(self, timeout: float = 0.0) -> PooledBuffer | None:
        """Borrow a buffer, or ``None`` if none became free in time."""
        with self._available_changed:
            if not self._free and timeout > 0:
                self._available_changed.wait(timeout)
            if not self._free:
                return None
            data = self._free.pop()
            self._outstanding += 1
            return PooledBuffer(self, data, self._generation)

    def _recycle(self, buffer: PooledBuffer) -> None:
        with self._available_changed:
            # A buffer from a superseded generation is simply dropped; its
            # memory is freed when the last reference goes away.
            if buffer.generation != self._generation:
                return
            if len(self._free) < self._count:
                self._free.append(buffer.data)
            self._outstanding = max(0, self._outstanding - 1)
            self._available_changed.notify()

    def clear(self) -> None:
        """Drop every buffer, e.g. when the source closes."""
        with self._available_changed:
            self._generation += 1
            self._free = []
            self._outstanding = 0
            self._available_changed.notify_all()


@dataclass
class Frame:
    """One decoded video frame, pointing at pooled memory.

    ``buffer`` must be released exactly once, by whoever last consumes it.
    """

    width: int
    height: int
    pixel_format: PixelFormat
    buffer: PooledBuffer
    sequence: int = 0
    timestamp: float = 0.0
    #: True when colour channels are already multiplied by alpha. Spout senders
    #: fed from OBS deliver straight (non-premultiplied) alpha.
    premultiplied: bool = False
    metadata: dict = field(default_factory=dict)

    @property
    def stride(self) -> int:
        return self.width * self.pixel_format.bytes_per_pixel

    @property
    def size_bytes(self) -> int:
        return self.stride * self.height

    def release(self) -> None:
        self.buffer.release()

    def __enter__(self) -> Frame:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()


def is_valid_dimensions(width: int, height: int) -> bool:
    """Reject absurd sender dimensions before allocating anything."""
    return 0 < width <= MAX_FRAME_DIMENSION and 0 < height <= MAX_FRAME_DIMENSION


def required_buffer_size(width: int, height: int) -> int:
    return width * height * 4
