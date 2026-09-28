"""Buffer pool, frame lifetime, timing statistics and the demo source."""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from obs_overlay.constants import MAX_FRAME_DIMENSION
from obs_overlay.core.fps import FrameStats, RateLimiter
from obs_overlay.core.frame import (
    Frame,
    FrameBufferPool,
    PixelFormat,
    is_valid_dimensions,
    required_buffer_size,
)
from obs_overlay.sources.base import SourceState
from obs_overlay.sources.demo_source import DemoSource


class TestBufferPool:
    def test_acquire_until_empty(self):
        pool = FrameBufferPool(64, count=2)
        first = pool.acquire()
        second = pool.acquire()
        assert first is not None and second is not None
        assert pool.acquire() is None
        assert pool.free_count == 0
        assert pool.outstanding == 2

    def test_release_returns_capacity(self):
        pool = FrameBufferPool(64, count=1)
        buffer = pool.acquire()
        assert pool.acquire() is None
        buffer.release()
        assert pool.acquire() is not None

    def test_double_release_is_harmless(self):
        pool = FrameBufferPool(64, count=2)
        buffer = pool.acquire()
        buffer.release()
        buffer.release()
        assert pool.free_count == 2

    def test_context_manager_releases(self):
        pool = FrameBufferPool(64, count=1)
        with pool.acquire() as buffer:
            assert len(buffer) == 64
        assert pool.free_count == 1

    def test_buffers_are_writable_and_sized(self):
        pool = FrameBufferPool(16, count=1)
        buffer = pool.acquire()
        buffer.data[0] = 7
        assert buffer.data[0] == 7
        assert len(buffer.data) == 16

    def test_resize_invalidates_old_generation(self):
        pool = FrameBufferPool(16, count=2)
        stale = pool.acquire()
        pool.resize(32)
        assert pool.buffer_size == 32
        assert pool.free_count == 2
        stale.release()  # must not push an undersized buffer back
        assert pool.free_count == 2
        fresh = pool.acquire()
        assert len(fresh.data) == 32

    def test_resize_to_same_size_is_a_noop(self):
        pool = FrameBufferPool(16, count=2)
        generation = pool.generation
        pool.resize(16)
        assert pool.generation == generation

    def test_clear_drops_everything(self):
        pool = FrameBufferPool(16, count=2)
        pool.acquire()
        pool.clear()
        assert pool.free_count == 0
        assert pool.acquire() is None

    def test_acquire_with_timeout_waits_for_release(self):
        pool = FrameBufferPool(16, count=1)
        held = pool.acquire()

        def release_soon():
            time.sleep(0.05)
            held.release()

        threading.Thread(target=release_soon, daemon=True).start()
        started = time.perf_counter()
        buffer = pool.acquire(timeout=1.0)
        assert buffer is not None
        assert time.perf_counter() - started >= 0.03

    def test_invalid_construction(self):
        with pytest.raises(ValueError):
            FrameBufferPool(-1, 1)
        with pytest.raises(ValueError):
            FrameBufferPool(16, 0)

    def test_thread_safety_under_contention(self):
        pool = FrameBufferPool(1024, count=4)
        errors = []

        def worker():
            for _ in range(200):
                buffer = pool.acquire()
                if buffer is None:
                    continue
                try:
                    buffer.data[0] = 1
                finally:
                    buffer.release()

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert not errors
        assert pool.free_count == 4
        assert pool.outstanding == 0


class TestFrame:
    def test_dimensions_and_size(self):
        pool = FrameBufferPool(required_buffer_size(4, 3), 1)
        frame = Frame(4, 3, PixelFormat.RGBA8888, pool.acquire())
        assert frame.stride == 16
        assert frame.size_bytes == 48
        frame.release()

    def test_context_manager(self):
        pool = FrameBufferPool(16, 1)
        with Frame(2, 2, PixelFormat.RGBA8888, pool.acquire()):
            assert pool.free_count == 0
        assert pool.free_count == 1

    def test_dimension_validation(self):
        assert is_valid_dimensions(1920, 1080)
        assert not is_valid_dimensions(0, 100)
        assert not is_valid_dimensions(-1, 100)
        assert not is_valid_dimensions(MAX_FRAME_DIMENSION + 1, 10)

    def test_required_buffer_size(self):
        assert required_buffer_size(1920, 1080) == 1920 * 1080 * 4


