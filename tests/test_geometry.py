"""The editor's arithmetic: hit-testing, resizing, snapping, layout, coverage."""

from __future__ import annotations

import pytest

from obs_overlay.config.models import Anchor, BooleanOp, FitMode, Parcel, RectSpec
from obs_overlay.constants import MIN_PARCEL_SIZE
from obs_overlay.core import geometry as geo
from obs_overlay.core.geometry import AlignMode, Handle


class TestRectHelpers:
    def test_normalise_negative_extent(self):
        assert geo.normalise(RectSpec(10, 10, -4, -6)) == RectSpec(6, 4, 4, 6)

    def test_edges(self):
        rect = RectSpec(10, 20, 100, 50)
        assert geo.right(rect) == 110
        assert geo.bottom(rect) == 70
        assert geo.center_x(rect) == 60
        assert geo.center_y(rect) == 45

    def test_contains_point_is_half_open(self):
        rect = RectSpec(0, 0, 10, 10)
        assert geo.contains_point(rect, 0, 0)
        assert geo.contains_point(rect, 9, 9)
        assert not geo.contains_point(rect, 10, 5)
        assert not geo.contains_point(rect, 5, 10)

    def test_intersects_and_intersection(self):
        a = RectSpec(0, 0, 10, 10)
        b = RectSpec(5, 5, 10, 10)
        c = RectSpec(20, 20, 5, 5)
        assert geo.intersects(a, b)
        assert not geo.intersects(a, c)
        assert geo.intersection(a, b) == RectSpec(5, 5, 5, 5)
        assert geo.intersection(a, c).width == 0

    def test_touching_rects_do_not_intersect(self):
        assert not geo.intersects(RectSpec(0, 0, 10, 10), RectSpec(10, 0, 10, 10))

    def test_bounding_rect(self):
        rects = [RectSpec(10, 10, 10, 10), RectSpec(50, 5, 20, 40)]
        assert geo.bounding_rect(rects) == RectSpec(10, 5, 60, 40)
        assert geo.bounding_rect([]) == RectSpec(0, 0, 0, 0)

    def test_clamp_rect_keeps_a_margin_visible(self):
        bounds = RectSpec(0, 0, 1000, 800)
        clamped = geo.clamp_rect(RectSpec(-5000, -5000, 100, 100), bounds)
        assert geo.right(clamped) > bounds.x
        assert geo.bottom(clamped) > bounds.y

    def test_clamp_rect_strict_pushes_fully_inside(self):
        bounds = RectSpec(0, 0, 200, 200)
        clamped = geo.clamp_rect(RectSpec(500, 500, 50, 50), bounds, allow_partial=False)
        assert clamped == RectSpec(150, 150, 50, 50)


