"""Frame timing statistics for the debug HUD and the control panel."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class StatsSnapshot:
    """Immutable view of the counters, safe to hand across threads."""

    fps: float = 0.0
    frames_received: int = 0
    frames_dropped: int = 0
    frames_painted: int = 0
    last_frame_age_ms: float = 0.0
    avg_interval_ms: float = 0.0
    jitter_ms: float = 0.0
    source_width: int = 0
    source_height: int = 0
    source_name: str = ""
    connected: bool = False

    @property
    def drop_ratio(self) -> float:
        total = self.frames_received + self.frames_dropped
        return (self.frames_dropped / total) if total else 0.0


class FrameStats:
    """Rolling frame-rate tracker.

    Uses ``time.perf_counter`` throughout — a monotonic clock, so a system
    clock change cannot make the measured FPS jump.

    Not internally locked: the producer thread updates it and the GUI thread
    reads a :class:`StatsSnapshot`. Python's GIL makes the individual integer
    updates safe, and a slightly stale snapshot is fine for a debug readout.
    """

    def __init__(self, window: int = 120) -> None:
        self._window = max(2, window)
        self._timestamps: deque[float] = deque(maxlen=self._window)
        self._frames_received = 0
        self._frames_dropped = 0
        self._frames_painted = 0
        self._last_frame_time: float | None = None
        self._source_width = 0
        self._source_height = 0
        self._source_name = ""
        self._connected = False

    # -- mutation ----------------------------------------------------------
    def record_frame(self, when: float | None = None) -> None:
        now = time.perf_counter() if when is None else when
        self._timestamps.append(now)
        self._last_frame_time = now
        self._frames_received += 1

    def record_drop(self, count: int = 1) -> None:
        self._frames_dropped += count

    def record_paint(self) -> None:
        self._frames_painted += 1

    def set_source(self, name: str, width: int, height: int) -> None:
        self._source_name = name
        self._source_width = width
        self._source_height = height

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        if not connected:
            self._timestamps.clear()
            self._last_frame_time = None

    def reset(self) -> None:
        self._timestamps.clear()
        self._frames_received = 0
        self._frames_dropped = 0
        self._frames_painted = 0
        self._last_frame_time = None

    # -- derived values ----------------------------------------------------
    @property
    def fps(self) -> float:
        """Frames per second over the rolling window."""
        if len(self._timestamps) < 2:
            return 0.0
        span = self._timestamps[-1] - self._timestamps[0]
        if span <= 0:
            return 0.0
        return (len(self._timestamps) - 1) / span

    @property
    def average_interval_ms(self) -> float:
        fps = self.fps
        return (1000.0 / fps) if fps > 0 else 0.0

    @property
    def jitter_ms(self) -> float:
        """Mean absolute deviation of frame intervals, in milliseconds.

        A steady 60 fps feed sits near zero; a stuttering one climbs, which is
        more informative than the average alone.
        """
        if len(self._timestamps) < 3:
            return 0.0
        intervals = [
            self._timestamps[i + 1] - self._timestamps[i] for i in range(len(self._timestamps) - 1)
        ]
        mean = sum(intervals) / len(intervals)
        if mean <= 0:
            return 0.0
        deviation = sum(abs(value - mean) for value in intervals) / len(intervals)
        return deviation * 1000.0

    @property
    def last_frame_age_ms(self) -> float:
        if self._last_frame_time is None:
            return 0.0
        return max(0.0, (time.perf_counter() - self._last_frame_time) * 1000.0)

    def snapshot(self) -> StatsSnapshot:
        return StatsSnapshot(
            fps=self.fps,
            frames_received=self._frames_received,
            frames_dropped=self._frames_dropped,
            frames_painted=self._frames_painted,
            last_frame_age_ms=self.last_frame_age_ms,
            avg_interval_ms=self.average_interval_ms,
            jitter_ms=self.jitter_ms,
            source_width=self._source_width,
            source_height=self._source_height,
            source_name=self._source_name,
            connected=self._connected,
        )


class RateLimiter:
    """Simple frame pacer.

    ``time_until_next`` returns how long to sleep to hit the target rate. The
    schedule is advanced from the previous deadline rather than from "now", so
    a single slow frame does not permanently shift the cadence; falling more
    than one interval behind resets the schedule instead of bursting to catch
    up.
    """

    def __init__(self, target_fps: float) -> None:
        self._interval = 1.0 / max(0.1, target_fps)
        self._next_deadline: float | None = None

    @property
    def interval(self) -> float:
        return self._interval

    def set_target_fps(self, target_fps: float) -> None:
        self._interval = 1.0 / max(0.1, target_fps)
        self._next_deadline = None

    def time_until_next(self, now: float | None = None) -> float:
        current = time.perf_counter() if now is None else now
        if self._next_deadline is None:
            self._next_deadline = current + self._interval
            return self._interval
        wait = self._next_deadline - current
        if wait <= 0:
            behind = -wait
            if behind > self._interval:
                self._next_deadline = current + self._interval
            else:
                self._next_deadline += self._interval
            return 0.0
        self._next_deadline += self._interval
        return wait

    def reset(self) -> None:
        self._next_deadline = None
