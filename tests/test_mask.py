"""QRegion / QPainterPath mask building. Needs a QApplication (offscreen)."""

from __future__ import annotations

import pytest

from obs_overlay.config.models import BooleanOp, Parcel, RectSpec, ShapeType

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _app(qapp):
    return qapp


def _region(parcels, bounds=RectSpec(0, 0, 800, 600), grow=0):
    from obs_overlay.core.mask import build_region

    return build_region(parcels, bounds, grow=grow)


class TestBuildRegion:
    def test_empty_parcels_give_an_empty_region(self):
        assert _region([]).isEmpty()

    def test_all_disabled_gives_an_empty_region(self):
        assert _region([Parcel(x=0, y=0, width=10, height=10, enabled=False)]).isEmpty()

    def test_single_rect(self):
        region = _region([Parcel(x=10, y=20, width=100, height=50)])
        bounds = region.boundingRect()
        assert (bounds.x(), bounds.y(), bounds.width(), bounds.height()) == (10, 20, 100, 50)

    def test_rect_only_layout_uses_the_cheap_path(self):
        # Two disjoint rectangles should decompose into exactly two rects, not
        # the hundreds a bitmap round-trip would produce.
        region = _region(
            [
                Parcel(x=0, y=0, width=100, height=100),
                Parcel(x=300, y=0, width=100, height=100),
            ]
        )
        assert region.rectCount() == 2

    def test_grow_dilates_the_region(self):
        plain = _region([Parcel(x=100, y=100, width=50, height=50)], grow=0)
        grown = _region([Parcel(x=100, y=100, width=50, height=50)], grow=2)
        assert grown.boundingRect().width() > plain.boundingRect().width()

    def test_contains_expected_points(self):
        from PyQt6.QtCore import QPoint

        region = _region([Parcel(x=100, y=100, width=100, height=100)])
        assert region.contains(QPoint(150, 150))
        assert not region.contains(QPoint(50, 50))

    def test_subtract_removes_area(self):
        from PyQt6.QtCore import QPoint

        parcels = [
            Parcel(x=0, y=0, width=200, height=200),
            Parcel(x=50, y=50, width=100, height=100, op=BooleanOp.SUBTRACT),
        ]
        region = _region(parcels)
        assert region.contains(QPoint(10, 10))
        assert not region.contains(QPoint(100, 100))

    def test_ellipse_is_not_rectangular(self):
        from PyQt6.QtCore import QPoint

        region = _region([Parcel(x=0, y=0, width=200, height=200, shape=ShapeType.ELLIPSE)])
        assert region.contains(QPoint(100, 100))  # centre
        assert not region.contains(QPoint(2, 2))  # corner outside the ellipse

    def test_rounded_rect_cuts_its_corners(self):
        from PyQt6.QtCore import QPoint

        region = _region(
            [
                Parcel(
                    x=0,
                    y=0,
                    width=200,
                    height=200,
                    shape=ShapeType.ROUNDED_RECT,
                    corner_radius=60,
                )
            ]
        )
        assert region.contains(QPoint(100, 100))
        assert not region.contains(QPoint(1, 1))

    def test_zero_radius_rounded_rect_takes_the_rect_path(self):
        region = _region(
            [Parcel(x=0, y=0, width=100, height=100, shape=ShapeType.ROUNDED_RECT, corner_radius=0)]
        )
        assert region.rectCount() == 1

    def test_radius_is_clamped_to_half_the_side(self):
        from PyQt6.QtCore import QPoint

        # A radius far larger than the box must produce a stadium/ellipse, not
        # a degenerate or inverted shape.
        region = _region(
            [
                Parcel(
                    x=0,
                    y=0,
                    width=100,
                    height=100,
                    shape=ShapeType.ROUNDED_RECT,
                    corner_radius=9999,
                )
            ]
        )
        assert region.contains(QPoint(50, 50))
        assert not region.isEmpty()

    def test_polygon(self):
        from PyQt6.QtCore import QPoint

        parcel = Parcel(
            x=0,
            y=0,
            width=200,
            height=200,
            shape=ShapeType.POLYGON,
            points=[(0.5, 0.0), (1.0, 1.0), (0.0, 1.0)],
        )
        region = _region([parcel])
        assert region.contains(QPoint(100, 150))  # inside the triangle
        assert not region.contains(QPoint(5, 5))  # above the apex

    def test_parcel_outside_bounds_still_builds(self):
        region = _region(
            [Parcel(x=-500, y=-500, width=100, height=100, shape=ShapeType.ELLIPSE)],
            bounds=RectSpec(0, 0, 100, 100),
        )
        assert region.isEmpty() or region.boundingRect().isValid()

    def test_many_parcels(self):
        parcels = [Parcel(x=i * 20, y=0, width=15, height=15) for i in range(40)]
        region = _region(parcels)
        assert region.rectCount() == 40