class TestHandles:
    @pytest.mark.parametrize(
        ("handle", "expected"),
        [
            (Handle.TOP_LEFT, (100, 100)),
            (Handle.TOP, (200, 100)),
            (Handle.TOP_RIGHT, (300, 100)),
            (Handle.RIGHT, (300, 200)),
            (Handle.BOTTOM_RIGHT, (300, 300)),
            (Handle.BOTTOM, (200, 300)),
            (Handle.BOTTOM_LEFT, (100, 300)),
            (Handle.LEFT, (100, 200)),
        ],
    )
    def test_handle_centres(self, handle, expected):
        assert geo.handle_center(RectSpec(100, 100, 200, 200), handle) == expected

    def test_corner_beats_edge(self):
        rect = RectSpec(100, 100, 200, 200)
        assert geo.hit_test_handle(rect, 100, 100) is Handle.TOP_LEFT

    def test_body_hit(self):
        rect = RectSpec(100, 100, 200, 200)
        assert geo.hit_test_handle(rect, 200, 200) is Handle.BODY

    def test_miss(self):
        rect = RectSpec(100, 100, 200, 200)
        assert geo.hit_test_handle(rect, 500, 500) is Handle.NONE

    def test_edge_membership_flags(self):
        assert Handle.TOP_LEFT.moves_left and Handle.TOP_LEFT.moves_top
        assert Handle.BOTTOM_RIGHT.moves_right and Handle.BOTTOM_RIGHT.moves_bottom
        assert Handle.TOP.moves_top and not Handle.TOP.moves_left
        assert Handle.BODY.is_resize is False
        assert Handle.TOP_LEFT.is_corner

    def test_topmost_parcel_wins(self):
        parcels = [
            Parcel(id="under", x=0, y=0, width=200, height=200),
            Parcel(id="over", x=0, y=0, width=200, height=200),
        ]
        found, _ = geo.hit_test_parcels(parcels, 100, 100)
        assert found == "over"

    def test_locked_and_disabled_parcels_are_not_hit(self):
        parcels = [
            Parcel(id="a", x=0, y=0, width=200, height=200, locked=True),
            Parcel(id="b", x=0, y=0, width=200, height=200, enabled=False),
        ]
        found, handle = geo.hit_test_parcels(parcels, 100, 100)
        assert found is None and handle is Handle.NONE

    def test_selected_parcel_handles_stay_reachable(self):
        # A newer parcel overlapping a selected one must not steal its handle.
        parcels = [
            Parcel(id="selected", x=0, y=0, width=200, height=200),
            Parcel(id="newer", x=0, y=0, width=400, height=400),
        ]
        found, handle = geo.hit_test_parcels(parcels, 200, 200, selected_ids=["selected"])
        assert found == "selected"
        assert handle is Handle.BOTTOM_RIGHT


class TestResize:
    def test_bottom_right_grows(self):
        assert geo.resize_rect(RectSpec(0, 0, 100, 100), Handle.BOTTOM_RIGHT, 50, 20) == RectSpec(
            0, 0, 150, 120
        )

    def test_top_left_moves_origin(self):
        assert geo.resize_rect(RectSpec(0, 0, 100, 100), Handle.TOP_LEFT, 20, 30) == RectSpec(
            20, 30, 80, 70
        )

    def test_body_translates(self):
        assert geo.resize_rect(RectSpec(5, 5, 10, 10), Handle.BODY, 3, -2) == RectSpec(8, 3, 10, 10)

    def test_minimum_size_is_respected(self):
        result = geo.resize_rect(RectSpec(0, 0, 100, 100), Handle.BOTTOM_RIGHT, -500, -500)
        assert result.width == MIN_PARCEL_SIZE
        assert result.height == MIN_PARCEL_SIZE

    def test_dragging_past_the_opposite_edge_does_not_flip(self):
        result = geo.resize_rect(RectSpec(0, 0, 100, 100), Handle.LEFT, 500, 0)
        assert result.width == MIN_PARCEL_SIZE
        assert result.x == 100 - MIN_PARCEL_SIZE

    def test_aspect_lock_keeps_ratio(self):
        start = RectSpec(0, 0, 200, 100)  # 2:1
        result = geo.resize_rect(start, Handle.BOTTOM_RIGHT, 100, 5, keep_aspect=True)
        assert abs(result.width / result.height - 2.0) < 0.05

    def test_aspect_lock_on_edge_handle_drives_other_axis(self):
        start = RectSpec(0, 0, 200, 100)
        result = geo.resize_rect(start, Handle.RIGHT, 100, 0, keep_aspect=True)
        assert result.width == 300
        assert result.height == 150

    def test_from_centre_expands_both_sides(self):
        result = geo.resize_rect(
            RectSpec(100, 100, 100, 100), Handle.RIGHT, 20, 0, from_center=True
        )
        assert result.x == 80
        assert result.width == 140

    def test_non_resize_handle_is_a_noop(self):
        rect = RectSpec(1, 2, 3, 4)
        assert geo.resize_rect(rect, Handle.NONE, 10, 10) == rect


