"""Game-compatible key press for CS2 (DirectInput scancodes — layout-independent)."""

from __future__ import annotations

import sys
import time

from modules.ui_nav.actions import focus_window
from modules.ui_nav.errors import UiNavError, UiNavPlatformError

_F_KEYS = frozenset({f"f{i}" for i in range(1, 13)})

# US QWERTY physical scancodes (set 1) — CS2 binds use key names, not OS layout chars.
_LETTER_SCAN: dict[str, int] = {
    "a": 0x1E,
    "b": 0x30,
    "c": 0x2E,
    "d": 0x20,
    "e": 0x12,
    "f": 0x21,
    "g": 0x22,
    "h": 0x23,
    "i": 0x17,
    "j": 0x24,
    "k": 0x25,
    "l": 0x26,
    "m": 0x32,
    "n": 0x31,
    "o": 0x18,
    "p": 0x19,
    "q": 0x10,
    "r": 0x13,
    "s": 0x1F,
    "t": 0x14,
    "u": 0x16,
    "v": 0x2F,
    "w": 0x11,
    "x": 0x2D,
    "y": 0x15,
    "z": 0x2C,
}

_EXTENDED_SCAN: dict[str, int] = {
    "insert": 0x52,
    "ins": 0x52,
    "delete": 0x53,
    "del": 0x53,
}


def _send_scancode(scan: int, *, key_up: bool, extended: bool = False) -> None:
    import ctypes
    from ctypes import wintypes

    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_SCANCODE = 0x0008
    PUL = ctypes.POINTER(ctypes.c_ulong)

    class KeyBdInput(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", PUL),
        ]

    class Input_I(ctypes.Union):
        _fields_ = [("ki", KeyBdInput)]

    class Input(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("ii", Input_I)]

    flags = KEYEVENTF_SCANCODE
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    if key_up:
        flags |= KEYEVENTF_KEYUP
    extra = ctypes.c_ulong(0)
    ii = Input_I()
    ii.ki = KeyBdInput(0, scan, flags, 0, ctypes.pointer(extra))
    inp = Input(1, ii)
    ctypes.windll.user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp))


def _press_scancode(scan: int, *, extended: bool = False) -> None:
    _send_scancode(scan, key_up=False, extended=extended)
    _send_scancode(scan, key_up=True, extended=extended)


def _press_fkey_sendinput(key: str) -> None:
    f_index = int(key[1:])
    if f_index < 1 or f_index > 12:
        raise UiNavError(f"unsupported function key: {key}")
    scan = 0x3B + (f_index - 1)
    _press_scancode(scan)


def _press_key_body(name: str) -> None:
    if name in _F_KEYS:
        _press_fkey_sendinput(name)
        return

    ext = _EXTENDED_SCAN.get(name)
    if ext is not None:
        _press_scancode(ext, extended=True)
        return

    if len(name) == 1:
        scan = _LETTER_SCAN.get(name)
        if scan is not None:
            _press_scancode(scan)
            return

    try:
        import pydirectinput

        pydirectinput.PAUSE = 0
        pydirectinput.FAILSAFE = False
        pydirectinput.press(name)
        return
    except ImportError:
        pass

    from modules.ui_nav.actions import press_key

    # press_key needs hwnd — caller must focus first; use VkKeyScan fallback only.
    raise UiNavError(f"unsupported bind key for scancode path: {name}")


def press_game_bind(hwnd: int, key: str, *, focus: bool = True) -> None:
    """Focus CS2 and press a bind key (F5, o, …) via hardware scancode."""
    if sys.platform != "win32":
        raise UiNavPlatformError("press_game_bind is Windows-only")

    name = key.lower().strip()
    if not name:
        raise UiNavError("empty bind key")

    if focus:
        focus_window(hwnd)

    _press_key_body(name)
    time.sleep(0.06)


def press_game_bind_no_focus(key: str) -> None:
    """Press bind key without refocusing (batch buy bursts)."""
    if sys.platform != "win32":
        raise UiNavPlatformError("press_game_bind is Windows-only")
    name = key.lower().strip()
    if not name:
        raise UiNavError("empty bind key")
    _press_key_body(name)
    time.sleep(0.06)
