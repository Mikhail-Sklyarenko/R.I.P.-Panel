"""Поиск окна CS2 (Windows)."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

from modules.ui_nav.errors import UiNavError, UiNavPlatformError

_CS2_TITLE_SUBSTRINGS = ("counter-strike 2", "counter-strike", "cs2")


@dataclass(frozen=True)
class MainMenuWaitResult:
    ok: bool
    timed_out: bool = False
    attempts: int = 0


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


def wait_for_cs2_hwnd(
    *,
    timeout_sec: float = 90.0,
    poll_sec: float = 0.5,
    on_progress: Callable[[str], None] | None = None,
) -> int:
    """Poll until CS2 top-level window appears (after Popen)."""
    _require_windows()
    deadline = time.monotonic() + timeout_sec
    last_log = 0.0
    if on_progress:
        on_progress("waiting for CS2 window…")
    while time.monotonic() < deadline:
        try:
            return find_cs2_hwnd()
        except UiNavError:
            pass
        now = time.monotonic()
        if on_progress and now - last_log >= 10.0:
            remaining = max(0, int(deadline - now))
            on_progress(f"waiting for CS2 window ({remaining}s left)")
            last_log = now
        time.sleep(poll_sec)
    raise UiNavError(f"CS2 window not found within {timeout_sec:.0f}s")


def wait_for_cs2_main_menu(
    hwnd: int,
    coords,
    *,
    timeout_sec: float = 120.0,
    poll_sec: float = 0.5,
    on_progress: Callable[[str], None] | None = None,
    artifacts=None,
    min_match: int | None = 1,
) -> MainMenuWaitResult:
    """Poll until main_menu probes match. Timeout returns timed_out (no exception)."""
    _require_windows()
    from modules.ui_nav.capture import capture_client
    from modules.ui_nav.detectors import ScreenState, detect_state

    deadline = time.monotonic() + timeout_sec
    last_log = 0.0
    attempt = 0
    last_img = None
    if on_progress:
        on_progress("waiting for CS2 main menu…")
    while time.monotonic() < deadline:
        attempt += 1
        img = capture_client(hwnd)
        last_img = img
        if artifacts is not None:
            artifacts.save_image(f"wait_main_menu_launch_{attempt}", img)
            probe_count = len(coords.probes("main_menu"))
            artifacts.log_step(
                "main_menu_probe",
                attempt=attempt,
                matched=int(detect_state(img, ScreenState.MAIN_MENU, coords, min_match=1)),
                required=min_match if min_match is not None else probe_count,
                img_w=img.width,
                img_h=img.height,
            )
        if detect_state(img, ScreenState.MAIN_MENU, coords, min_match=min_match):
            if artifacts is not None:
                artifacts.log_step("main_menu_detect_ok", attempt=attempt)
            return MainMenuWaitResult(ok=True, attempts=attempt)
        now = time.monotonic()
        if on_progress and now - last_log >= 10.0:
            remaining = max(0, int(deadline - now))
            on_progress(f"waiting for CS2 main menu ({remaining}s left)")
            last_log = now
        time.sleep(poll_sec)
    if artifacts is not None and last_img is not None:
        artifacts.save_image("wait_main_menu_launch_timeout", last_img)
        artifacts.log_step(
            "main_menu_detect_timeout",
            timeout_sec=timeout_sec,
            attempts=attempt,
        )
    return MainMenuWaitResult(ok=False, timed_out=True, attempts=attempt)


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