class TestSnapping:
    def test_snap_to_grid_value(self):
        assert geo.snap_to_grid(103, 10) == 100
        assert geo.snap_to_grid(106, 10) == 110
        assert geo.snap_to_grid(7, 1) == 7

    def test_snaps_to_neighbour_left_edge(self):
        moving = RectSpec(103, 300, 100, 100)
        other = RectSpec(100, 0, 50, 50)
        snapped, guides = geo.snap_moved_rect(
            moving,
            [other],
            None,
            grid=0,
            threshold=8,
            snap_grid=False,
            snap_parcels=True,
            snap_canvas=False,
        )
        assert snapped.x == 100
        assert guides

    def test_no_snap_outside_threshold(self):
        moving = RectSpec(140, 300, 100, 100)
        other = RectSpec(100, 0, 50, 50)
        snapped, guides = geo.snap_moved_rect(
            moving,
            [other],
            None,
            grid=0,
            threshold=8,
            snap_grid=False,
            snap_parcels=True,
            snap_canvas=False,
        )
        assert snapped == moving
        assert not guides

    def test_zero_threshold_disables_snapping(self):
        moving = RectSpec(101, 300, 100, 100)
        snapped, _ = geo.snap_moved_rect(
            moving,
            [RectSpec(100, 0, 50, 50)],
            None,
            grid=10,
            threshold=0,
            snap_grid=True,
            snap_parcels=True,
            snap_canvas=True,
        )
        assert snapped == moving

    def test_canvas_centre_snap(self):
        canvas = RectSpec(0, 0, 1000, 800)
        moving = RectSpec(448, 20, 100, 100)  # centre 498, canvas centre 500
        snapped, _ = geo.snap_moved_rect(
            moving,
            [],
            canvas,
            grid=0,
            threshold=8,
            snap_grid=False,
            snap_parcels=False,
            snap_canvas=True,
        )
        assert geo.center_x(snapped) == 500

    def test_object_snap_wins_over_grid(self):
        # 103 is 3 from the neighbour's edge and 3 from the grid line at 100,
        # but the neighbour must win so boxes line up with each other.
        moving = RectSpec(103, 300, 100, 100)
        other = RectSpec(104, 0, 50, 50)
        snapped, _ = geo.snap_moved_rect(
            moving,
            [other],
            None,
            grid=10,
            threshold=8,
            snap_grid=True,
            snap_parcels=True,
            snap_canvas=False,
        )
        assert snapped.x == 104

    def test_resize_snap_only_moves_the_dragged_edge(self):
        rect = RectSpec(0, 0, 103, 100)
        other = RectSpec(100, 0, 50, 300)
        snapped, _ = geo.snap_resized_rect(
            rect,
            Handle.RIGHT,
            [other],
            None,
            grid=0,
            threshold=8,
            snap_grid=False,
            snap_parcels=True,
            snap_canvas=False,
        )
        assert snapped.x == 0  # left edge untouched
        assert geo.right(snapped) == 100

    def test_resize_snap_never_shrinks_below_minimum(self):
        rect = RectSpec(0, 0, 12, 100)
        other = RectSpec(2, 0, 50, 300)
        snapped, _ = geo.snap_resized_rect(
            rect,
            Handle.RIGHT,
            [other],
            None,
            grid=0,
            threshold=40,
            snap_grid=False,
            snap_parcels=True,
            snap_canvas=False,
        )
        assert snapped.width >= MIN_PARCEL_SIZE


