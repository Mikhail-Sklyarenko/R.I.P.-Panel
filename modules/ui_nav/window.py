"""Поиск окна CS2 (Windows)."""

from __future__ import annotations

import sys

from modules.ui_nav.errors import UiNavError, UiNavPlatformError

_CS2_TITLE_SUBSTRINGS = ("counter-strike 2", "counter-strike", "cs2")


def _require_windows() -> None:
    if sys.platform != "win32":
        raise UiNavPlatformError("CS2 window API is Windows-only")


def find_cs2_hwnd() -> int:
    _require_windows()
    import win32gui

    found: list[int] = []

    def _enum(hwnd: int, _ctx) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = (win32gui.GetWindowText(hwnd) or "").lower()
        if any(sub in title for sub in _CS2_TITLE_SUBSTRINGS):
            found.append(hwnd)

    win32gui.EnumWindows(_enum, None)
    if not found:
        raise UiNavError("CS2 window not found")
    return found[0]


def is_valid_hwnd(hwnd: int) -> bool:
    """True if hwnd is a live top-level window (not closed)."""
    _require_windows()
    if not hwnd:
        return False
    import win32gui

    try:
        return bool(win32gui.IsWindow(hwnd))
    except Exception:
        return False


def is_invalid_hwnd_error(exc: BaseException) -> bool:
    """True for Win32 ERROR_INVALID_WINDOW_HANDLE (1400) and similar."""
    if getattr(exc, "winerror", None) == 1400:
        return True
    msg = str(exc).lower()
    return (
        "getclientrect" in msg
        or "invalid window handle" in msg
        or "window closed" in msg
        or "недопустимый дескриптор окна" in msg
    )


def client_size(hwnd: int) -> tuple[int, int]:
    _require_windows()
    import win32gui

    if not is_valid_hwnd(hwnd):
        raise UiNavError(f"invalid or closed window handle: {hwnd}")
    _left, top, right, bottom = win32gui.GetClientRect(hwnd)
    return right - _left, bottom - top
