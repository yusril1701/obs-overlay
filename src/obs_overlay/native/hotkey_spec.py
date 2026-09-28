"""Parsing human-readable hotkey strings into Win32 modifier/virtual-key pairs.

Deliberately free of ``ctypes`` and of any Windows import so the parser can be
unit-tested anywhere. The numeric values are Win32's, taken from
``winuser.h``.
"""

from __future__ import annotations

from dataclasses import dataclass

# -- RegisterHotKey modifier flags -----------------------------------------
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
#: Suppresses auto-repeat while the combination is held (Windows 7+).
MOD_NOREPEAT = 0x4000

_MODIFIER_ALIASES: dict[str, int] = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "ctl": MOD_CONTROL,
    "alt": MOD_ALT,
    "menu": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
    "meta": MOD_WIN,
    "cmd": MOD_WIN,
}

#: Canonical display order, so "Alt+Ctrl+M" normalises to "Ctrl+Alt+M".
_MODIFIER_ORDER: tuple[tuple[int, str], ...] = (
    (MOD_CONTROL, "Ctrl"),
    (MOD_ALT, "Alt"),
    (MOD_SHIFT, "Shift"),
    (MOD_WIN, "Win"),
)

# -- Virtual key codes ------------------------------------------------------
_NAMED_KEYS: dict[str, int] = {
    "backspace": 0x08,
    "tab": 0x09,
    "clear": 0x0C,
    "enter": 0x0D,
    "return": 0x0D,
    "pause": 0x13,
    "capslock": 0x14,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pgup": 0x21,
    "pagedown": 0x22,
    "pgdn": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "print": 0x2A,
    "printscreen": 0x2C,
    "prtsc": 0x2C,
    "insert": 0x2D,
    "ins": 0x2D,
    "delete": 0x2E,
    "del": 0x2E,
    "numlock": 0x90,
    "scrolllock": 0x91,
    "plus": 0xBB,
    "comma": 0xBC,
    "minus": 0xBD,
    "period": 0xBE,
    "slash": 0xBF,
    "backtick": 0xC0,
    "grave": 0xC0,
    "tilde": 0xC0,
    "lbracket": 0xDB,
    "backslash": 0xDC,
    "rbracket": 0xDD,
    "quote": 0xDE,
    "semicolon": 0xBA,
}

#: Symbols users are likely to type directly rather than by name. "+" is here
#: because the tokeniser hands it through as a key when it is not acting as the
#: separator, so "Ctrl++" means Ctrl plus the plus key.
_SYMBOL_KEYS: dict[str, int] = {
    "+": 0xBB,
    ";": 0xBA,
    "=": 0xBB,
    ",": 0xBC,
    "-": 0xBD,
    ".": 0xBE,
    "/": 0xBF,
    "`": 0xC0,
    "[": 0xDB,
    "\\": 0xDC,
    "]": 0xDD,
    "'": 0xDE,
}

#: Reverse lookup for :func:`format_hotkey`.
_VK_NAMES: dict[int, str] = {
    0x08: "Backspace",
    0x09: "Tab",
    0x0D: "Enter",
    0x13: "Pause",
    0x1B: "Esc",
    0x20: "Space",
    0x21: "PageUp",
    0x22: "PageDown",
    0x23: "End",
    0x24: "Home",
    0x25: "Left",
    0x26: "Up",
    0x27: "Right",
    0x28: "Down",
    0x2C: "PrintScreen",
    0x2D: "Insert",
    0x2E: "Delete",
    0x90: "NumLock",
    0x91: "ScrollLock",
    # OEM keys render as the symbol they produce on a US layout, so that
    # "ctrl+plus" and "Ctrl++" normalise to the same string.
    0xBA: ";",
    0xBB: "+",
    0xBC: ",",
    0xBD: "-",
    0xBE: ".",
    0xBF: "/",
    0xC0: "`",
    0xDB: "[",
    0xDC: "\\",
    0xDD: "]",
    0xDE: "'",
}


class HotkeyParseError(ValueError):
    """The hotkey string could not be understood."""


