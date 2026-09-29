"""Profile model behaviour: round-tripping, coercion and hostile input."""

from __future__ import annotations

import json
import math

import pytest

from obs_overlay.config.models import (
    Anchor,
    AppSettings,
    BooleanOp,
    FitMode,
    GeometryMode,
    Parcel,
    Profile,
    RectSpec,
    ScaleQuality,
    ShapeType,
    SourceKind,
    _as_bool,
    _as_enum,
    _as_float,
    _as_int,
)
from obs_overlay.constants import MIN_PARCEL_SIZE, PROFILE_SCHEMA_VERSION


class TestCoercion:
    @pytest.mark.parametrize(
        ("value", "default", "expected"),
        [
            (True, False, True),
            ("yes", False, True),
            ("OFF", True, False),
            (1, False, True),
            (0, True, False),
            (None, True, True),
            ("banana", False, False),
        ],
    )
    def test_as_bool(self, value, default, expected):
        assert _as_bool(value, default) is expected

    def test_as_int_clamps(self):
        assert _as_int(500, 0, lo=0, hi=100) == 100
        assert _as_int(-5, 0, lo=0, hi=100) == 0
        assert _as_int("42", 0) == 42
        assert _as_int("nope", 7) == 7
        assert _as_int(None, 7) == 7

    def test_as_int_rejects_bool(self):
        # bool is an int subclass; treating True as 1 here would silently
        # accept a checkbox value where a number belongs.
        assert _as_int(True, 9) == 9

    def test_as_float_rejects_nan_and_inf(self):
        assert _as_float(float("nan"), 1.0) == 1.0
        assert _as_float(float("inf"), 1.0) == 1.0
        assert _as_float(float("-inf"), 1.0) == 1.0
        assert not math.isnan(_as_float("x", 0.5))

    def test_as_enum_accepts_name_value_and_case(self):
        assert _as_enum(ShapeType, "ellipse", ShapeType.RECT) is ShapeType.ELLIPSE
        assert _as_enum(ShapeType, "ELLIPSE", ShapeType.RECT) is ShapeType.ELLIPSE
        assert _as_enum(ShapeType, "rounded_rect", ShapeType.RECT) is ShapeType.ROUNDED_RECT
        assert _as_enum(ShapeType, "nonsense", ShapeType.RECT) is ShapeType.RECT
        assert _as_enum(ShapeType, None, ShapeType.ELLIPSE) is ShapeType.ELLIPSE


class TestParcel:
    def test_round_trip(self):
        parcel = Parcel(
            name="Box",
            x=10,
            y=20,
            width=300,
            height=200,
            shape=ShapeType.ROUNDED_RECT,
            corner_radius=12,
            op=BooleanOp.SUBTRACT,
            enabled=False,
            locked=True,
        )
        assert Parcel.from_dict(parcel.to_dict()).to_dict() == parcel.to_dict()

    def test_geometry_helpers(self):
        parcel = Parcel(x=10, y=20, width=100, height=50)
        assert parcel.right == 110
        assert parcel.bottom == 70
        assert parcel.center == (60, 45)
        assert parcel.rect == RectSpec(10, 20, 100, 50)

    def test_minimum_size_enforced(self):
        parcel = Parcel.from_dict({"width": 1, "height": -40})
        assert parcel.width >= MIN_PARCEL_SIZE
        assert parcel.height >= MIN_PARCEL_SIZE

    def test_clone_gets_new_id_and_offset(self):
        original = Parcel(name="A", x=5, y=5)
        clone = original.clone(offset=10)
        assert clone.id != original.id
        assert (clone.x, clone.y) == (15, 15)
        assert clone.name == "A copy"

    def test_polygon_gets_default_points(self):
        parcel = Parcel.from_dict({"shape": "polygon"})
        assert len(parcel.points) >= 3
        assert all(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 for x, y in parcel.points)

    def test_polygon_points_accept_both_shapes(self):
        parcel = Parcel.from_dict(
            {"shape": "polygon", "points": [[0, 0], {"x": 1, "y": 0}, [0.5, 1]]}
        )
        assert parcel.points == [(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)]

    def test_moved_and_with_rect(self):
        parcel = Parcel(x=0, y=0, width=100, height=100)
        assert parcel.moved(5, -5).rect == RectSpec(5, -5, 100, 100)
        assert parcel.with_rect(RectSpec(1, 2, 3, 4)).width == MIN_PARCEL_SIZE

    def test_display_name_falls_back_to_id(self):
        parcel = Parcel(name="")
        assert parcel.display_name.startswith("Parcel ")


