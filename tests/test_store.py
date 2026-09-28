"""Profile storage: atomicity, corruption recovery, naming and migrations."""

from __future__ import annotations

import json

import pytest

from obs_overlay.config.migrations import detect_version, migrate
from obs_overlay.config.models import Profile
from obs_overlay.config.store import (
    ProfileStoreError,
    atomic_write_json,
    read_json,
    slugify,
)
from obs_overlay.constants import PROFILE_SCHEMA_VERSION


class TestSlugify:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Default", "Default"),
            ("My Stream", "My_Stream"),
            ("a/b\\c:d*e?f", "a_b_c_d_e_f"),
            ("  spaced  ", "spaced"),
            ("", "profile"),
            ("...", "profile"),
        ],
    )
    def test_basic(self, name, expected):
        assert slugify(name) == expected

    def test_windows_reserved_names_are_escaped(self):
        for reserved in ("CON", "con", "PRN", "COM1", "LPT9"):
            assert slugify(reserved).upper() != reserved.upper()

    def test_trailing_dot_and_space_removed(self):
        # Windows silently strips these, which would break round-tripping.
        assert not slugify("name. ").endswith((".", " "))

    def test_length_is_bounded(self):
        assert len(slugify("x" * 500)) <= 80

    def test_control_characters_removed(self):
        assert "\x00" not in slugify("a\x00b")
        assert "\n" not in slugify("a\nb")


class TestAtomicWrite:
    def test_write_and_read(self, tmp_path):
        target = tmp_path / "x.json"
        atomic_write_json(target, {"a": 1})
        assert read_json(target) == {"a": 1}

    def test_no_temp_files_left_behind(self, tmp_path):
        target = tmp_path / "x.json"
        atomic_write_json(target, {"a": 1})
        atomic_write_json(target, {"a": 2})
        assert sorted(p.name for p in tmp_path.iterdir()) == ["x.json"]

    def test_creates_parent_directories(self, tmp_path):
        target = tmp_path / "deep" / "nested" / "x.json"
        atomic_write_json(target, {"ok": True})
        assert target.is_file()

    def test_overwrites_existing(self, tmp_path):
        target = tmp_path / "x.json"
        target.write_text("old", encoding="utf-8")
        atomic_write_json(target, {"new": True})
        assert read_json(target) == {"new": True}

    def test_unicode_survives(self, tmp_path):
        target = tmp_path / "x.json"
        atomic_write_json(target, {"name": "Parsel — kotak éè"})
        assert read_json(target)["name"] == "Parsel — kotak éè"

    def test_read_json_rejects_non_object(self, tmp_path):
        target = tmp_path / "list.json"
        target.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(ProfileStoreError):
            read_json(target)

    def test_read_json_rejects_malformed(self, tmp_path):
        target = tmp_path / "bad.json"
        target.write_text("{not json", encoding="utf-8")
        with pytest.raises(ProfileStoreError):
            read_json(target)

    def test_read_json_missing_file(self, tmp_path):
        with pytest.raises(ProfileStoreError):
            read_json(tmp_path / "nope.json")