class TestFrameStats:
    def test_fps_from_even_intervals(self):
        stats = FrameStats()
        for index in range(11):
            stats.record_frame(when=index * 0.01)  # 100 fps
        assert stats.fps == pytest.approx(100.0, rel=0.01)

    def test_fps_needs_two_samples(self):
        stats = FrameStats()
        assert stats.fps == 0.0
        stats.record_frame(when=1.0)
        assert stats.fps == 0.0

    def test_jitter_zero_for_steady_feed(self):
        stats = FrameStats()
        for index in range(20):
            stats.record_frame(when=index * 0.016)
        assert stats.jitter_ms == pytest.approx(0.0, abs=0.01)

    def test_jitter_detects_irregularity(self):
        stats = FrameStats()
        times = [0.0, 0.016, 0.100, 0.116, 0.200]
        for value in times:
            stats.record_frame(when=value)
        assert stats.jitter_ms > 10.0

    def test_drop_ratio(self):
        stats = FrameStats()
        for index in range(9):
            stats.record_frame(when=index * 0.01)
        stats.record_drop()
        assert stats.snapshot().drop_ratio == pytest.approx(0.1)

    def test_snapshot_carries_source_info(self):
        stats = FrameStats()
        stats.set_source("Sender", 1920, 1080)
        stats.set_connected(True)
        snapshot = stats.snapshot()
        assert snapshot.source_name == "Sender"
        assert (snapshot.source_width, snapshot.source_height) == (1920, 1080)
        assert snapshot.connected

    def test_disconnect_clears_the_window(self):
        stats = FrameStats()
        for index in range(5):
            stats.record_frame(when=index * 0.01)
        stats.set_connected(False)
        assert stats.fps == 0.0

    def test_reset(self):
        stats = FrameStats()
        stats.record_frame()
        stats.record_drop()
        stats.reset()
        snapshot = stats.snapshot()
        assert snapshot.frames_received == 0
        assert snapshot.frames_dropped == 0


class TestRateLimiter:
    def test_interval_from_fps(self):
        assert RateLimiter(60).interval == pytest.approx(1 / 60)
        assert RateLimiter(0).interval == pytest.approx(1 / 0.1)

    def test_first_call_returns_a_full_interval(self):
        limiter = RateLimiter(100)
        assert limiter.time_until_next(now=0.0) == pytest.approx(0.01)

    def test_on_schedule_waits(self):
        limiter = RateLimiter(100)
        limiter.time_until_next(now=0.0)
        assert limiter.time_until_next(now=0.005) == pytest.approx(0.005, abs=1e-6)

    def test_slightly_behind_does_not_burst(self):
        limiter = RateLimiter(100)
        limiter.time_until_next(now=0.0)
        assert limiter.time_until_next(now=0.015) == 0.0

    def test_far_behind_resets_the_schedule(self):
        limiter = RateLimiter(100)
        limiter.time_until_next(now=0.0)
        assert limiter.time_until_next(now=10.0) == 0.0
        # Schedule is rebased on now, not chasing ten seconds of backlog.
        assert limiter.time_until_next(now=10.0) == pytest.approx(0.01, abs=1e-6)

    def test_set_target_resets(self):
        limiter = RateLimiter(100)
        limiter.time_until_next(now=0.0)
        limiter.set_target_fps(10)
        assert limiter.interval == pytest.approx(0.1)