class TestProfile:
    def test_default_round_trip(self):
        profile = Profile.default()
        assert Profile.from_dict(profile.to_dict()).to_dict() == profile.to_dict()

    def test_schema_version_is_stamped(self):
        assert Profile.default().to_dict()["schema_version"] == PROFILE_SCHEMA_VERSION

    def test_empty_dict_yields_usable_profile(self):
        profile = Profile.from_dict({})
        assert profile.name
        assert profile.parcels  # missing key -> starter layout

    def test_explicit_empty_parcels_is_respected(self):
        # An empty overlay is a legitimate configuration and must not be
        # silently replaced by the starter layout.
        profile = Profile.from_dict({"parcels": []})
        assert profile.parcels == []

    def test_hostile_input_does_not_raise(self):
        garbage = {
            "schema_version": "wat",
            "name": 12345,
            "source": "not a dict",
            "display": {"opacity": "abc", "zoom": None},
            "behavior": [1, 2, 3],
            "parcels": ["nope", {"x": "x"}, None, 42],
            "hotkeys": {"panic": None},
        }
        profile = Profile.from_dict(garbage)
        assert isinstance(profile.name, str)
        assert profile.display.opacity == 1.0
        assert profile.display.zoom == 1.0
        assert len(profile.parcels) == 4

    def test_duplicate_ids_are_repaired(self):
        profile = Profile.from_dict({"parcels": [{"id": "same"}, {"id": "same"}, {"id": "same"}]})
        ids = [p.id for p in profile.parcels]
        assert len(set(ids)) == 3

    def test_lookup_helpers(self):
        profile = Profile.default()
        first = profile.parcels[0]
        assert profile.parcel_by_id(first.id) is first
        assert profile.index_of(first.id) == 0
        assert profile.parcel_by_id("missing") is None
        assert profile.index_of("missing") == -1

    def test_remove_and_replace(self):
        profile = Profile.default()
        first = profile.parcels[0]
        changed = Parcel.from_dict({**first.to_dict(), "name": "renamed"})
        assert profile.replace_parcel(changed)
        assert profile.parcels[0].name == "renamed"
        assert profile.remove_parcel(first.id)
        assert profile.index_of(first.id) == -1
        assert not profile.remove_parcel("missing")

    def test_copy_is_deep_enough(self):
        profile = Profile.default()
        clone = profile.copy()
        clone.parcels[0].x = 9999
        assert profile.parcels[0].x != 9999

    def test_active_parcels_filters_disabled(self):
        profile = Profile.default()
        profile.parcels[0].enabled = False
        assert len(profile.active_parcels()) == len(profile.parcels) - 1

    def test_json_serialisable(self):
        # The store writes with json.dumps; enums must survive it. Compare
        # against the same instance, since Profile.default() mints fresh ids.
        original = Profile.default().to_dict()
        text = json.dumps(original)
        assert Profile.from_dict(json.loads(text)).to_dict() == original

    def test_enum_defaults(self):
        profile = Profile.default()
        assert profile.source.kind is SourceKind.SPOUT
        assert profile.display.fit_mode is FitMode.CONTAIN
        assert profile.display.anchor is Anchor.CENTER
        assert profile.display.geometry_mode is GeometryMode.PRIMARY
        assert profile.display.scale_quality is ScaleQuality.SMOOTH

    def test_spout_premultiplied_defaults_true(self):
        # The OBS Spout filter composites with premultiplied alpha, so this is
        # the correct default for the supported path.
        assert Profile.default().source.spout.premultiplied_alpha is True

    def test_ndi_premultiplied_defaults_false(self):
        # NDI's specification is explicit that its RGBA data is not
        # premultiplied — the opposite of Spout.
        assert Profile.default().source.ndi.premultiplied_alpha is False

    def test_every_source_group_survives_a_round_trip(self):
        profile = Profile.default()
        profile.source.spout.sender_name = "A"
        profile.source.ndi.source_name = "B"
        profile.source.screen.monitor_index = 2
        profile.source.image.path = "/tmp/x.png"

        restored = Profile.from_dict(profile.to_dict())
        assert restored.source.spout.sender_name == "A"
        assert restored.source.ndi.source_name == "B"
        assert restored.source.screen.monitor_index == 2
        assert restored.source.image.path == "/tmp/x.png"

    def test_inactive_source_groups_are_kept(self):
        # Switching kind must not discard what the other kinds were set to.
        profile = Profile.default()
        profile.source.ndi.source_name = "Remembered"
        profile.source.kind = SourceKind.SCREEN
        assert Profile.from_dict(profile.to_dict()).source.ndi.source_name == "Remembered"


class TestAppSettings:
    def test_round_trip(self):
        settings = AppSettings(active_profile="X", log_level="DEBUG", language="en")
        assert AppSettings.from_dict(settings.to_dict()).to_dict() == settings.to_dict()

    def test_invalid_values_fall_back(self):
        settings = AppSettings.from_dict({"log_level": "LOUD", "language": "kl"})
        assert settings.log_level == "INFO"
        assert settings.language == "id"

    def test_panel_geometry_optional(self):
        assert AppSettings.from_dict({}).panel_geometry is None
        restored = AppSettings.from_dict(
            {"panel_geometry": {"x": 1, "y": 2, "width": 3, "height": 4}}
        )
        assert restored.panel_geometry == RectSpec(1, 2, 3, 4)