class TestConfigStore:
    def test_bootstrap_creates_default(self, store):
        store.bootstrap()
        assert store.list_profiles() == ["Default"]

    def test_save_and_load_round_trip(self, store):
        profile = Profile.default("Stream")
        profile.source.sender_name = "MySender"
        profile.parcels[0].x = 1234
        store.save_profile(profile)

        loaded = store.load_profile("Stream")
        assert loaded.name == "Stream"
        assert loaded.source.sender_name == "MySender"
        assert loaded.parcels[0].x == 1234

    def test_missing_profile_yields_default_with_that_name(self, store):
        loaded = store.load_profile("Nonexistent")
        assert loaded.name == "Nonexistent"
        assert loaded.parcels

    def test_corrupt_profile_is_quarantined_not_fatal(self, store):
        path = store.profile_path("Broken")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{{{ not json", encoding="utf-8")

        loaded = store.load_profile("Broken")
        assert loaded.name == "Broken"
        assert not path.exists()
        assert any(p.name.endswith(".corrupt") for p in store.profiles_dir.iterdir())

    def test_display_name_comes_from_file_contents(self, store):
        profile = Profile.default("Pretty Name")
        store.save_profile(profile)
        assert "Pretty Name" in store.list_profiles()

    def test_delete(self, store):
        store.save_profile(Profile.default("Temp"))
        assert store.delete_profile("Temp")
        assert not store.delete_profile("Temp")
        assert "Temp" not in store.list_profiles()

    def test_rename(self, store):
        store.save_profile(Profile.default("Old"))
        renamed = store.rename_profile("Old", "New")
        assert renamed.name == "New"
        assert store.list_profiles() == ["New"]

    def test_rename_to_existing_is_refused(self, store):
        store.save_profile(Profile.default("A"))
        store.save_profile(Profile.default("B"))
        with pytest.raises(ProfileStoreError):
            store.rename_profile("A", "B")

    def test_rename_to_same_slug_keeps_one_file(self, store):
        store.save_profile(Profile.default("My Name"))
        store.rename_profile("My Name", "My  Name")
        assert len(list(store.profiles_dir.glob("*.json"))) == 1

    def test_duplicate_gets_fresh_parcel_ids(self, store):
        original = Profile.default("Source")
        store.save_profile(original)
        copy = store.duplicate_profile("Source", "Copy")
        assert copy.name == "Copy"
        assert {p.id for p in copy.parcels}.isdisjoint({p.id for p in original.parcels})

    def test_duplicate_to_existing_is_refused(self, store):
        store.save_profile(Profile.default("A"))
        store.save_profile(Profile.default("B"))
        with pytest.raises(ProfileStoreError):
            store.duplicate_profile("A", "B")

    def test_export_import_round_trip(self, store, tmp_path):
        profile = Profile.default("Exported")
        profile.display.opacity = 0.42
        store.save_profile(profile)

        target = tmp_path / "out.json"
        store.export_profile(profile, target)
        assert target.is_file()

        imported = store.import_profile(target)
        assert imported.display.opacity == pytest.approx(0.42)

    def test_import_never_overwrites(self, store, tmp_path):
        profile = Profile.default("Clash")
        store.save_profile(profile)
        target = tmp_path / "clash.json"
        store.export_profile(profile, target)

        imported = store.import_profile(target)
        assert imported.name != "Clash"
        assert "Clash" in store.list_profiles()
        assert imported.name in store.list_profiles()

    def test_settings_round_trip(self, store):
        settings = store.load_settings()
        settings.active_profile = "Chosen"
        settings.log_level = "DEBUG"
        store.save_settings(settings)
        assert store.load_settings().active_profile == "Chosen"
        assert store.load_settings().log_level == "DEBUG"

    def test_corrupt_settings_recovered(self, store):
        store.settings_file.parent.mkdir(parents=True, exist_ok=True)
        store.settings_file.write_text("garbage", encoding="utf-8")
        settings = store.load_settings()
        assert settings.active_profile  # a usable default
        assert not store.settings_file.exists()

    def test_saved_file_is_valid_json_with_indentation(self, store):
        store.save_profile(Profile.default("Readable"))
        text = store.profile_path("Readable").read_text(encoding="utf-8")
        assert json.loads(text)["name"] == "Readable"
        assert "\n  " in text  # human-editable


class TestMigrations:
    def test_detects_blueprint_era_layout(self):
        assert detect_version({"boxes": [[0, 0, 10, 10]]}) == 1
        assert detect_version({"sender": "X"}) == 1

    def test_unversioned_modern_file_is_treated_as_current(self):
        assert detect_version({"parcels": []}) == PROFILE_SCHEMA_VERSION

    def test_explicit_version_wins(self):
        assert detect_version({"schema_version": 1, "parcels": []}) == 1
        assert detect_version({"schema_version": "1"}) == 1

    def test_v1_boxes_become_parcels(self):
        migrated = migrate(
            {"schema_version": 1, "boxes": [[100, 100, 300, 300], [500, 100, 300, 300]]}
        )
        assert migrated["schema_version"] == PROFILE_SCHEMA_VERSION
        assert len(migrated["parcels"]) == 2
        assert migrated["parcels"][0] == {
            "name": "Box 1",
            "x": 100,
            "y": 100,
            "width": 300,
            "height": 300,
            "shape": "rect",
        }

    def test_v1_scalars_are_grouped(self):
        migrated = migrate(
            {"schema_version": 1, "sender": "OBS_Sender", "fps": 30, "click_through": False}
        )
        assert migrated["source"]["sender_name"] == "OBS_Sender"
        assert migrated["source"]["target_fps"] == 30
        assert migrated["behavior"]["click_through"] is False

    def test_v1_dict_boxes_also_work(self):
        migrated = migrate({"schema_version": 1, "boxes": [{"x": 1, "y": 2, "w": 3, "h": 4}]})
        assert migrated["parcels"][0]["width"] == 3

    def test_migrated_dict_loads_into_a_profile(self):
        migrated = migrate({"schema_version": 1, "boxes": [[10, 20, 300, 400]], "sender": "S"})
        profile = Profile.from_dict(migrated)
        assert profile.source.sender_name == "S"
        assert profile.parcels[0].width == 300

    def test_newer_schema_passes_through(self):
        future = {"schema_version": PROFILE_SCHEMA_VERSION + 5, "name": "Future"}
        assert migrate(future)["schema_version"] == PROFILE_SCHEMA_VERSION + 5

    def test_non_dict_input(self):
        assert migrate("nonsense")["schema_version"] == PROFILE_SCHEMA_VERSION  # type: ignore[arg-type]

    def test_current_schema_untouched(self):
        original = Profile.default().to_dict()
        assert migrate(dict(original)) == original

    def test_store_migrates_on_load(self, store):
        path = store.profile_path("Legacy")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"schema_version": 1, "name": "Legacy", "boxes": [[5, 5, 50, 50]]}),
            encoding="utf-8",
        )
        loaded = store.load_profile("Legacy")
        assert loaded.parcels[0].x == 5
        # The migrated form is written back, so the next load is cheap.
        assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == (
            PROFILE_SCHEMA_VERSION
        )
