"""Turning a ``QImage`` into a pooled :class:`~obs_overlay.core.frame.Frame`.

Shared by the screen and image sources, which both produce their pixels through
Qt rather than through a native capture API.

The conversion is deliberately kept to two passes over the data — one
``convertToFormat`` and one copy — because at 1080p each full-resolution pass
costs a few milliseconds and the frame budget at 60 fps is 16.
"""

from __future__ import annotations

import logging
import time

from PyQt6.QtGui import QImage

from ..core.frame import (
    Frame,
    FrameBufferPool,
    PixelFormat,
    is_valid_dimensions,
    required_buffer_size,
)

logger = logging.getLogger(__name__)

#: The layout the rest of the pipeline expects from a Qt-produced frame.
_TARGET_FORMAT = QImage.Format.Format_RGBA8888


def to_rgba8888(image: QImage) -> QImage:
    """Return ``image`` in RGBA8888, converting only when it is not already.

    Converting from an opaque format (a screen grab is RGB32) fills the alpha
    channel with 255, which is what an opaque source should look like.
    """
    if image.format() is _TARGET_FORMAT:
        return image
    return image.convertToFormat(_TARGET_FORMAT)


def frame_from_qimage(
    image: QImage,
    pool: FrameBufferPool,
    sequence: int,
    premultiplied: bool = False,
) -> Frame | None:
    """Copy ``image`` into a pooled buffer and wrap it as a frame.

    Returns ``None`` when the image is unusable or the pool is momentarily
    empty — both are normal conditions the producer handles by skipping.
    """
    if image.isNull():
        return None

    converted = to_rgba8888(image)
    width, height = converted.width(), converted.height()
    if not is_valid_dimensions(width, height):
        logger.debug("Refusing a frame of %dx%d", width, height)
        return None

    needed = required_buffer_size(width, height)
    if pool.buffer_size != needed:
        pool.resize(needed)

    buffer = pool.acquire()
    if buffer is None:
        return None

    try:
        _copy_pixels(converted, buffer.data, width, height, needed)
    except Exception:
        buffer.release()
        raise

    return Frame(
        width=width,
        height=height,
        pixel_format=PixelFormat.RGBA8888,
        buffer=buffer,
        sequence=sequence,
        timestamp=time.perf_counter(),
        premultiplied=premultiplied,
    )


def _copy_pixels(
    image: QImage,
    destination: bytearray,
    width: int,
    height: int,
    needed: int,
) -> None:
    """Copy an RGBA8888 QImage's pixels into a tightly packed buffer.

    Qt may pad each row to a hardware-friendly alignment, so a whole-buffer
    copy is only valid when the image happens to be tightly packed. It usually
    is at 4 bytes per pixel, but a region grab of an odd width can differ, and
    silently copying the padding would skew every row.
    """
    stride = width * 4
    bytes_per_line = image.bytesPerLine()

    bits = image.constBits()
    if bits is None:  # pragma: no cover - only on a null image
        raise ValueError("QImage has no pixel data")

    # PyQt6's sip.voidptr supports the buffer protocol once it has been given
    # a size; the stub does not model that, hence the ignores. Going through
    # a memoryview avoids the extra copy that .asstring() would make.
    if bytes_per_line == stride:
        bits.setsize(image.sizeInBytes())
        destination[:needed] = memoryview(bits)  # type: ignore[arg-type]
        return

    bits.setsize(bytes_per_line * height)
    source = memoryview(bits)  # type: ignore[arg-type]
    for row in range(height):
        start = row * bytes_per_line
        destination[row * stride : (row + 1) * stride] = source[start : start + stride]
