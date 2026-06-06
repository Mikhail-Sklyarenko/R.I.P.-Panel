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
    """strict_ok: both main_menu probes matched (ИГРАТЬ tab, not Loadout)."""

    strict_ok: bool
    timed_out: bool = False
    attempts: int = 0
    soft_peek: bool = False

    @property
    def ok(self) -> bool:
        return self.strict_ok


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
    min_match: int | None = None,
    require_strict: bool = True,
) -> MainMenuWaitResult:
    """Poll until main_menu probes match. Timeout returns timed_out (no exception)."""
    _require_windows()
    from modules.ui_nav.capture import capture_client_with_black_retry
    from modules.ui_nav.detectors import ScreenState, detect_state, probe_match_results

    probe_count = len(coords.probes("main_menu"))
    strict_required = probe_count if probe_count else 1
    soft_required = min_match if min_match is not None else 1
    deadline = time.monotonic() + timeout_sec
    last_log = 0.0
    attempt = 0
    last_img = None
    last_probe_results = []
    soft_peek = False
    if on_progress:
        on_progress("waiting for CS2 main menu…")
    while time.monotonic() < deadline:
        attempt += 1
        img = capture_client_with_black_retry(
            hwnd,
            on_progress=on_progress,
            artifacts=artifacts,
            attempt=attempt,
        )
        last_img = img
        probe_results = probe_match_results(img, ScreenState.MAIN_MENU, coords)
        last_probe_results = probe_results
        soft_hit = sum(1 for r in probe_results if r.matched) >= 1
        soft_peek = soft_peek or soft_hit
        strict = detect_state(
            img,
            ScreenState.MAIN_MENU,
            coords,
            min_match=strict_required,
        )
        if artifacts is not None:
            artifacts.save_image(f"wait_main_menu_launch_{attempt}", img)
            probe_kwargs: dict = {
                "attempt": attempt,
                "matched": int(soft_hit),
                "strict": int(strict),
                "img_w": img.width,
                "img_h": img.height,
            }
            for idx, result in enumerate(probe_results[:2]):
                probe_kwargs[f"p{idx}"] = int(result.matched)
                probe_kwargs[f"rgb{idx}"] = list(result.actual_rgb)
                probe_kwargs[f"exp{idx}"] = list(result.expected_rgb)
            artifacts.log_step("main_menu_probe", **probe_kwargs)
        if require_strict:
            if strict:
                if artifacts is not None:
                    artifacts.log_step(
                        "main_menu_detect_ok",
                        attempt=attempt,
                        strict=True,
                    )
                return MainMenuWaitResult(
                    strict_ok=True,
                    attempts=attempt,
                    soft_peek=soft_peek,
                )
        elif detect_state(
            img, ScreenState.MAIN_MENU, coords, min_match=soft_required
        ):
            if artifacts is not None:
                artifacts.log_step(
                    "main_menu_detect_ok",
                    attempt=attempt,
                    strict=strict,
                )
            return MainMenuWaitResult(
                strict_ok=strict,
                attempts=attempt,
                soft_peek=soft_peek or soft_hit,
            )
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
    if on_progress and last_probe_results:
        r0 = last_probe_results[0]
        p1 = int(last_probe_results[1].matched) if len(last_probe_results) > 1 else 0
        on_progress(
            "main_menu timeout: "
            f"p0={int(r0.matched)} p1={p1} "
            f"last@({r0.x},{r0.y})={list(r0.actual_rgb)} "
            f"expected={list(r0.expected_rgb)}"
        )
    return MainMenuWaitResult(
        strict_ok=False,
        timed_out=True,
        attempts=attempt,
        soft_peek=soft_peek,
    )


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
