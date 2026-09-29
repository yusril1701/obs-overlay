"""A still or animated image as the overlay's content.

The simplest source there is, and often the most useful one: a PNG with an
alpha channel is exactly what most people want an overlay to be — a logo, a
frame, a lower third — and it needs neither OBS nor a network.

Efficiency
----------
A still image publishes exactly one frame and then reports "nothing new" for
ever after. The overlay holds the last frame it was given, so the picture stays
on screen while the pipeline goes completely idle. Animated files (GIF, WebP)
publish a frame only when the animation advances.

The frame is republished if the first attempt could not be delivered — for
instance because the buffer pool was momentarily empty — otherwise a still
image could be lost and the overlay would stay blank for ever.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtGui import QImage, QImageReader, QMovie

from ..core.frame import Frame, FrameBufferPool, is_valid_dimensions
from .base import SourceError, SourceState, VideoSource
from .qt_frames import frame_from_qimage

logger = logging.getLogger(__name__)

#: Formats Qt can animate. Everything else is treated as a still.
_ANIMATED_SUFFIXES = {".gif", ".webp", ".mng"}


def supported_image_filter() -> str:
    """A Qt file-dialog filter listing every readable image format."""
    formats = sorted(
        {bytes(fmt.data()).decode().lower() for fmt in QImageReader.supportedImageFormats()}
    )
    patterns = " ".join(f"*.{fmt}" for fmt in formats)
    return f"Images ({patterns});;All files (*)"


class ImageSource(VideoSource):
    """Shows an image file, animating it when the format supports it."""

    kind = "image"

    def __init__(self, path: str = "", animate: bool = True) -> None:
        super().__init__()
        self._path = path
        self._animate = animate
        self._image: QImage | None = None
        self._movie: QMovie | None = None
        self._pending = False
        self._last_movie_frame = -1

    # -- identity ----------------------------------------------------------
    @property
    def display_name(self) -> str:
        if not self._path:
            return "(no image)"
        return Path(self._path).name

    @property
    def is_animated(self) -> bool:
        return self._movie is not None

    # -- lifecycle ---------------------------------------------------------
    def open(self) -> bool:
        if not self._path:
            raise SourceError("No image file has been chosen.")

        path = Path(self._path)
        if not path.is_file():
            self._set_state(SourceState.ERROR, f"Image not found: {path}")
            return False

        wants_animation = self._animate and path.suffix.lower() in _ANIMATED_SUFFIXES
        if wants_animation and self._open_animation(path):
            return True

        # Falls through to a still when the file is not animatable: a
        # single-frame GIF is perfectly valid, and so is one Qt declines to
        # animate.
        return self._open_still(path)

    def _open_animation(self, path: Path) -> bool:
        if QCoreApplication.instance() is None:  # pragma: no cover - defensive
            raise SourceError("Animated images need a running Qt application.")

        movie = QMovie(str(path))
        if not movie.isValid():
            logger.debug("QMovie cannot read %s; falling back to a still.", path)
            return False
        if movie.frameCount() == 1:
            return False

        # Cache every frame: the alternative re-decodes from the start on each
        # loop, which for a long GIF is far more work than the memory costs.
        movie.setCacheMode(QMovie.CacheMode.CacheAll)
        movie.start()

        self._movie = movie
        self._image = None
        self._pending = True
        self._last_movie_frame = -1

        size = movie.currentImage().size()
        self._width, self._height = size.width(), size.height()
        self._set_state(SourceState.CONNECTED)
        logger.info("Image source opened: %s (animated, %d frames)", path.name, movie.frameCount())
        return True

    def _open_still(self, path: Path) -> bool:
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)  # honour EXIF orientation
        image = reader.read()
        if image.isNull():
            self._set_state(
                SourceState.ERROR,
                f"Could not read {path.name}: {reader.errorString()}",
            )
            return False

        if not is_valid_dimensions(image.width(), image.height()):
            self._set_state(
                SourceState.ERROR,
                f"{path.name} has an unusable size ({image.width()}x{image.height()}).",
            )
            return False

        self._image = image
        self._movie = None
        self._pending = True
        self._width, self._height = image.width(), image.height()
        self._set_state(SourceState.CONNECTED)
        logger.info("Image source opened: %s (%dx%d)", path.name, image.width(), image.height())
        return True

    def close(self) -> None:
        if self._movie is not None:
            self._movie.stop()
        self._movie = None
        self._image = None
        self._pending = False
        self._set_state(SourceState.CLOSED)

    # -- capture -----------------------------------------------------------
    def capture(self, pool: FrameBufferPool) -> Frame | None:
        if self._state is not SourceState.CONNECTED:
            return None

        image = self._next_image()
        if image is None:
            return None

        frame = frame_from_qimage(
            image,
            pool,
            sequence=self._next_sequence(),
            # Qt decodes PNG/GIF/WebP to straight alpha.
            premultiplied=False,
        )
        if frame is None:
            # Could not deliver; keep it pending so the still is not lost.
            return None

        self._pending = False
        self._width, self._height = frame.width, frame.height
        return frame

    def _next_image(self) -> QImage | None:
        movie = self._movie
        if movie is None:
            return self._image if self._pending else None

        current = movie.currentFrameNumber()
        if current == self._last_movie_frame and not self._pending:
            return None
        self._last_movie_frame = current

        image = movie.currentImage()
        return None if image.isNull() else image

    # -- discovery ---------------------------------------------------------
    @staticmethod
    def list_senders() -> list[str]:
        return []
