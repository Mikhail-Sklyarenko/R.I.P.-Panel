"""Скриншот client area CS2."""

from __future__ import annotations

import sys

from PIL import Image

from modules.ui_nav.errors import UiNavPlatformError


def capture_client(hwnd: int) -> Image.Image:
    if sys.platform != "win32":
        raise UiNavPlatformError("capture is Windows-only")
    import win32gui
    from PIL import ImageGrab

    from modules.ui_nav.window import is_valid_hwnd

    if not is_valid_hwnd(hwnd):
        raise UiNavPlatformError(f"capture: invalid window handle {hwnd}")

    win32gui.SetForegroundWindow(hwnd)
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    w, h = right - left, bottom - top
    sx, sy = win32gui.ClientToScreen(hwnd, (0, 0))
    return ImageGrab.grab(bbox=(sx, sy, sx + w, sy + h))
