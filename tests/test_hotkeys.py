"""Hotkey string parsing. Pure logic, so it runs on every platform."""

from __future__ import annotations

import pytest

from obs_overlay.constants import DEFAULT_HOTKEYS
from obs_overlay.native.hotkey_spec import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    MOD_WIN,
    HotkeyParseError,
    format_hotkey,
    normalise_hotkey,
    parse_hotkey,
)


class TestParse:
    def test_basic(self):
        spec = parse_hotkey("Ctrl+Alt+M")
        assert spec.modifiers == MOD_CONTROL | MOD_ALT
        assert spec.vk == ord("M")

    def test_case_and_order_are_normalised(self):
        assert parse_hotkey("alt+ctrl+m").text == "Ctrl+Alt+M"
        assert parse_hotkey("SHIFT+CTRL+A").text == "Ctrl+Shift+A"

    def test_all_modifiers(self):
        spec = parse_hotkey("Ctrl+Alt+Shift+Win+K")
        assert spec.modifiers == MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_WIN

    def test_modifier_aliases(self):
        for alias in ("Control", "Ctl", "ctrl"):
            assert parse_hotkey(f"{alias}+Alt+M").modifiers & MOD_CONTROL
        for alias in ("Win", "Super", "Meta", "Cmd"):
            assert parse_hotkey(f"{alias}+M").modifiers & MOD_WIN

    @pytest.mark.parametrize(
        ("text", "vk"),
        [
            ("Ctrl+F1", 0x70),
            ("Ctrl+F12", 0x7B),
            ("Ctrl+F24", 0x87),
            ("Ctrl+A", 0x41),
            ("Ctrl+Z", 0x5A),
            ("Ctrl+0", 0x30),
            ("Ctrl+9", 0x39),
            ("Ctrl+Space", 0x20),
            ("Ctrl+Esc", 0x1B),
            ("Ctrl+Enter", 0x0D),
            ("Ctrl+Tab", 0x09),
            ("Ctrl+Left", 0x25),
            ("Ctrl+Up", 0x26),
            ("Ctrl+Right", 0x27),
            ("Ctrl+Down", 0x28),
            ("Ctrl+PageUp", 0x21),
            ("Ctrl+PgDn", 0x22),
            ("Ctrl+Home", 0x24),
            ("Ctrl+End", 0x23),
            ("Ctrl+Insert", 0x2D),
            ("Ctrl+Delete", 0x2E),
            ("Ctrl+Numpad0", 0x60),
            ("Ctrl+Numpad9", 0x69),
        ],
    )
    def test_key_codes(self, text, vk):
        assert parse_hotkey(text).vk == vk

    @pytest.mark.parametrize(
        ("text", "vk"),
        [("Ctrl+.", 0xBE), ("Ctrl+,", 0xBC), ("Ctrl+/", 0xBF), ("Ctrl+-", 0xBD), ("Ctrl+;", 0xBA)],
    )
    def test_symbol_keys(self, text, vk):
        assert parse_hotkey(text).vk == vk

    def test_plus_key_is_not_mistaken_for_a_separator(self):
        assert parse_hotkey("Ctrl++").vk == 0xBB
        assert parse_hotkey("ctrl+plus").vk == 0xBB
        assert parse_hotkey("ctrl+plus").text == parse_hotkey("Ctrl++").text

    def test_whitespace_tolerated(self):
        assert parse_hotkey("  Ctrl + Alt + M  ").text == "Ctrl+Alt+M"

    def test_norepeat_is_added_for_registration(self):
        spec = parse_hotkey("Ctrl+M")
        assert spec.modifiers_with_norepeat & MOD_NOREPEAT
        assert not spec.modifiers & MOD_NOREPEAT

    def test_str_is_the_canonical_text(self):
        assert str(parse_hotkey("alt+ctrl+m")) == "Ctrl+Alt+M"


class TestParseErrors:
    @pytest.mark.parametrize("text", ["", "   ", "Ctrl", "Ctrl+Alt", "Alt+Shift"])
    def test_missing_key(self, text):
        with pytest.raises(HotkeyParseError):
            parse_hotkey(text)

    def test_missing_modifier_is_refused(self):
        # A global hotkey with no modifier would swallow that key everywhere.
        with pytest.raises(HotkeyParseError):
            parse_hotkey("M")
        with pytest.raises(HotkeyParseError):
            parse_hotkey("F5")

    def test_unknown_key(self):
        with pytest.raises(HotkeyParseError):
            parse_hotkey("Ctrl+Nonsense")

    def test_two_non_modifier_keys(self):
        with pytest.raises(HotkeyParseError):
            parse_hotkey("Ctrl+A+B")

    def test_out_of_range_function_key(self):
        with pytest.raises(HotkeyParseError):
            parse_hotkey("Ctrl+F25")
        with pytest.raises(HotkeyParseError):
            parse_hotkey("Ctrl+F0")

    def test_out_of_range_numpad(self):
        with pytest.raises(HotkeyParseError):
            parse_hotkey("Ctrl+Numpad10")


class TestFormat:
    def test_round_trip(self):
        for text in ("Ctrl+Alt+M", "Ctrl+Shift+F9", "Win+Space", "Ctrl+Numpad5", "Ctrl+Left"):
            assert parse_hotkey(parse_hotkey(text).text).text == parse_hotkey(text).text

    def test_format_unknown_vk_falls_back_to_hex(self):
        assert format_hotkey(MOD_CONTROL, 0x01) == "Ctrl+0x01"

    def test_normalise_leaves_invalid_text_alone(self):
        assert normalise_hotkey("not a hotkey") == "not a hotkey"
        assert normalise_hotkey("alt+ctrl+m") == "Ctrl+Alt+M"


class TestDefaults:
    def test_every_default_parses(self):
        for action, combo in DEFAULT_HOTKEYS.items():
            spec = parse_hotkey(combo)
            assert spec.modifiers, f"{action} has no modifier"

    def test_no_default_uses_f12(self):
        # Windows reserves F12 for the debugger; RegisterHotKey refuses it.
        for action, combo in DEFAULT_HOTKEYS.items():
            assert parse_hotkey(combo).vk != 0x7B, f"{action} uses F12"

    def test_defaults_are_unique(self):
        canonical = [parse_hotkey(c).text for c in DEFAULT_HOTKEYS.values()]
        assert len(set(canonical)) == len(canonical)


class TestNullManager:
    def test_reports_everything_unsupported(self):
        from obs_overlay.native.base import NullHotkeyManager

        manager = NullHotkeyManager()
        assert manager.start(lambda action: None) is False
        failures = manager.apply({"toggle_editor": "Ctrl+Alt+M", "unused": ""})
        assert "toggle_editor" in failures
        assert "unused" not in failures  # an empty binding is not a failure
        assert manager.registered_actions() == []
        manager.stop()


class TestNullWindowController:
    def test_all_operations_report_failure_without_raising(self):
        from obs_overlay.native.base import NullWindowController

        controller = NullWindowController()
        assert controller.attach(1234) is False
        assert controller.set_click_through(True) is False
        assert controller.set_tool_window(True) is False
        assert controller.set_no_activate(True) is False
        assert controller.set_topmost(True) is False
        assert controller.reassert_topmost() is False
        assert controller.set_excluded_from_capture(True) is False
        assert controller.is_click_through() is None
        controller.detach()

    def test_factory_returns_something_usable_on_any_platform(self):
        from obs_overlay.native import create_hotkey_manager, create_window_controller

        controller = create_window_controller()
        assert hasattr(controller, "set_click_through")
        manager = create_hotkey_manager()
        assert hasattr(manager, "apply")