class TestAlignDistribute:
    def test_align_left(self):
        rects = [RectSpec(10, 0, 50, 50), RectSpec(30, 60, 50, 50)]
        assert [r.x for r in geo.align_rects(rects, AlignMode.LEFT)] == [10, 10]

    def test_align_right_uses_each_width(self):
        rects = [RectSpec(0, 0, 50, 50), RectSpec(0, 60, 100, 50)]
        aligned = geo.align_rects(rects, AlignMode.RIGHT)
        assert [geo.right(r) for r in aligned] == [100, 100]

    def test_align_vertical_centre(self):
        rects = [RectSpec(0, 0, 50, 50), RectSpec(0, 0, 50, 100)]
        aligned = geo.align_rects(rects, AlignMode.V_CENTER)
        assert geo.center_y(aligned[0]) == geo.center_y(aligned[1])

    def test_align_single_rect_is_noop(self):
        rects = [RectSpec(7, 7, 10, 10)]
        assert geo.align_rects(rects, AlignMode.LEFT) == rects

    def test_distribute_equalises_gaps(self):
        rects = [
            RectSpec(0, 0, 100, 10),
            RectSpec(120, 0, 50, 10),
            RectSpec(400, 0, 100, 10),
        ]
        spread = geo.distribute_rects(rects, horizontal=True)
        gap1 = spread[1].x - geo.right(spread[0])
        gap2 = spread[2].x - geo.right(spread[1])
        assert abs(gap1 - gap2) <= 1
        assert spread[0] == rects[0]
        assert spread[2] == rects[2]

    def test_distribute_preserves_input_order(self):
        rects = [RectSpec(400, 0, 50, 10), RectSpec(0, 0, 50, 10), RectSpec(200, 0, 50, 10)]
        spread = geo.distribute_rects(rects, horizontal=True)
        assert spread[0].x > spread[1].x  # the first input was the rightmost
        assert len(spread) == 3

    def test_distribute_needs_three(self):
        rects = [RectSpec(0, 0, 10, 10), RectSpec(50, 0, 10, 10)]
        assert geo.distribute_rects(rects, horizontal=True) == rects


class TestFitRect:
    def test_contain_letterboxes(self):
        result = geo.fit_rect(1920, 1080, RectSpec(0, 0, 1000, 1000), FitMode.CONTAIN)
        assert result.width == 1000
        assert result.height == 562
        assert result.y > 0  # centred vertically

    def test_cover_overflows(self):
        result = geo.fit_rect(1920, 1080, RectSpec(0, 0, 1000, 1000), FitMode.COVER)
        assert result.width >= 1000 and result.height >= 1000

    def test_none_is_one_to_one(self):
        result = geo.fit_rect(640, 480, RectSpec(0, 0, 1920, 1080), FitMode.NONE)
        assert (result.width, result.height) == (640, 480)

    def test_stretch_fills_exactly(self):
        result = geo.fit_rect(640, 480, RectSpec(0, 0, 1920, 1080), FitMode.STRETCH)
        assert (result.width, result.height) == (1920, 1080)

    def test_anchor_top_left(self):
        result = geo.fit_rect(
            640, 480, RectSpec(0, 0, 1920, 1080), FitMode.NONE, anchor=Anchor.TOP_LEFT
        )
        assert (result.x, result.y) == (0, 0)

    def test_anchor_bottom_right(self):
        result = geo.fit_rect(
            640, 480, RectSpec(0, 0, 1920, 1080), FitMode.NONE, anchor=Anchor.BOTTOM_RIGHT
        )
        assert geo.right(result) == 1920
        assert geo.bottom(result) == 1080

    def test_offset_and_zoom(self):
        result = geo.fit_rect(
            100,
            100,
            RectSpec(0, 0, 1000, 1000),
            FitMode.NONE,
            anchor=Anchor.TOP_LEFT,
            zoom=2.0,
            offset_x=10,
            offset_y=20,
        )
        assert (result.width, result.height) == (200, 200)
        assert (result.x, result.y) == (10, 20)

    def test_degenerate_inputs(self):
        assert geo.fit_rect(0, 0, RectSpec(0, 0, 100, 100)).width == 0
        assert geo.fit_rect(100, 100, RectSpec(0, 0, 0, 0)).width == 0

    def test_map_point_round_trip(self):
        dest = geo.fit_rect(200, 100, RectSpec(0, 0, 400, 200), FitMode.CONTAIN)
        assert geo.map_point_to_source((dest.x, dest.y), dest, 200, 100) == (0, 0)
        outside = geo.map_point_to_source((-50, -50), dest, 200, 100)
        assert outside is None


