"""Widget-level behaviour, driven headlessly through the offscreen platform.

These cover the wiring that unit tests cannot: that the overlay actually masks
itself, that edit mode releases the mask, that dragging moves parcels, and that
the whole application starts, receives frames and shuts down cleanly.
"""

from __future__ import annotations

import time

import pytest

from obs_overlay.config.models import (
    Parcel,
    RectSpec,
    SourceKind,
)

pytestmark = pytest.mark.gui


@pytest.fixture()
def overlay(qapp, profile):
    from obs_overlay.native import create_window_controller
    from obs_overlay.ui.overlay_window import OverlayWindow

    window = OverlayWindow(profile, create_window_controller())
    window.resize(1280, 720)
    window.show()
    qapp.processEvents()
    yield window
    window.clear_frame()
    window.close()


def _press(window, x, y, buttons=None, modifiers=None):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    return QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(x, y),
        QPointF(x, y),
        Qt.MouseButton.LeftButton,
        buttons or Qt.MouseButton.LeftButton,
        modifiers or Qt.KeyboardModifier.NoModifier,
    )


def _move(window, x, y, modifiers=None):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    return QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(x, y),
        QPointF(x, y),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        modifiers or Qt.KeyboardModifier.NoModifier,
    )


def _release(window, x, y):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    return QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(x, y),
        QPointF(x, y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )


