"""The receiver thread.

One :class:`FrameProducer` owns one :class:`~obs_overlay.sources.base.VideoSource`
for the thread's whole lifetime, which is required for Spout: WGL contexts are
thread-affine, so every receive call must happen on the thread that created the
context.

Frames are published *latest-wins*: if the GUI thread has not picked up the
previous frame by the time a new one arrives, the old one is released and
counted as dropped. Queueing frames instead would trade latency for a
smoothness nobody can perceive — on an overlay, a fresh frame always beats a
complete sequence.
"""

from __future__ import annotations

import logging
import threading
import time
from copy import deepcopy

from PyQt6.QtCore import QMutex, QMutexLocker, QThread, pyqtSignal

from ..config.models import SourceKind, SourceSettings
from ..constants import FRAME_POOL_SIZE, RECONNECT_INTERVAL_S
from ..sources.base import SourceError, SourceInfo, SourceState, VideoSource
from ..sources.registry import create_source
from .fps import FrameStats, RateLimiter, StatsSnapshot
from .frame import Frame, FrameBufferPool

logger = logging.getLogger(__name__)

#: How long a failed open() is backed off before retrying, in seconds.
_MIN_RETRY_S = RECONNECT_INTERVAL_S
_MAX_RETRY_S = 8.0


class FrameProducer(QThread):
    """Background thread that keeps a video source connected and pumping."""

    #: Emitted when a new frame is waiting. Collect it with :meth:`take_frame`.
    frameAvailable = pyqtSignal()
    #: Emitted when the connection state or resolution changes.
    statusChanged = pyqtSignal(object)  # SourceInfo
    #: Emitted once per unrecoverable setup failure, with a user-facing message.
    failed = pyqtSignal(str)

    def __init__(self, settings: SourceSettings, parent: object | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        # Snapshotted, never aliased: the control panel edits the profile's
        # settings object in place, so holding a reference to it would make
        # `_needs_reopen` compare an object with itself and never see a change.
        self._settings = deepcopy(settings)
        self._pending_settings: SourceSettings | None = None
        self._settings_lock = threading.Lock()

        self._frame_mutex = QMutex()
        self._latest: Frame | None = None
        #: True while a frameAvailable signal is queued but not yet handled.
        self._notify_pending = False

        self._running = False
        self._reconnect_requested = False
        #: Why the last open() attempt failed, so the reason survives the
        #: source being closed and discarded and still reaches the UI.
        self._last_open_failure = SourceInfo()
        self._stats = FrameStats()
        self._pool = FrameBufferPool(0, FRAME_POOL_SIZE)
        self._last_info = SourceInfo()

    # -- public API --------------------------------------------------------
    @property
    def stats(self) -> FrameStats:
        return self._stats

    def stats_snapshot(self) -> StatsSnapshot:
        return self._stats.snapshot()

    def take_frame(self) -> Frame | None:
        """Claim the newest frame, transferring ownership to the caller.

        The caller must call ``frame.release()`` when it is done painting.
        Returns ``None`` when nothing new has arrived.
        """
        with QMutexLocker(self._frame_mutex):
            frame, self._latest = self._latest, None
            # Re-arm the notification: the next published frame emits again.
            self._notify_pending = False
        return frame

    def apply_settings(self, settings: SourceSettings) -> None:
        """Hand new settings to the loop; it reopens the source if needed.

        The settings are copied. Callers pass the live profile object, which
        they go on mutating, and the loop has to be able to tell what actually
        changed since the last time it looked.
        """
        with self._settings_lock:
            self._pending_settings = deepcopy(settings)

    def request_reconnect(self) -> None:
        self._reconnect_requested = True

    def stop(self, timeout_ms: int = 4000) -> None:
        """Ask the loop to finish and wait for it."""
        self._running = False
        if not self.wait(timeout_ms):  # pragma: no cover - timing dependent
            logger.warning("Frame producer did not stop within %d ms; terminating.", timeout_ms)
            self.terminate()
            self.wait(1000)
        self._discard_pending_frame()
        self._pool.clear()

    # -- internals ---------------------------------------------------------
    def _discard_pending_frame(self) -> None:
        with QMutexLocker(self._frame_mutex):
            frame, self._latest = self._latest, None
            self._notify_pending = False
        if frame is not None:
            frame.release()

    def _publish(self, frame: Frame) -> None:
        """Hand the newest frame to the consumer, replacing any unclaimed one.

        The notification is *coalesced*: a second signal is not emitted while
        one is still waiting to be handled. Emitting per frame would post an
        unbounded number of events at the frame rate, and a GUI thread that
        cannot keep up would never drain the queue — starving timers and
        leaving the whole application unresponsive. Since only the newest frame
        is ever served, one pending notification is all that means anything.
        """
        with QMutexLocker(self._frame_mutex):
            previous, self._latest = self._latest, frame
            notify = not self._notify_pending
            self._notify_pending = True
        if previous is not None:
            previous.release()
            self._stats.record_drop()
        if notify:
            self.frameAvailable.emit()

    def _emit_status(self, source: VideoSource | None) -> None:
        self._emit_info(source.describe() if source is not None else SourceInfo())

    def _emit_info(self, info: SourceInfo) -> None:
        """Publish a status change, but only when something actually changed.

        The GUI repaints on every one of these, so an unchanged status must not
        be re-emitted at the producer's poll rate.
        """
        if (
            info.state != self._last_info.state
            or info.name != self._last_info.name
            or info.width != self._last_info.width
            or info.height != self._last_info.height
            or info.detail != self._last_info.detail
        ):
            self._last_info = info
            self._stats.set_connected(info.state is SourceState.CONNECTED)
            self._stats.set_source(info.name, info.width, info.height)
            self.statusChanged.emit(info)

    def _take_pending_settings(self) -> SourceSettings | None:
        with self._settings_lock:
            pending, self._pending_settings = self._pending_settings, None
        return pending

    @staticmethod
    def _needs_reopen(old: SourceSettings, new: SourceSettings) -> bool:
        """Whether a settings change requires building a fresh source.

        Everything a source reads at construction counts, which is most of its
        own settings group. ``target_fps`` deliberately does not: the producer
        re-paces its limiter in place, and reconnecting mid-stream just to
        change the poll rate would drop frames for no reason.

        Only the *active* kind's group is compared. Editing the NDI source name
        while running on Spout must not interrupt the Spout feed.
        """
        if old.kind is not new.kind or old.fallback_to_demo != new.fallback_to_demo:
            return True

        if new.kind is SourceKind.SPOUT:
            return old.spout != new.spout
        if new.kind is SourceKind.NDI:
            return old.ndi != new.ndi
        if new.kind is SourceKind.SCREEN:
            # The grabber's timer interval is fixed at open(), so a rate change
            # does matter here, unlike for the pull-based sources.
            return old.screen != new.screen or old.target_fps != new.target_fps
        if new.kind is SourceKind.IMAGE:
            return old.image != new.image
        return False

    # -- the loop ----------------------------------------------------------
    def run(self) -> None:
        self._running = True
        source: VideoSource | None = None
        limiter = RateLimiter(self._settings.target_fps)
        retry_delay = _MIN_RETRY_S
        next_open_attempt = 0.0

        logger.info("Frame producer started.")
        try:
            while self._running:
                pending = self._take_pending_settings()
                if pending is not None:
                    reopen = self._needs_reopen(self._settings, pending)
                    if pending.target_fps != self._settings.target_fps:
                        limiter.set_target_fps(pending.target_fps)
                    self._settings = pending
                    if reopen:
                        self._reconnect_requested = True

                if self._reconnect_requested:
                    self._reconnect_requested = False
                    self._close_source(source)
                    source = None
                    self._discard_pending_frame()
                    retry_delay = _MIN_RETRY_S
                    next_open_attempt = 0.0

                now = time.perf_counter()
                if source is None:
                    if now < next_open_attempt:
                        self.msleep(20)
                        continue
                    source = self._open_source()
                    if source is None:
                        next_open_attempt = now + retry_delay
                        retry_delay = min(_MAX_RETRY_S, retry_delay * 2)
                        self._emit_info(self._last_open_failure)
                        continue
                    retry_delay = _MIN_RETRY_S
                    limiter.reset()

                try:
                    frame = source.capture(self._pool)
                except SourceError as exc:
                    logger.error("Source error: %s", exc)
                    self.failed.emit(str(exc))
                    self._close_source(source)
                    source = None
                    next_open_attempt = time.perf_counter() + retry_delay
                    retry_delay = min(_MAX_RETRY_S, retry_delay * 2)
                    continue
                except Exception as exc:  # pragma: no cover - native failures
                    logger.exception("Unexpected capture failure: %s", exc)
                    self._close_source(source)
                    source = None
                    next_open_attempt = time.perf_counter() + retry_delay
                    retry_delay = min(_MAX_RETRY_S, retry_delay * 2)
                    continue

                if frame is not None:
                    self._stats.record_frame(frame.timestamp)
                    self._publish(frame)

                self._emit_status(source)

                # Pace the loop. When no frame arrived we still sleep, so a
                # disconnected sender does not spin the CPU.
                wait = limiter.time_until_next()
                if wait > 0:
                    self.msleep(max(1, int(wait * 1000)))
        finally:
            self._close_source(source)
            self._discard_pending_frame()
            self._pool.clear()
            logger.info("Frame producer stopped.")

    def _open_source(self) -> VideoSource | None:
        self._last_open_failure = SourceInfo()
        try:
            source = create_source(self._settings)
        except SourceError as exc:
            logger.error("Could not create source: %s", exc)
            self._record_open_failure(str(exc))
            self.failed.emit(str(exc))
            return None
        except Exception as exc:  # pragma: no cover
            logger.exception("Unexpected source construction failure")
            self._record_open_failure(str(exc))
            self.failed.emit(str(exc))
            return None

        try:
            if not source.open():
                # Capture the reason before close() resets the source's state,
                # otherwise a failure like "image not found" never reaches the
                # UI and the overlay just sits there blank.
                self._last_open_failure = source.describe()
                logger.debug("Source not ready: %s", source.last_error)
                self._close_source(source)
                return None
        except SourceError as exc:
            logger.error("Could not open source: %s", exc)
            self._record_open_failure(str(exc), source)
            self.failed.emit(str(exc))
            self._close_source(source)
            return None
        except Exception as exc:  # pragma: no cover
            logger.exception("Unexpected source open failure")
            self._record_open_failure(str(exc), source)
            self.failed.emit(str(exc))
            self._close_source(source)
            return None

        return source

    def _record_open_failure(self, detail: str, source: VideoSource | None = None) -> None:
        self._last_open_failure = SourceInfo(
            name=source.display_name if source is not None else "",
            state=SourceState.ERROR,
            detail=detail,
        )

    @staticmethod
    def _close_source(source: VideoSource | None) -> None:
        if source is None:
            return
        try:
            source.close()
        except Exception:  # pragma: no cover
            logger.exception("Error while closing source")
