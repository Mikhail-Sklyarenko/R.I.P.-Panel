"""Скриншот client area CS2."""

from __future__ import annotations

import sys
import time

from PIL import Image

from modules.ui_nav.errors import UiNavError, UiNavPlatformError


def is_suspect_black_capture(img: Image.Image, *, luminance_threshold: int = 8) -> bool:
    """True when client grab looks empty (all-near-black), not a probe calibration miss."""
    if img.width <= 0 or img.height <= 0:
        return True
    samples = [
        (0, 0),
        (img.width // 2, img.height // 2),
        (max(0, img.width - 1), max(0, img.height - 1)),
    ]
    for x, y in samples:
        r, g, b = img.getpixel((x, y))[:3]
        if r + g + b > luminance_threshold:
            return False
    return True


def capture_client(
    hwnd: int,
    *,
    on_progress=None,
    skip_focus: bool = False,
) -> Image.Image:
    if sys.platform != "win32":
        raise UiNavPlatformError("capture is Windows-only")
    import win32gui
    from PIL import ImageGrab

    from modules.ui_nav.window import is_valid_hwnd

    if not is_valid_hwnd(hwnd):
        raise UiNavPlatformError(f"capture: invalid window handle {hwnd}")

    if not skip_focus:
        from modules.ui_nav.actions import focus_window

        try:
            focus_window(hwnd)
        except UiNavError as exc:
            if on_progress:
                on_progress(f"capture: focus_window failed ({exc}); grab without focus")
        except Exception as exc:
            msg = f"capture: focus_window failed: {exc}"
            if on_progress:
                on_progress(f"{msg}; grab without focus")
        else:
            time.sleep(0.1)
            try:
                if win32gui.GetForegroundWindow() != hwnd and on_progress:
                    on_progress(f"capture: focus not acquired (hwnd={hwnd})")
            except Exception:
                pass
    elif on_progress:
        on_progress("capture: skip_focus=True")

    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    w, h = right - left, bottom - top
    sx, sy = win32gui.ClientToScreen(hwnd, (0, 0))
    return ImageGrab.grab(bbox=(sx, sy, sx + w, sy + h))


def capture_client_with_black_retry(
    hwnd: int,
    *,
    on_progress=None,
    artifacts=None,
    attempt: int | None = None,
) -> Image.Image:
    """Capture once; if suspect-black, refocus and grab again (same poll attempt)."""
    try:
        img = capture_client(hwnd, on_progress=on_progress)
    except UiNavError:
        img = capture_client(hwnd, on_progress=on_progress, skip_focus=True)
    if not is_suspect_black_capture(img):
        return img
    if artifacts is not None:
        artifacts.log_step(
            "capture_suspect_black",
            attempt=attempt or 0,
            detail="retry focus",
        )
    if on_progress:
        on_progress("capture: suspect black frame; refocusing")
    time.sleep(0.2)
    try:
        img2 = capture_client(hwnd, on_progress=on_progress)
    except UiNavError:
        img2 = capture_client(hwnd, on_progress=on_progress, skip_focus=True)
    if is_suspect_black_capture(img2) and on_progress:
        on_progress("capture: still black after refocus retry")
    return img2