@dataclass(frozen=True)
class HotkeySpec:
    """A parsed hotkey: modifier bitmask plus a virtual-key code."""

    modifiers: int
    vk: int
    text: str

    @property
    def modifiers_with_norepeat(self) -> int:
        return self.modifiers | MOD_NOREPEAT

    def __str__(self) -> str:
        return self.text


def _parse_key_token(token: str) -> int | None:
    lowered = token.lower()

    if lowered in _NAMED_KEYS:
        return _NAMED_KEYS[lowered]
    if token in _SYMBOL_KEYS:
        return _SYMBOL_KEYS[token]

    # F1 - F24
    if len(lowered) >= 2 and lowered[0] == "f" and lowered[1:].isdigit():
        number = int(lowered[1:])
        if 1 <= number <= 24:
            return 0x70 + number - 1
        return None

    # Numpad0 - Numpad9
    if lowered.startswith("numpad") and lowered[6:].isdigit():
        number = int(lowered[6:])
        if 0 <= number <= 9:
            return 0x60 + number
        return None

    if len(token) == 1:
        char = token.upper()
        if "A" <= char <= "Z":
            return ord(char)
        if "0" <= char <= "9":
            return ord(char)

    return None


def parse_hotkey(text: str) -> HotkeySpec:
    """Parse ``"Ctrl+Alt+M"`` into modifiers and a virtual-key code.

    Raises :class:`HotkeyParseError` for an empty string, an unknown key name,
    a missing non-modifier key, or more than one non-modifier key.
    """
    if not text or not text.strip():
        raise HotkeyParseError("Hotkey is empty.")

    # "Ctrl++" means Ctrl plus the "+" key; splitting naively would lose it.
    raw = text.strip()
    tokens = []
    buffer = ""
    for index, char in enumerate(raw):
        if char == "+" and buffer:
            tokens.append(buffer)
            buffer = ""
        elif char == "+" and not buffer and index + 1 == len(raw):
            tokens.append("+")
        elif char == "+" and not buffer:
            # A leading or doubled '+' is the key itself.
            tokens.append("+")
        else:
            buffer += char
    if buffer:
        tokens.append(buffer)

    tokens = [token.strip() for token in tokens if token.strip()]
    if not tokens:
        raise HotkeyParseError(f"Hotkey {text!r} has no keys.")

    modifiers = 0
    key_vk: int | None = None
    key_name = ""

    for token in tokens:
        lowered = token.lower()
        if lowered in _MODIFIER_ALIASES:
            modifiers |= _MODIFIER_ALIASES[lowered]
            continue
        vk = _parse_key_token(token)
        if vk is None:
            raise HotkeyParseError(f"Unknown key {token!r} in hotkey {text!r}.")
        if key_vk is not None:
            raise HotkeyParseError(f"Hotkey {text!r} has more than one non-modifier key.")
        key_vk = vk
        key_name = token

    if key_vk is None:
        raise HotkeyParseError(f"Hotkey {text!r} has modifiers but no key.")
    if modifiers == 0:
        raise HotkeyParseError(
            f"Hotkey {text!r} has no modifier. A global hotkey without "
            "Ctrl/Alt/Shift/Win would swallow that key everywhere."
        )

    return HotkeySpec(
        modifiers=modifiers, vk=key_vk, text=format_hotkey(modifiers, key_vk, key_name)
    )


def format_hotkey(modifiers: int, vk: int, fallback_name: str = "") -> str:
    """Render modifiers + virtual key back into canonical display form."""
    parts = [label for bit, label in _MODIFIER_ORDER if modifiers & bit]

    if vk in _VK_NAMES:
        parts.append(_VK_NAMES[vk])
    elif 0x70 <= vk <= 0x87:
        parts.append(f"F{vk - 0x70 + 1}")
    elif 0x60 <= vk <= 0x69:
        parts.append(f"Numpad{vk - 0x60}")
    elif 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        parts.append(chr(vk))
    elif fallback_name:
        parts.append(fallback_name.upper() if len(fallback_name) == 1 else fallback_name)
    else:
        parts.append(f"0x{vk:02X}")

    return "+".join(parts)


def normalise_hotkey(text: str) -> str:
    """Canonical form of a hotkey string, or the original if it does not parse."""
    try:
        return parse_hotkey(text).text
    except HotkeyParseError:
        return text