class TestOverlayWindow:
    def test_translucency_attributes_are_set(self, overlay):
        from PyQt6.QtCore import Qt

        assert overlay.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        assert overlay.windowFlags() & Qt.WindowType.FramelessWindowHint
        assert overlay.windowFlags() & Qt.WindowType.WindowStaysOnTopHint

    def test_mask_follows_the_parcels(self, overlay):
        assert not overlay.mask().isEmpty()
        assert overlay.mask().rectCount() == len(overlay.profile.parcels)

    def test_mask_is_released_in_edit_mode(self, overlay, qapp):
        overlay.set_edit_mode(True)
        qapp.processEvents()
        assert overlay.mask().isEmpty()
        overlay.set_edit_mode(False)
        qapp.processEvents()
        assert not overlay.mask().isEmpty()

    def test_mask_disabled_by_profile(self, overlay, qapp):
        overlay.profile.behavior.mask_enabled = False
        overlay.refresh_mask()
        qapp.processEvents()
        assert overlay.mask().isEmpty()

    def test_mask_is_cached_between_identical_refreshes(self, overlay):
        overlay.refresh_mask()
        first = overlay._cached_region
        overlay.refresh_mask()
        assert overlay._cached_region is first

    def test_changing_a_parcel_invalidates_the_mask(self, overlay):
        overlay.refresh_mask()
        first = overlay._cached_region
        overlay.profile.parcels[0].x += 40
        overlay.invalidate_mask()
        assert overlay._cached_region is not first

    def test_paints_without_error(self, overlay):
        from PyQt6.QtGui import QImage

        image = QImage(1280, 720, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        overlay.render(image)  # would raise if paintEvent threw

    def test_frame_is_adopted_and_released(self, overlay, qapp):
        from obs_overlay.core.frame import FrameBufferPool, required_buffer_size
        from obs_overlay.sources.demo_source import DemoSource

        source = DemoSource(320, 180)
        source.open()
        pool = FrameBufferPool(required_buffer_size(320, 180), 2)

        first = source.capture(pool)
        overlay.set_frame(first)
        assert pool.free_count == 1

        second = source.capture(pool)
        overlay.set_frame(second)  # must release the first
        qapp.processEvents()
        assert pool.free_count == 1

        overlay.clear_frame()
        assert pool.free_count == 2

    def test_premultiplied_flag_picks_the_image_format(self, overlay):
        from PyQt6.QtGui import QImage

        from obs_overlay.core.frame import (
            Frame,
            FrameBufferPool,
            PixelFormat,
            required_buffer_size,
        )

        pool = FrameBufferPool(required_buffer_size(8, 8), 2)
        straight = Frame(8, 8, PixelFormat.RGBA8888, pool.acquire(), premultiplied=False)
        overlay.set_frame(straight)
        assert overlay._image.format() == QImage.Format.Format_RGBA8888

        premultiplied = Frame(8, 8, PixelFormat.RGBA8888, pool.acquire(), premultiplied=True)
        overlay.set_frame(premultiplied)
        assert overlay._image.format() == QImage.Format.Format_RGBA8888_Premultiplied
        overlay.clear_frame()

    def test_video_rect_respects_fit_mode(self, overlay):
        from obs_overlay.config.models import FitMode
        from obs_overlay.core.frame import (
            Frame,
            FrameBufferPool,
            PixelFormat,
            required_buffer_size,
        )

        pool = FrameBufferPool(required_buffer_size(640, 360), 1)
        overlay.set_frame(Frame(640, 360, PixelFormat.RGBA8888, pool.acquire()))

        overlay.profile.display.fit_mode = FitMode.NONE
        assert overlay.video_rect().width == 640

        overlay.profile.display.fit_mode = FitMode.CONTAIN
        assert overlay.video_rect().width == 1280
        overlay.clear_frame()

    def test_geometry_falls_back_for_a_missing_monitor(self, overlay):
        from obs_overlay.config.models import GeometryMode

        overlay.profile.display.geometry_mode = GeometryMode.MONITOR
        overlay.profile.display.monitor_index = 99
        rect = overlay.target_geometry()
        assert rect.width() > 0 and rect.height() > 0


class TestEditorInteraction:
    def test_click_selects_a_parcel(self, overlay, qapp):
        overlay.set_edit_mode(True)
        parcel = overlay.profile.parcels[0]
        overlay.editor.mouse_press(_press(overlay, parcel.center[0], parcel.center[1]))
        assert overlay.editor.selection == [parcel.id]

    def test_click_on_empty_space_clears_the_selection(self, overlay):
        overlay.set_edit_mode(True)
        overlay.editor.set_selection([overlay.profile.parcels[0].id])
        overlay.editor.mouse_press(_press(overlay, 1200, 700))
        assert overlay.editor.selection == []

    def test_drag_moves_the_parcel(self, overlay):
        overlay.set_edit_mode(True)
        overlay.profile.editor.snap_to_grid = False
        overlay.profile.editor.snap_to_parcels = False
        overlay.profile.editor.snap_to_canvas = False

        parcel = overlay.profile.parcels[0]
        start_x, start_y = parcel.center
        origin_x = parcel.x

        overlay.editor.mouse_press(_press(overlay, start_x, start_y))
        overlay.editor.mouse_move(_move(overlay, start_x + 60, start_y))
        overlay.editor.mouse_release(_release(overlay, start_x + 60, start_y))

        assert overlay.profile.parcels[0].x == origin_x + 60

    def test_drag_a_handle_resizes(self, overlay):
        overlay.set_edit_mode(True)
        overlay.profile.editor.snap_to_grid = False
        overlay.profile.editor.snap_to_parcels = False
        overlay.profile.editor.snap_to_canvas = False

        parcel = overlay.profile.parcels[0]
        overlay.editor.set_selection([parcel.id])
        corner_x, corner_y = parcel.right, parcel.bottom
        width = parcel.width

        overlay.editor.mouse_press(_press(overlay, corner_x, corner_y))
        overlay.editor.mouse_move(_move(overlay, corner_x + 50, corner_y + 50))
        overlay.editor.mouse_release(_release(overlay, corner_x + 50, corner_y + 50))

        assert overlay.profile.parcels[0].width == width + 50

    def test_undo_restores_the_previous_layout(self, overlay):
        overlay.set_edit_mode(True)
        original = overlay.profile.parcels[0].x
        overlay.editor.set_selection([overlay.profile.parcels[0].id])
        overlay.editor.nudge_selection(37, 0)
        assert overlay.profile.parcels[0].x == original + 37
        assert overlay.editor.undo()
        assert overlay.profile.parcels[0].x == original
        assert overlay.editor.redo()
        assert overlay.profile.parcels[0].x == original + 37

    def test_undo_on_empty_stack(self, overlay):
        overlay.set_edit_mode(True)
        assert overlay.editor.undo() is False
        assert overlay.editor.redo() is False

    def test_a_click_that_moves_nothing_costs_no_undo(self, overlay):
        overlay.set_edit_mode(True)
        parcel = overlay.profile.parcels[0]
        overlay.editor.mouse_press(_press(overlay, parcel.center[0], parcel.center[1]))
        overlay.editor.mouse_release(_release(overlay, parcel.center[0], parcel.center[1]))
        assert overlay.editor.can_undo is False

    def test_duplicate_and_delete(self, overlay):
        overlay.set_edit_mode(True)
        count = len(overlay.profile.parcels)
        overlay.editor.select_all()
        overlay.editor.duplicate_selection()
        assert len(overlay.profile.parcels) == count * 2
        overlay.editor.delete_selection()
        assert len(overlay.profile.parcels) == count

    def test_locked_parcels_survive_delete(self, overlay):
        overlay.set_edit_mode(True)
        overlay.profile.parcels[0].locked = True
        overlay.editor.set_selection([p.id for p in overlay.profile.parcels])
        overlay.editor.delete_selection()
        assert len(overlay.profile.parcels) == 1
        assert overlay.profile.parcels[0].locked

    def test_add_parcel_selects_it(self, overlay):
        overlay.set_edit_mode(True)
        parcel = overlay.editor.add_parcel()
        assert overlay.editor.selection == [parcel.id]

    def test_reorder(self, overlay):
        overlay.set_edit_mode(True)
        first, second = overlay.profile.parcels[0], overlay.profile.parcels[1]
        overlay.editor.set_selection([first.id])
        overlay.editor.raise_selection(to_top=True)
        assert overlay.profile.parcels[-1].id == first.id
        overlay.editor.lower_selection(to_bottom=True)
        assert overlay.profile.parcels[0].id == first.id
        assert second.id in [p.id for p in overlay.profile.parcels]

    def test_align(self, overlay):
        from obs_overlay.core.geometry import AlignMode

        overlay.set_edit_mode(True)
        overlay.editor.select_all()
        overlay.editor.align_selection(AlignMode.LEFT)
        xs = {p.x for p in overlay.profile.parcels}
        assert len(xs) == 1

    def test_ctrl_drag_creates_a_parcel(self, overlay):
        from PyQt6.QtCore import Qt

        overlay.set_edit_mode(True)
        count = len(overlay.profile.parcels)
        overlay.editor.mouse_press(
            _press(overlay, 900, 500, modifiers=Qt.KeyboardModifier.ControlModifier)
        )
        overlay.editor.mouse_move(_move(overlay, 1100, 650))
        overlay.editor.mouse_release(_release(overlay, 1100, 650))
        assert len(overlay.profile.parcels) == count + 1

    def test_tiny_ctrl_drag_creates_nothing(self, overlay):
        from PyQt6.QtCore import Qt

        overlay.set_edit_mode(True)
        count = len(overlay.profile.parcels)
        overlay.editor.mouse_press(
            _press(overlay, 900, 500, modifiers=Qt.KeyboardModifier.ControlModifier)
        )
        overlay.editor.mouse_move(_move(overlay, 902, 501))
        overlay.editor.mouse_release(_release(overlay, 902, 501))
        assert len(overlay.profile.parcels) == count
        assert overlay.editor.can_undo is False

    def test_layout_changed_is_emitted(self, overlay):
        fired = []
        overlay.layoutChanged.connect(lambda: fired.append(1))
        overlay.set_edit_mode(True)
        overlay.editor.select_all()
        overlay.editor.nudge_selection(5, 5)
        assert fired


class TestParcelTable:
    def test_reflects_the_profile(self, qapp, profile):
        from obs_overlay.ui.parcel_table import ParcelTable

        table = ParcelTable(lambda: profile.parcels)
        table.refresh()
        assert table.rowCount() == len(profile.parcels)

    def test_apply_edit_clamps(self, profile):
        from obs_overlay.constants import MIN_PARCEL_SIZE
        from obs_overlay.ui.parcel_table import apply_edit

        edited = apply_edit(profile.parcels[0], {"width": 1, "corner_radius": -5})
        assert edited.width == MIN_PARCEL_SIZE
        assert edited.corner_radius == 0

    def test_apply_edit_ignores_unknown_fields(self, profile):
        from obs_overlay.ui.parcel_table import apply_edit

        assert apply_edit(profile.parcels[0], {"nonsense": 1}) == profile.parcels[0]


class TestApplicationLifecycle:
    def test_starts_receives_frames_and_stops(self, qapp, data_dir):

        from obs_overlay.app import OverlayApplication
        from obs_overlay.config.store import ConfigStore

        store = ConfigStore()
        controller = OverlayApplication(qapp, store=store)
        controller._profile.source.kind = SourceKind.DEMO
        controller._profile.display.custom_rect = RectSpec(0, 0, 640, 360)
        controller.producer.apply_settings(controller._profile.source)
        controller.start()

        deadline = time.perf_counter() + 6.0
        while time.perf_counter() < deadline:
            qapp.processEvents()
            if controller.producer.stats_snapshot().frames_received > 3:
                break
            time.sleep(0.02)

        stats = controller.producer.stats_snapshot()
        assert stats.frames_received > 0, "no frames arrived from the demo source"

        controller._teardown()
        assert not controller.producer.isRunning()

    def test_profile_is_persisted_on_teardown(self, qapp, data_dir):
        from obs_overlay.app import OverlayApplication
        from obs_overlay.config.store import ConfigStore

        store = ConfigStore()
        controller = OverlayApplication(qapp, store=store)
        controller._profile.source.kind = SourceKind.DEMO
        controller._profile.parcels[0].name = "Persisted"
        controller._teardown()

        assert store.load_profile(controller._profile.name).parcels[0].name == "Persisted"

    def test_safety_guard_restores_click_through(self, qapp, data_dir):
        from obs_overlay.app import OverlayApplication
        from obs_overlay.config.store import ConfigStore

        store = ConfigStore()
        controller = OverlayApplication(qapp, store=store)
        controller.overlay.resize(800, 600)
        controller._profile.behavior.click_through = False
        controller._profile.display.opacity = 1.0
        controller._profile.parcels = [Parcel(x=0, y=0, width=800, height=600)]

        controller._warn_if_unsafe()
        assert controller._profile.behavior.click_through is True
        controller._teardown()

    def test_safety_guard_leaves_a_modest_layout_alone(self, qapp, data_dir):
        from obs_overlay.app import OverlayApplication
        from obs_overlay.config.store import ConfigStore

        store = ConfigStore()
        controller = OverlayApplication(qapp, store=store)
        controller.overlay.resize(800, 600)
        controller._profile.behavior.click_through = False
        controller._profile.parcels = [Parcel(x=0, y=0, width=100, height=100)]

        controller._warn_if_unsafe()
        assert controller._profile.behavior.click_through is False
        controller._teardown()

    def test_panic_restores_a_usable_state(self, qapp, data_dir):
        from obs_overlay.app import OverlayApplication
        from obs_overlay.config.store import ConfigStore

        store = ConfigStore()
        controller = OverlayApplication(qapp, store=store)
        controller._profile.behavior.click_through = False
        controller.overlay.set_edit_mode(True)

        controller.panic()
        assert controller._profile.behavior.click_through is True
        assert controller.overlay.edit_mode is False
        assert controller.panel.isVisible()
        controller._teardown()


def _key(key, modifiers=None):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeyEvent

    return QKeyEvent(
        QKeyEvent.Type.KeyPress,
        int(key),
        modifiers or Qt.KeyboardModifier.NoModifier,
    )


class TestEditorKeyboard:
    """The key_press path, which the mouse-driven tests never reach.

    Qt.Key is an IntEnum and QKeyEvent.key() returns a plain int, so the
    dispatch table is keyed by int; these tests pin that down.
    """

    def test_arrow_keys_nudge_by_one_pixel(self, overlay):
        from PyQt6.QtCore import Qt

        overlay.set_edit_mode(True)
        parcel = overlay.profile.parcels[0]
        overlay.editor.set_selection([parcel.id])
        start_x, start_y = parcel.x, parcel.y

        assert overlay.editor.key_press(_key(Qt.Key.Key_Right))
        assert overlay.profile.parcels[0].x == start_x + 1
        assert overlay.editor.key_press(_key(Qt.Key.Key_Down))
        assert overlay.profile.parcels[0].y == start_y + 1
        assert overlay.editor.key_press(_key(Qt.Key.Key_Left))
        assert overlay.profile.parcels[0].x == start_x
        assert overlay.editor.key_press(_key(Qt.Key.Key_Up))
        assert overlay.profile.parcels[0].y == start_y

    def test_shift_arrow_nudges_by_the_grid_size(self, overlay):
        from PyQt6.QtCore import Qt

        overlay.set_edit_mode(True)
        overlay.profile.editor.grid_size = 25
        parcel = overlay.profile.parcels[0]
        overlay.editor.set_selection([parcel.id])
        start_x = parcel.x

        overlay.editor.key_press(_key(Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier))
        assert overlay.profile.parcels[0].x == start_x + 25

    def test_ctrl_d_duplicates(self, overlay):
        from PyQt6.QtCore import Qt

        overlay.set_edit_mode(True)
        overlay.editor.set_selection([overlay.profile.parcels[0].id])
        count = len(overlay.profile.parcels)
        assert overlay.editor.key_press(_key(Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier))
        assert len(overlay.profile.parcels) == count + 1

    def test_delete_removes(self, overlay):
        from PyQt6.QtCore import Qt

        overlay.set_edit_mode(True)
        overlay.editor.set_selection([overlay.profile.parcels[0].id])
        count = len(overlay.profile.parcels)
        assert overlay.editor.key_press(_key(Qt.Key.Key_Delete))
        assert len(overlay.profile.parcels) == count - 1

    def test_ctrl_a_selects_all(self, overlay):
        from PyQt6.QtCore import Qt

        overlay.set_edit_mode(True)
        overlay.editor.clear_selection()
        assert overlay.editor.key_press(_key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier))
        assert len(overlay.editor.selection) == len(overlay.profile.parcels)

    def test_ctrl_z_and_redo(self, overlay):
        from PyQt6.QtCore import Qt

        overlay.set_edit_mode(True)
        parcel = overlay.profile.parcels[0]
        overlay.editor.set_selection([parcel.id])
        start_x = parcel.x

        overlay.editor.key_press(_key(Qt.Key.Key_Right))
        assert overlay.profile.parcels[0].x == start_x + 1

        overlay.editor.key_press(_key(Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier))
        assert overlay.profile.parcels[0].x == start_x

        overlay.editor.key_press(
            _key(
                Qt.Key.Key_Z,
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
            )
        )
        assert overlay.profile.parcels[0].x == start_x + 1

    def test_escape_clears_selection_then_requests_exit(self, overlay):
        from PyQt6.QtCore import Qt

        overlay.set_edit_mode(True)
        overlay.editor.select_all()
        exits = []
        overlay.editor.exitRequested.connect(lambda: exits.append(1))

        overlay.editor.key_press(_key(Qt.Key.Key_Escape))
        assert overlay.editor.selection == []
        assert not exits

        overlay.editor.key_press(_key(Qt.Key.Key_Escape))
        assert exits

    def test_unhandled_key_is_reported_as_unhandled(self, overlay):
        from PyQt6.QtCore import Qt

        overlay.set_edit_mode(True)
        assert overlay.editor.key_press(_key(Qt.Key.Key_F7)) is False

    def test_ctrl_bracket_reorders(self, overlay):
        from PyQt6.QtCore import Qt

        overlay.set_edit_mode(True)
        first = overlay.profile.parcels[0]
        overlay.editor.set_selection([first.id])
        assert overlay.editor.key_press(
            _key(Qt.Key.Key_BracketRight, Qt.KeyboardModifier.ControlModifier)
        )
        assert overlay.profile.parcels[-1].id == first.id
