"""The screen, image and NDI sources, plus source selection and migration.

Screen and image capture run for real here — the offscreen Qt platform grabs a
genuine surface — so these are not mocks. NDI cannot be exercised without the
runtime and a live sender, so only its guard rails are covered.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from obs_overlay.config.models import (
    ImageSettings,
    NdiSettings,
    Profile,
    RectSpec,
    ScreenSettings,
    SourceKind,
    SourceSettings,
    SpoutSettings,
)
from obs_overlay.core.frame import FrameBufferPool, required_buffer_size
from obs_overlay.sources.base import SourceError, SourceState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pool(width: int, height: int, count: int = 3) -> FrameBufferPool:
    return FrameBufferPool(required_buffer_size(width, height), count)


def _alpha_of(frame) -> np.ndarray:
    pixels = np.frombuffer(bytes(frame.buffer.data[: frame.size_bytes]), dtype=np.uint8)
    return pixels.reshape(frame.height, frame.width, 4)[..., 3]


@pytest.fixture()
def png_with_alpha(tmp_path, qapp):
    """A small PNG that is transparent in the corners and opaque in the middle."""
    from PyQt6.QtGui import QColor, QImage, QPainter

    image = QImage(120, 80, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.setBrush(QColor(200, 60, 60, 255))
    painter.setPen(QColor(255, 255, 255, 255))
    painter.drawEllipse(10, 10, 100, 60)
    painter.end()

    path = tmp_path / "alpha.png"
    assert image.save(str(path))
    return path


# ---------------------------------------------------------------------------
# Settings and migration
# ---------------------------------------------------------------------------


class TestSourceSettings:
    def test_round_trip(self):
        settings = SourceSettings(kind=SourceKind.NDI, target_fps=45)
        settings.ndi.source_name = "STUDIO (OBS)"
        settings.screen.region = RectSpec(5, 6, 7, 8)
        assert SourceSettings.from_dict(settings.to_dict()).to_dict() == settings.to_dict()

    def test_defaults_per_group(self):
        settings = SourceSettings()
        assert settings.spout.premultiplied_alpha is True
        assert settings.ndi.premultiplied_alpha is False
        assert settings.screen.use_region is False
        assert settings.image.animate is True

    def test_hostile_input(self):
        settings = SourceSettings.from_dict(
            {"kind": "nonsense", "spout": "not a dict", "ndi": 42, "screen": None, "image": []}
        )
        assert settings.kind is SourceKind.SPOUT
        assert settings.spout.sender_name
        assert isinstance(settings.screen.region, RectSpec)

    def test_zero_sized_region_is_repaired(self):
        settings = ScreenSettings.from_dict({"region": {"x": 0, "y": 0, "width": 0, "height": 0}})
        assert settings.region.width > 0
        assert settings.region.height > 0

    @pytest.mark.parametrize(
        "group",
        [SpoutSettings, NdiSettings, ScreenSettings, ImageSettings],
    )
    def test_each_group_round_trips_empty(self, group):
        assert group.from_dict({}).to_dict() == group().to_dict()


class TestMigrationToV3:
    def test_spout_fields_move_into_their_group(self):
        from obs_overlay.config.migrations import migrate

        migrated = migrate(
            {
                "schema_version": 2,
                "source": {
                    "kind": "spout",
                    "sender_name": "OBS_Sender",
                    "auto_select_sender": False,
                    "invert_y": True,
                    "premultiplied_alpha": True,
                    "target_fps": 30,
                },
            }
        )
        assert migrated["schema_version"] == 3
        assert migrated["source"]["spout"]["sender_name"] == "OBS_Sender"
        assert migrated["source"]["spout"]["invert_y"] is True
        assert migrated["source"]["spout"]["auto_select_sender"] is False
        # Common fields stay where they were.
        assert migrated["source"]["target_fps"] == 30
        # The old flat keys are gone.
        assert "sender_name" not in migrated["source"]

    def test_loads_into_a_profile(self):
        from obs_overlay.config.migrations import migrate

        profile = Profile.from_dict(
            migrate(
                {
                    "schema_version": 2,
                    "source": {"sender_name": "Kept", "invert_y": True},
                    "parcels": [{"x": 1, "y": 2, "width": 30, "height": 40}],
                }
            )
        )
        assert profile.source.spout.sender_name == "Kept"
        assert profile.source.spout.invert_y is True
        assert profile.parcels[0].width == 30

    def test_v1_migrates_all_the_way(self):
        from obs_overlay.config.migrations import migrate

        migrated = migrate({"schema_version": 1, "boxes": [[1, 2, 30, 40]], "sender": "Blueprint"})
        assert migrated["schema_version"] == 3
        profile = Profile.from_dict(migrated)
        assert profile.source.spout.sender_name == "Blueprint"
        assert len(profile.parcels) == 1

    def test_is_idempotent(self):
        from obs_overlay.config.migrations import migrate

        source = {"schema_version": 2, "source": {"sender_name": "X"}}
        once = migrate(source)
        assert migrate(dict(once)) == once

    def test_newer_value_wins_over_legacy(self):
        from obs_overlay.config.migrations import migrate

        migrated = migrate(
            {
                "schema_version": 2,
                "source": {"sender_name": "old", "spout": {"sender_name": "new"}},
            }
        )
        assert migrated["source"]["spout"]["sender_name"] == "new"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_builds_the_right_class_for_each_kind(self, qapp):
        from obs_overlay.sources.registry import create_source

        expected = {
            SourceKind.DEMO: "DemoSource",
            SourceKind.SCREEN: "ScreenSource",
            SourceKind.IMAGE: "ImageSource",
            SourceKind.SPOUT: "SpoutSource",
            SourceKind.NDI: "NdiSource",
        }
        for kind, name in expected.items():
            source = create_source(SourceSettings(kind=kind))
            assert type(source).__name__ == name

    def test_screen_settings_reach_the_source(self, qapp):
        from obs_overlay.sources.registry import create_source

        settings = SourceSettings(kind=SourceKind.SCREEN)
        settings.screen.use_region = True
        settings.screen.region = RectSpec(4, 5, 60, 70)
        source = create_source(settings)
        assert source._region == RectSpec(4, 5, 60, 70)

    def test_region_ignored_when_disabled(self, qapp):
        from obs_overlay.sources.registry import create_source

        settings = SourceSettings(kind=SourceKind.SCREEN)
        settings.screen.use_region = False
        assert create_source(settings)._region is None

    def test_fallback_to_demo_when_unavailable(self, qapp):
        from obs_overlay.sources.registry import create_source, kind_available

        settings = SourceSettings(kind=SourceKind.NDI, fallback_to_demo=True)
        source = create_source(settings)
        if kind_available(SourceKind.NDI):
            assert type(source).__name__ == "NdiSource"
        else:
            assert type(source).__name__ == "DemoSource"

    def test_screen_and_image_are_always_available(self):
        from obs_overlay.sources.registry import kind_available, unavailable_reason

        for kind in (SourceKind.SCREEN, SourceKind.IMAGE, SourceKind.DEMO):
            assert kind_available(kind)
            assert unavailable_reason(kind) == ""

    def test_unavailable_reason_is_actionable(self):
        from obs_overlay.sources.registry import ndi_available, unavailable_reason

        if not ndi_available():
            assert "pip install" in unavailable_reason(SourceKind.NDI)

    def test_sender_list_per_kind(self, qapp):
        from obs_overlay.sources.registry import available_sender_names

        assert available_sender_names(SourceKind.SCREEN)  # at least one monitor
        assert available_sender_names(SourceKind.IMAGE) == []
        assert available_sender_names(SourceKind.DEMO) == []


# ---------------------------------------------------------------------------
# Screen capture
# ---------------------------------------------------------------------------


@pytest.mark.gui
class TestScreenSource:
    def test_captures_the_whole_monitor(self, qapp):
        from PyQt6.QtGui import QGuiApplication

        from obs_overlay.sources.screen_source import ScreenSource

        expected = QGuiApplication.primaryScreen().geometry()
        source = ScreenSource(monitor_index=0, target_fps=30)
        assert source.open()
        try:
            frame = _wait_for_frame(qapp, source)
            assert frame is not None
            assert (frame.width, frame.height) == (expected.width(), expected.height())
            frame.release()
        finally:
            source.close()

    def test_captures_a_region(self, qapp):
        from obs_overlay.sources.screen_source import ScreenSource

        source = ScreenSource(monitor_index=0, region=RectSpec(5, 6, 64, 48), target_fps=30)
        assert source.open()
        try:
            frame = _wait_for_frame(qapp, source)
            assert frame is not None
            assert (frame.width, frame.height) == (64, 48)
            frame.release()
        finally:
            source.close()

    def test_frames_are_opaque(self, qapp):
        # A desktop grab has no alpha; handing Qt an undefined fourth byte
        # would make the overlay flicker or vanish.
        from obs_overlay.sources.screen_source import ScreenSource

        source = ScreenSource(monitor_index=0, region=RectSpec(0, 0, 32, 32), target_fps=30)
        assert source.open()
        try:
            frame = _wait_for_frame(qapp, source)
            assert frame is not None
            assert _alpha_of(frame).min() == 255
            assert frame.premultiplied is False
            frame.release()
        finally:
            source.close()

    def test_missing_monitor_reports_why(self, qapp):
        from obs_overlay.sources.screen_source import ScreenSource

        source = ScreenSource(monitor_index=99)
        assert source.open() is False
        assert source.state is SourceState.ERROR
        assert "not connected" in source.last_error

    def test_empty_region_is_refused(self, qapp):
        from obs_overlay.sources.screen_source import ScreenSource

        source = ScreenSource(monitor_index=0, region=RectSpec(0, 0, 0, 0))
        with pytest.raises(SourceError):
            source.open()

    def test_captured_rect_is_virtual_desktop_relative(self, qapp):
        from PyQt6.QtGui import QGuiApplication

        from obs_overlay.sources.screen_source import ScreenSource

        geometry = QGuiApplication.primaryScreen().geometry()
        source = ScreenSource(monitor_index=0, region=RectSpec(10, 20, 30, 40))
        rect = source.captured_rect()
        assert rect.x == geometry.x() + 10
        assert rect.y == geometry.y() + 20
        assert (rect.width, rect.height) == (30, 40)

    def test_captured_rect_without_region(self, qapp):
        from PyQt6.QtGui import QGuiApplication

        from obs_overlay.sources.screen_source import ScreenSource

        geometry = QGuiApplication.primaryScreen().geometry()
        rect = ScreenSource(monitor_index=0).captured_rect()
        assert (rect.width, rect.height) == (geometry.width(), geometry.height())

    def test_close_is_idempotent(self, qapp):
        from obs_overlay.sources.screen_source import ScreenSource

        source = ScreenSource(monitor_index=0)
        source.open()
        source.close()
        source.close()
        assert source.state is SourceState.CLOSED

    def test_capture_before_open(self, qapp):
        from obs_overlay.sources.screen_source import ScreenSource

        assert ScreenSource(monitor_index=0).capture(_pool(64, 64)) is None

    def test_lists_monitors(self, qapp):
        from obs_overlay.sources.screen_source import ScreenSource, available_monitors

        assert ScreenSource.list_senders()
        monitors = available_monitors()
        assert monitors and monitors[0][2].width > 0


def _wait_for_frame(qapp, source, timeout: float = 5.0):
    """Pump the event loop until the GUI-thread grabber has produced a frame."""
    pool = _pool(4096, 4096, count=2)
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        qapp.processEvents()
        frame = source.capture(pool)
        if frame is not None:
            return frame
        time.sleep(0.01)
    return None


# ---------------------------------------------------------------------------
# Image source
# ---------------------------------------------------------------------------


@pytest.mark.gui
class TestImageSource:
    def test_loads_a_png_and_keeps_its_alpha(self, qapp, png_with_alpha):
        from obs_overlay.sources.image_source import ImageSource

        source = ImageSource(path=str(png_with_alpha))
        assert source.open()
        try:
            frame = source.capture(_pool(120, 80))
            assert frame is not None
            assert (frame.width, frame.height) == (120, 80)
            alpha = _alpha_of(frame)
            assert alpha.min() == 0, "transparent corners were lost"
            assert alpha.max() == 255, "opaque centre was lost"
            assert frame.premultiplied is False
            frame.release()
        finally:
            source.close()

    def test_publishes_a_still_exactly_once(self, qapp, png_with_alpha):
        # The overlay holds the last frame, so a still must not be re-sent at
        # the poll rate; that would burn a full copy per tick for nothing.
        from obs_overlay.sources.image_source import ImageSource

        source = ImageSource(path=str(png_with_alpha))
        source.open()
        try:
            pool = _pool(120, 80)
            first = source.capture(pool)
            assert first is not None
            first.release()
            assert source.capture(pool) is None
            assert source.capture(pool) is None
        finally:
            source.close()

    def test_still_is_retried_when_the_pool_was_full(self, qapp, png_with_alpha):
        from obs_overlay.sources.image_source import ImageSource

        source = ImageSource(path=str(png_with_alpha))
        source.open()
        try:
            pool = _pool(120, 80, count=1)
            held = pool.acquire()  # starve the pool
            assert source.capture(pool) is None
            held.release()
            # The frame must still arrive, or the overlay stays blank for ever.
            recovered = source.capture(pool)
            assert recovered is not None
            recovered.release()
        finally:
            source.close()

    def test_missing_file_reports_why(self, qapp, tmp_path):
        from obs_overlay.sources.image_source import ImageSource

        source = ImageSource(path=str(tmp_path / "nope.png"))
        assert source.open() is False
        assert source.state is SourceState.ERROR
        assert "not found" in source.last_error.lower()

    def test_empty_path_raises(self, qapp):
        from obs_overlay.sources.image_source import ImageSource

        with pytest.raises(SourceError):
            ImageSource(path="").open()

    def test_unreadable_file_reports_why(self, qapp, tmp_path):
        from obs_overlay.sources.image_source import ImageSource

        junk = tmp_path / "broken.png"
        junk.write_bytes(b"this is not a png")
        source = ImageSource(path=str(junk))
        assert source.open() is False
        assert source.state is SourceState.ERROR

    def test_display_name_is_the_file_name(self, qapp, png_with_alpha):
        from obs_overlay.sources.image_source import ImageSource

        assert ImageSource(path=str(png_with_alpha)).display_name == "alpha.png"
        assert ImageSource(path="").display_name == "(no image)"

    def test_still_is_not_reported_as_animated(self, qapp, png_with_alpha):
        from obs_overlay.sources.image_source import ImageSource

        source = ImageSource(path=str(png_with_alpha))
        source.open()
        assert source.is_animated is False
        source.close()

    def test_close_is_idempotent(self, qapp, png_with_alpha):
        from obs_overlay.sources.image_source import ImageSource

        source = ImageSource(path=str(png_with_alpha))
        source.open()
        source.close()
        source.close()
        assert source.state is SourceState.CLOSED

    def test_filter_string_covers_png(self, qapp):
        from obs_overlay.sources.image_source import supported_image_filter

        assert "*.png" in supported_image_filter()


# ---------------------------------------------------------------------------
# NDI — only the guard rails; the real path needs the runtime and a sender.
# ---------------------------------------------------------------------------


class TestNdiSource:
    def test_import_failure_is_explained(self, monkeypatch):
        from obs_overlay.sources import ndi_source

        monkeypatch.setattr(
            ndi_source,
            "_import_ndi",
            lambda: (_ for _ in ()).throw(SourceError(ndi_source._INSTALL_HINT)),
        )
        with pytest.raises(SourceError) as excinfo:
            ndi_source.NdiSource().open()
        assert "ndi-python" in str(excinfo.value)

    def test_discovery_degrades_to_empty(self, monkeypatch):
        from obs_overlay.sources import ndi_source

        monkeypatch.setattr(
            ndi_source,
            "_import_ndi",
            lambda: (_ for _ in ()).throw(SourceError("nope")),
        )
        assert ndi_source.list_ndi_sources() == []

    def test_capture_without_open_returns_none(self):
        from obs_overlay.sources.ndi_source import NdiSource

        assert NdiSource().capture(_pool(16, 16)) is None

    def test_display_name_falls_back(self):
        from obs_overlay.sources.ndi_source import NdiSource

        assert NdiSource().display_name == "(any NDI source)"
        assert NdiSource(source_name="STUDIO (OBS)").display_name == "STUDIO (OBS)"

    def test_settings_reach_the_source(self):
        from obs_overlay.sources.registry import create_source

        settings = SourceSettings(kind=SourceKind.NDI)
        settings.ndi.source_name = "PC (OBS)"
        settings.ndi.low_bandwidth = True
        settings.ndi.premultiplied_alpha = True
        source = create_source(settings)
        assert source._requested_name == "PC (OBS)"
        assert source._low_bandwidth is True
        assert source._premultiplied is True


# ---------------------------------------------------------------------------
# Producer reopen policy
# ---------------------------------------------------------------------------


class TestReopenPolicy:
    def test_kind_change_reopens(self):
        from obs_overlay.core.producer import FrameProducer

        assert FrameProducer._needs_reopen(
            SourceSettings(kind=SourceKind.SPOUT), SourceSettings(kind=SourceKind.DEMO)
        )

    def test_inactive_group_change_does_not_reopen(self):
        # Editing the NDI name while running on Spout must not cut the feed.
        from obs_overlay.core.producer import FrameProducer

        old = SourceSettings(kind=SourceKind.SPOUT)
        new = SourceSettings(kind=SourceKind.SPOUT)
        new.ndi.source_name = "something else"
        assert FrameProducer._needs_reopen(old, new) is False

    def test_active_group_change_reopens(self):
        from obs_overlay.core.producer import FrameProducer

        old = SourceSettings(kind=SourceKind.SPOUT)
        new = SourceSettings(kind=SourceKind.SPOUT)
        new.spout.sender_name = "Other"
        assert FrameProducer._needs_reopen(old, new)

    def test_fps_change_does_not_reopen_a_pull_source(self):
        from obs_overlay.core.producer import FrameProducer

        old = SourceSettings(kind=SourceKind.SPOUT, target_fps=60)
        new = SourceSettings(kind=SourceKind.SPOUT, target_fps=30)
        assert FrameProducer._needs_reopen(old, new) is False

    def test_fps_change_reopens_screen_capture(self):
        # The grabber's timer interval is fixed when it starts.
        from obs_overlay.core.producer import FrameProducer

        old = SourceSettings(kind=SourceKind.SCREEN, target_fps=60)
        new = SourceSettings(kind=SourceKind.SCREEN, target_fps=30)
        assert FrameProducer._needs_reopen(old, new)

    def test_image_path_change_reopens(self):
        from obs_overlay.core.producer import FrameProducer

        old = SourceSettings(kind=SourceKind.IMAGE)
        new = SourceSettings(kind=SourceKind.IMAGE)
        new.image.path = "/tmp/other.png"
        assert FrameProducer._needs_reopen(old, new)


# ---------------------------------------------------------------------------
# Back-pressure
# ---------------------------------------------------------------------------


@pytest.mark.gui
class TestNotificationCoalescing:
    """One pending notification at a time.

    Emitting per frame posts an unbounded number of events at the frame rate.
    A GUI thread that cannot keep up then never drains the queue, and timers —
    including the debounced profile save — stop firing.
    """

    @staticmethod
    def _frame(pool):
        from obs_overlay.core.frame import Frame, PixelFormat

        buffer = pool.acquire()
        assert buffer is not None
        return Frame(4, 4, PixelFormat.RGBA8888, buffer)

    def test_repeated_publishes_emit_once(self, qapp):
        from obs_overlay.core.producer import FrameProducer

        producer = FrameProducer(SourceSettings(kind=SourceKind.DEMO))
        emitted = []
        producer.frameAvailable.connect(lambda: emitted.append(1))

        pool = _pool(4, 4, count=4)
        for _ in range(4):
            producer._publish(self._frame(pool))

        assert len(emitted) == 1, "each publish posted its own event"

    def test_taking_a_frame_re_arms_the_notification(self, qapp):
        from obs_overlay.core.producer import FrameProducer

        producer = FrameProducer(SourceSettings(kind=SourceKind.DEMO))
        emitted = []
        producer.frameAvailable.connect(lambda: emitted.append(1))

        pool = _pool(4, 4, count=4)
        producer._publish(self._frame(pool))
        assert len(emitted) == 1

        taken = producer.take_frame()
        assert taken is not None
        taken.release()

        producer._publish(self._frame(pool))
        assert len(emitted) == 2

    def test_superseded_frames_are_released_and_counted(self, qapp):
        from obs_overlay.core.producer import FrameProducer

        producer = FrameProducer(SourceSettings(kind=SourceKind.DEMO))
        pool = _pool(4, 4, count=4)

        producer._publish(self._frame(pool))
        producer._publish(self._frame(pool))
        # The first frame must go back to the pool, not leak.
        assert producer.stats_snapshot().frames_dropped == 1

        latest = producer.take_frame()
        assert latest is not None
        latest.release()
        assert producer.take_frame() is None

    def test_discarding_re_arms_too(self, qapp):
        from obs_overlay.core.producer import FrameProducer

        producer = FrameProducer(SourceSettings(kind=SourceKind.DEMO))
        emitted = []
        producer.frameAvailable.connect(lambda: emitted.append(1))
        pool = _pool(4, 4, count=4)

        producer._publish(self._frame(pool))
        producer._discard_pending_frame()
        producer._publish(self._frame(pool))
        assert len(emitted) == 2
