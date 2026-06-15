"""CS2-compatible key press (pydirectinput + extended-key fix for Insert/Home/...)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable

# pydirectinput maps these with a +1024 marker but never sets KEYEVENTF_EXTENDEDKEY.
_EXTENDED_SCAN: dict[str, int] = {
    "insert": 0x52,
    "ins": 0x52,
    "delete": 0x53,
    "del": 0x53,
    "home": 0x47,
    "end": 0x4F,
    "pageup": 0x49,
    "pgup": 0x49,
    "pagedown": 0x51,
    "pgdn": 0x51,
}

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


def _send_scancode(scan: int, *, key_up: bool, extended: bool) -> None:
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


def press_extended(scan: int) -> None:
    _send_scancode(scan, key_up=False, extended=True)
    _send_scancode(scan, key_up=True, extended=True)


def make_game_key_press() -> Callable[[str], None]:
    import pydirectinput

    pydirectinput.PAUSE = 0
    pydirectinput.FAILSAFE = False

    def press(key: str) -> None:
        name = key.lower().strip()
        scan = _EXTENDED_SCAN.get(name)
        if scan is not None:
            press_extended(scan)
            return
        pydirectinput.press(name)

    return press
