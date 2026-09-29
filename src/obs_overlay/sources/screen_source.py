"""Desktop capture: a monitor, or a rectangle within one.

Threading
---------
``QScreen.grabWindow`` is not safe to call from a worker thread, but the
producer runs its source on one. Rather than blocking the worker on the GUI
thread for every frame — which would deadlock against ``FrameProducer.stop()``,
since that waits for the worker *from* the GUI thread — the grabbing is pushed
the other way round:

* a small :class:`_ScreenGrabber` lives on the GUI thread and grabs on its own
  timer, publishing the newest image under a mutex;
* :meth:`ScreenSource.capture` merely picks up whatever is there.

``QImage`` is implicitly shared, so publishing is a refcount bump and the lock
is held for microseconds, never for the duration of a copy.

Self-capture
------------
Capturing the display the overlay is on makes the overlay photograph itself,
which recurses into an infinite tunnel. The source reports the rectangle it
captures so the application can hide the overlay from capture (or warn) when
the two overlap; see ``OverlayApplication._guard_screen_capture``.
"""

from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import (
    QCoreApplication,
    QMetaObject,
    QMutex,
    QMutexLocker,
    QObject,
    Qt,
    QTimer,
    pyqtSlot,
)
from PyQt6.QtGui import QGuiApplication, QImage, QScreen

from ..config.models import RectSpec
from ..core.frame import Frame, FrameBufferPool
from .base import SourceError, SourceState, VideoSource
from .qt_frames import frame_from_qimage

logger = logging.getLogger(__name__)

#: Never grab faster than this, whatever the profile's target rate says.
#: Desktop capture is expensive and nobody needs it above screen refresh.
_MAX_GRAB_FPS = 120

#: The window id meaning "the whole desktop". PyQt6's stub types grabWindow's
#: first argument as a ``voidptr``, but passing ``None`` raises at runtime —
#: the plain integer is what the binding actually accepts.
_WHOLE_DESKTOP: Any = 0


class _ScreenGrabber(QObject):
    """Grabs the desktop on the GUI thread and publishes the latest image."""

    def __init__(self, monitor_index: int, region: RectSpec | None, interval_ms: int) -> None:
        super().__init__()
        self._monitor_index = monitor_index
        self._region = region
        self._interval_ms = max(1, interval_ms)
        self._timer: QTimer | None = None

        self._mutex = QMutex()
        self._image = QImage()
        self._sequence = 0
        self._error = ""

    # -- GUI-thread slots --------------------------------------------------
    @pyqtSlot()
    def start(self) -> None:
        """Begin grabbing. Must run on the GUI thread."""
        if self._timer is None:
            # Created here, not in __init__, so the timer belongs to the thread
            # that will actually run it.
            self._timer = QTimer(self)
            self._timer.setTimerType(Qt.TimerType.PreciseTimer)
            self._timer.timeout.connect(self._grab)
        self._timer.start(self._interval_ms)
        self._grab()

    @pyqtSlot()
    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()

    @pyqtSlot()
    def _grab(self) -> None:
        screen = self._screen()
        if screen is None:
            self._publish_error(f"Monitor {self._monitor_index} is not connected.")
            return

        try:
            if self._region is not None:
                pixmap = screen.grabWindow(
                    _WHOLE_DESKTOP,
                    self._region.x,
                    self._region.y,
                    self._region.width,
                    self._region.height,
                )
            else:
                pixmap = screen.grabWindow(_WHOLE_DESKTOP)
        except Exception as exc:  # pragma: no cover - platform dependent
            self._publish_error(f"Screen capture failed: {exc}")
            return

        if pixmap.isNull():
            self._publish_error("Screen capture returned nothing.")
            return

        image = pixmap.toImage()
        with QMutexLocker(self._mutex):
            self._image = image
            self._sequence += 1
            self._error = ""

    def _screen(self) -> QScreen | None:
        screens = QGuiApplication.screens()
        if not screens:
            return None
        if 0 <= self._monitor_index < len(screens):
            return screens[self._monitor_index]
        return None

    def _publish_error(self, message: str) -> None:
        with QMutexLocker(self._mutex):
            if self._error != message:
                logger.warning("%s", message)
            self._error = message

    # -- any thread --------------------------------------------------------
    def take(self) -> tuple[QImage, int, str]:
        """Latest image, its sequence number, and any pending error."""
        with QMutexLocker(self._mutex):
            return self._image, self._sequence, self._error


