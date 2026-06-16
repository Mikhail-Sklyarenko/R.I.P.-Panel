"""CS2-compatible key press (focus CS2 hwnd + VK / DirectInput)."""

from __future__ import annotations

import ctypes
import logging
import os
from ctypes import wintypes
from typing import Callable

logger = logging.getLogger("DetectionProcess")

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

_VK_BY_KEY: dict[str, int] = {
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
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


def _press_vk(vk: int) -> None:
    import win32api
    import win32con

    win32api.keybd_event(vk, 0, 0, 0)
    win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)


def resolve_cs2_hwnd() -> int | None:
    raw = os.environ.get("CSGOBOT_CS2_HWND", "").strip()
    if raw:
        try:
            hwnd = int(raw)
            if hwnd > 0:
                return hwnd
        except ValueError:
            pass
    title = os.environ.get("CSGOBOT_WINDOW_TITLE", "").strip() or "Counter-Strike 2"
    from utils.win32 import find_window

    found = find_window(title)
    return found if found else None


def make_game_key_press(*, focus_before_press: bool = True) -> Callable[[str], None]:
    import pydirectinput

    from utils.win32 import focus_window_hwnd

    pydirectinput.PAUSE = 0
    pydirectinput.FAILSAFE = False
    hwnd = resolve_cs2_hwnd()
    focus_warned = False

    if hwnd:
        logger.info("autobuy: cs2 hwnd=%s focus=%s", hwnd, focus_before_press)
    else:
        logger.warning("autobuy: CS2 hwnd not set — keys may miss (set CSGOBOT_CS2_HWND)")

    def press(key: str) -> None:
        nonlocal focus_warned
        name = key.lower().strip()

        if focus_before_press and hwnd:
            if not focus_window_hwnd(hwnd):
                if not focus_warned:
                    logger.warning("autobuy: failed to focus CS2 hwnd=%s", hwnd)
                    focus_warned = True

        vk = _VK_BY_KEY.get(name)
        if vk is not None:
            pydirectinput.press(name)
            return

        scan = _EXTENDED_SCAN.get(name)
        if scan is not None:
            press_extended(scan)
            return

        pydirectinput.press(name)

    return press
