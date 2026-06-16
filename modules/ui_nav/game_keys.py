"""Game-compatible key press for CS2 (DirectInput / SendInput, not plain keybd_event)."""

from __future__ import annotations

import sys
import time

from modules.ui_nav.actions import focus_window
from modules.ui_nav.errors import UiNavError, UiNavPlatformError

_F_KEYS = frozenset({f"f{i}" for i in range(1, 13)})


def press_game_bind(hwnd: int, key: str) -> None:
    """Focus CS2 and press a bind key (F5, o, …) so in-game binds fire."""
    if sys.platform != "win32":
        raise UiNavPlatformError("press_game_bind is Windows-only")

    name = key.lower().strip()
    if not name:
        raise UiNavError("empty bind key")

    focus_window(hwnd)

    try:
        import pydirectinput

        pydirectinput.PAUSE = 0
        pydirectinput.FAILSAFE = False
        pydirectinput.press(name)
        time.sleep(0.08)
        return
    except ImportError:
        pass

    if name in _F_KEYS:
        _press_fkey_sendinput(name)
        time.sleep(0.08)
        return

    from modules.ui_nav.actions import press_key

    press_key(hwnd, name)


def _press_fkey_sendinput(key: str) -> None:
    import ctypes
    from ctypes import wintypes

    f_index = int(key[1:])
    if f_index < 1 or f_index > 12:
        raise UiNavError(f"unsupported function key: {key}")

    scan = 0x3B + (f_index - 1)
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

    def send(*, key_up: bool) -> None:
        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if key_up else 0)
        extra = ctypes.c_ulong(0)
        ii = Input_I()
        ii.ki = KeyBdInput(0, scan, flags, 0, ctypes.pointer(extra))
        inp = Input(1, ii)
        ctypes.windll.user32.SendInput(1, ctypes.pointer(inp), ctypes.sizeof(inp))

    send(key_up=False)
    send(key_up=True)