class ScreenSource(VideoSource):
    """Captures a monitor, or a region of one, as the overlay's content."""

    kind = "screen"

    def __init__(
        self,
        monitor_index: int = 0,
        region: RectSpec | None = None,
        target_fps: int = 60,
    ) -> None:
        super().__init__()
        self._monitor_index = max(0, monitor_index)
        self._region = region
        self._target_fps = max(1, min(_MAX_GRAB_FPS, target_fps))
        self._grabber: _ScreenGrabber | None = None
        self._last_sequence = 0

    # -- identity ----------------------------------------------------------
    @property
    def display_name(self) -> str:
        name = f"Monitor {self._monitor_index}"
        screens = QGuiApplication.screens()
        if 0 <= self._monitor_index < len(screens):
            label = screens[self._monitor_index].name()
            if label:
                name = f"{self._monitor_index}: {label}"
        if self._region is not None:
            name += f" ({self._region.width}×{self._region.height} region)"
        return name

    def captured_rect(self) -> RectSpec:
        """The captured area in virtual-desktop coordinates.

        Used to detect that the overlay is inside its own capture area.
        """
        screens = QGuiApplication.screens()
        if not (0 <= self._monitor_index < len(screens)):
            return RectSpec()
        geometry = screens[self._monitor_index].geometry()
        if self._region is None:
            return RectSpec(geometry.x(), geometry.y(), geometry.width(), geometry.height())
        return RectSpec(
            geometry.x() + self._region.x,
            geometry.y() + self._region.y,
            self._region.width,
            self._region.height,
        )

    # -- lifecycle ---------------------------------------------------------
    def open(self) -> bool:
        app = QCoreApplication.instance()
        if app is None:
            raise SourceError("Screen capture needs a running Qt application.")

        screens = QGuiApplication.screens()
        if not screens:
            raise SourceError("No screens are available to capture.")
        if self._monitor_index >= len(screens):
            self._set_state(
                SourceState.ERROR,
                f"Monitor {self._monitor_index} is not connected ({len(screens)} available).",
            )
            return False

        if self._region is not None and (self._region.width <= 0 or self._region.height <= 0):
            raise SourceError("The capture region has no area.")

        interval_ms = max(1, round(1000.0 / self._target_fps))
        grabber = _ScreenGrabber(self._monitor_index, self._region, interval_ms)
        # The grabber must live on the GUI thread; open() runs on the producer.
        grabber.moveToThread(app.thread())
        self._grabber = grabber
        self._last_sequence = 0

        # Queued, never blocking: a blocking call here could deadlock against
        # a GUI thread that is itself waiting for this producer to stop.
        QMetaObject.invokeMethod(grabber, "start", Qt.ConnectionType.QueuedConnection)

        self._set_state(SourceState.CONNECTING, "Starting desktop capture…")
        logger.info("Screen capture opened: %s", self.display_name)
        return True

    def close(self) -> None:
        grabber, self._grabber = self._grabber, None
        if grabber is not None:
            QMetaObject.invokeMethod(grabber, "stop", Qt.ConnectionType.QueuedConnection)
            grabber.deleteLater()
        self._set_state(SourceState.CLOSED)

    # -- capture -----------------------------------------------------------
    def capture(self, pool: FrameBufferPool) -> Frame | None:
        grabber = self._grabber
        if grabber is None:
            return None

        image, sequence, error = grabber.take()

        if error:
            self._set_state(SourceState.ERROR, error)
            return None

        if sequence == self._last_sequence or image.isNull():
            # Nothing new since the last poll; the overlay keeps the last frame.
            return None

        frame = frame_from_qimage(image, pool, sequence=self._next_sequence(), premultiplied=False)
        if frame is None:
            return None

        self._last_sequence = sequence
        if (frame.width, frame.height) != (self._width, self._height):
            self._width, self._height = frame.width, frame.height
            logger.info("Screen capture resolution: %dx%d", frame.width, frame.height)

        if self._state is not SourceState.CONNECTED:
            self._set_state(SourceState.CONNECTED)
        return frame

    # -- discovery ---------------------------------------------------------
    @staticmethod
    def list_senders() -> list[str]:
        """Every connected monitor, labelled for the source picker."""
        entries = []
        for index, screen in enumerate(QGuiApplication.screens()):
            rect = screen.geometry()
            label = screen.name() or f"Monitor {index}"
            entries.append(f"{index}: {label} ({rect.width()}×{rect.height()})")
        return entries


def available_monitors() -> list[tuple[int, str, RectSpec]]:
    """Connected monitors as ``(index, label, geometry)``."""
    result = []
    for index, screen in enumerate(QGuiApplication.screens()):
        rect = screen.geometry()
        result.append(
            (
                index,
                screen.name() or f"Monitor {index}",
                RectSpec(rect.x(), rect.y(), rect.width(), rect.height()),
            )
        )
    return result