class TestBuildPath:
    def test_empty(self):
        from obs_overlay.core.mask import build_path

        assert build_path([]).isEmpty()

    def test_union_bounding_box(self):
        from obs_overlay.core.mask import build_path

        path = build_path(
            [
                Parcel(x=0, y=0, width=100, height=100),
                Parcel(x=200, y=0, width=100, height=100),
            ]
        )
        bounds = path.boundingRect()
        assert bounds.left() == pytest.approx(0)
        assert bounds.right() == pytest.approx(300)

    def test_subtract_shrinks_the_path(self):
        from obs_overlay.core.mask import build_path

        whole = build_path([Parcel(x=0, y=0, width=200, height=200)])
        holed = build_path(
            [
                Parcel(x=0, y=0, width=200, height=200),
                Parcel(x=50, y=50, width=100, height=100, op=BooleanOp.SUBTRACT),
            ]
        )
        assert holed.contains(_point(10, 10))
        assert not holed.contains(_point(100, 100))
        assert whole.contains(_point(100, 100))

    def test_disabled_parcels_excluded(self):
        from obs_overlay.core.mask import build_path

        path = build_path([Parcel(x=0, y=0, width=100, height=100, enabled=False)])
        assert path.isEmpty()


def _point(x, y):
    from PyQt6.QtCore import QPointF

    return QPointF(float(x), float(y))


class TestImageMask:
    def test_white_keeps_black_cuts(self):
        from PyQt6.QtCore import QPoint
        from PyQt6.QtGui import QColor, QImage

        from obs_overlay.core.mask import region_from_image

        image = QImage(20, 10, QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 255))
        for x in range(10):
            for y in range(10):
                image.setPixelColor(x, y, QColor(255, 255, 255, 255))

        region = region_from_image(image)
        assert region.contains(QPoint(5, 5))
        assert not region.contains(QPoint(15, 5))

    def test_transparent_pixels_are_cut(self):
        from PyQt6.QtCore import QPoint
        from PyQt6.QtGui import QColor, QImage

        from obs_overlay.core.mask import region_from_image

        image = QImage(10, 10, QImage.Format.Format_ARGB32)
        image.fill(QColor(255, 255, 255, 0))
        region = region_from_image(image)
        assert not region.contains(QPoint(5, 5))

    def test_null_image_gives_empty_region(self):
        from PyQt6.QtGui import QImage

        from obs_overlay.core.mask import region_from_image

        assert region_from_image(QImage()).isEmpty()

    def test_missing_file_raises(self):
        from obs_overlay.core.mask import region_from_image_file

        with pytest.raises(ValueError):
            region_from_image_file("/definitely/not/here.png")


class TestParcelsFromRegion:
    def test_single_rect_round_trip(self):
        from obs_overlay.core.mask import parcels_from_region

        region = _region([Parcel(x=10, y=10, width=40, height=30)])
        parcels = parcels_from_region(region)
        assert len(parcels) == 1
        assert parcels[0].rect == RectSpec(10, 10, 40, 30)

    def test_two_disjoint_rects(self):
        from obs_overlay.core.mask import parcels_from_region

        region = _region(
            [
                Parcel(x=0, y=0, width=20, height=20),
                Parcel(x=60, y=0, width=20, height=20),
            ]
        )
        parcels = parcels_from_region(region)
        assert len(parcels) == 2
        assert {(p.x, p.width) for p in parcels} == {(0, 20), (60, 20)}

    def test_empty_region(self):
        from PyQt6.QtGui import QRegion

        from obs_overlay.core.mask import parcels_from_region

        assert parcels_from_region(QRegion()) == []

    def test_respects_the_cap(self):
        from obs_overlay.core.mask import parcels_from_region

        region = _region([Parcel(x=i * 4, y=0, width=2, height=2) for i in range(30)])
        assert len(parcels_from_region(region, max_parcels=5)) <= 5