class TestDemoSource:
    def test_open_and_capture(self):
        source = DemoSource(320, 180)
        assert source.open()
        assert source.state is SourceState.CONNECTED

        pool = FrameBufferPool(required_buffer_size(320, 180), 2)
        frame = source.capture(pool)
        assert frame is not None
        assert (frame.width, frame.height) == (320, 180)
        assert frame.size_bytes == 320 * 180 * 4
        frame.release()
        source.close()

    def test_demo_alpha_is_straight_not_premultiplied(self):
        # The pattern is generated with straight alpha; the overlay picks its
        # QImage format from this flag, so it has to be right.
        source = DemoSource(64, 64)
        source.open()
        pool = FrameBufferPool(required_buffer_size(64, 64), 1)
        frame = source.capture(pool)
        assert frame.premultiplied is False
        frame.release()

    def test_pattern_has_real_transparency(self):
        source = DemoSource(320, 180)
        source.open()
        pool = FrameBufferPool(required_buffer_size(320, 180), 1)
        frame = source.capture(pool)
        pixels = np.frombuffer(
            bytes(frame.buffer.data[: frame.size_bytes]), dtype=np.uint8
        ).reshape(180, 320, 4)
        alpha = pixels[..., 3]
        assert alpha.min() == 0, "the pattern must contain fully transparent pixels"
        assert alpha.max() == 255, "the pattern must contain fully opaque pixels"
        assert 0.3 < float((alpha < 8).mean()) < 0.99
        frame.release()

    def test_pattern_animates(self):
        source = DemoSource(160, 90)
        source.open()
        pool = FrameBufferPool(required_buffer_size(160, 90), 2)
        first = source.capture(pool)
        snapshot = bytes(first.buffer.data[: first.size_bytes])
        first.release()
        time.sleep(0.08)
        second = source.capture(pool)
        assert bytes(second.buffer.data[: second.size_bytes]) != snapshot
        second.release()

    def test_sequence_increments(self):
        source = DemoSource(64, 64)
        source.open()
        pool = FrameBufferPool(required_buffer_size(64, 64), 2)
        first = source.capture(pool)
        second = source.capture(pool)
        assert second.sequence > first.sequence
        first.release()
        second.release()

    def test_capture_returns_none_when_pool_is_empty(self):
        source = DemoSource(64, 64)
        source.open()
        pool = FrameBufferPool(required_buffer_size(64, 64), 1)
        held = source.capture(pool)
        assert source.capture(pool) is None
        held.release()

    def test_pool_is_resized_to_match(self):
        source = DemoSource(64, 64)
        source.open()
        pool = FrameBufferPool(16, 2)  # deliberately too small
        frame = source.capture(pool)
        assert pool.buffer_size == required_buffer_size(64, 64)
        frame.release()

    def test_resolution_change(self):
        source = DemoSource(64, 64)
        source.open()
        source.set_resolution(128, 96)
        pool = FrameBufferPool(required_buffer_size(128, 96), 1)
        frame = source.capture(pool)
        assert (frame.width, frame.height) == (128, 96)
        frame.release()

    def test_capture_before_open_returns_none(self):
        source = DemoSource(64, 64)
        pool = FrameBufferPool(required_buffer_size(64, 64), 1)
        assert source.capture(pool) is None

    def test_close_is_idempotent(self):
        source = DemoSource(64, 64)
        source.open()
        source.close()
        source.close()
        assert source.state is SourceState.CLOSED

    def test_rejects_absurd_resolution(self):
        with pytest.raises(ValueError):
            DemoSource(0, 100)
        with pytest.raises(ValueError):
            DemoSource(MAX_FRAME_DIMENSION * 2, 100)

    @pytest.mark.parametrize("size", [(1920, 1080), (1366, 768), (1921, 1081), (100, 100)])
    def test_arbitrary_resolutions_produce_exact_buffers(self, size):
        width, height = size
        source = DemoSource(width, height)
        source.open()
        pool = FrameBufferPool(required_buffer_size(width, height), 1)
        frame = source.capture(pool)
        assert frame.size_bytes == width * height * 4
        frame.release()

    def test_describe(self):
        source = DemoSource(64, 64)
        source.open()
        info = source.describe()
        assert info.state is SourceState.CONNECTED
        assert info.resolution == "64×64"