class TestCoverage:
    def test_single_parcel(self):
        parcels = [Parcel(x=0, y=0, width=100, height=100)]
        assert geo.covered_area(parcels, RectSpec(0, 0, 1000, 1000)) == 10_000

    def test_overlap_is_not_double_counted(self):
        parcels = [
            Parcel(x=0, y=0, width=100, height=100),
            Parcel(x=50, y=0, width=100, height=100),
        ]
        assert geo.covered_area(parcels, RectSpec(0, 0, 1000, 1000)) == 15_000

    def test_subtract_cuts_away(self):
        parcels = [
            Parcel(x=0, y=0, width=100, height=100),
            Parcel(x=50, y=0, width=100, height=100, op=BooleanOp.SUBTRACT),
        ]
        assert geo.covered_area(parcels, RectSpec(0, 0, 1000, 1000)) == 5_000

    def test_subtract_then_add_restores(self):
        parcels = [
            Parcel(x=0, y=0, width=100, height=100),
            Parcel(x=0, y=0, width=100, height=100, op=BooleanOp.SUBTRACT),
            Parcel(x=0, y=0, width=100, height=100),
        ]
        assert geo.covered_area(parcels, RectSpec(0, 0, 1000, 1000)) == 10_000

    def test_clipped_to_bounds(self):
        parcels = [Parcel(x=-500, y=-500, width=1000, height=1000)]
        assert geo.covered_area(parcels, RectSpec(0, 0, 100, 100)) == 10_000

    def test_disabled_parcels_ignored(self):
        parcels = [Parcel(x=0, y=0, width=100, height=100, enabled=False)]
        assert geo.covered_area(parcels, RectSpec(0, 0, 1000, 1000)) == 0

    def test_ratio(self):
        parcels = [Parcel(x=0, y=0, width=500, height=500)]
        assert geo.coverage_ratio(parcels, RectSpec(0, 0, 1000, 1000)) == pytest.approx(0.25)
        assert geo.coverage_ratio(parcels, RectSpec(0, 0, 0, 0)) == 0.0

    def test_unsafe_layout_detection(self):
        full = [Parcel(x=0, y=0, width=1000, height=1000)]
        bounds = RectSpec(0, 0, 1000, 1000)
        assert geo.is_unsafe_layout(full, bounds, click_through=False, opacity=1.0)
        # Click-through makes any layout safe.
        assert not geo.is_unsafe_layout(full, bounds, click_through=True, opacity=1.0)
        # So does being nearly invisible.
        assert not geo.is_unsafe_layout(full, bounds, click_through=False, opacity=0.1)

    def test_small_layout_is_safe(self):
        small = [Parcel(x=0, y=0, width=100, height=100)]
        assert not geo.is_unsafe_layout(
            small, RectSpec(0, 0, 1000, 1000), click_through=False, opacity=1.0
        )


class TestLayoutGenerators:
    def test_grid_layout_counts_and_fits(self):
        bounds = RectSpec(0, 0, 1920, 1080)
        rects = geo.grid_layout(bounds, columns=3, rows=2, gap=16, margin=48)
        assert len(rects) == 6
        for rect in rects:
            assert rect.x >= 48
            assert geo.right(rect) <= 1920 - 48 + 1

    def test_grid_layout_refuses_impossible_geometry(self):
        assert geo.grid_layout(RectSpec(0, 0, 100, 100), columns=50, rows=50) == []

    def test_rects_to_parcels_names_and_ids(self):
        rects = [RectSpec(0, 0, 10, 10), RectSpec(20, 0, 10, 10)]
        parcels = geo.rects_to_parcels(rects, name_prefix="Cell")
        assert [p.name for p in parcels] == ["Cell 1", "Cell 2"]
        assert len({p.id for p in parcels}) == 2
