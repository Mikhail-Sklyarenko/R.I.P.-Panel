"""DM startup rifle buy — press buy binds at spawn (invuln window)."""

from __future__ import annotations

import sys
import time
from typing import Callable

from modules.ui_nav.actions import focus_window
from modules.ui_nav.coords import NavCoords
from modules.ui_nav.detectors import detect_probe_key
from modules.ui_nav.errors import UiNavError
from modules.ui_nav.game_keys import press_game_bind_no_focus

# Farm PC confirmed: o works; p/f5 are aliases on buy_rifle_dm.
_BUY_KEYS = ("o", "p", "f5")
_DEFAULT_SPAWN_BUY_PRESSES = 3
_DEFAULT_SPAWN_BUY_INTERVAL_SEC = 0.25


def press_spawn_buy(hwnd: int, *, focus: bool = True) -> None:
    """Fire all buy binds once — focus CS2 once, then scancode keys."""
    if focus:
        focus_window(hwnd)
    for key in _BUY_KEYS:
        press_game_bind_no_focus(key)


def _console_buy_fallback(
    hwnd: int,
    *,
    on_progress: Callable[[str], None] | None = None,
    log_step: Callable[..., None] | None = None,
) -> bool:
    from modules.ui_nav.cs2_console import run_console_dm_rifle_buy

    if on_progress:
        on_progress("dm nav: autobuy console fallback (buy commands)")
    try:
        run_console_dm_rifle_buy(hwnd)
        if log_step:
            log_step("dm_autobuy_console", cmd="buy_rifle_dm")
        return True
    except UiNavError as exc:
        if on_progress:
            on_progress(f"dm nav: autobuy console failed ({exc})")
        return False


def run_simple_startup_autobuy(
    hwnd: int | None,
    *,
    delay_sec: float = 0.0,
    presses: int = _DEFAULT_SPAWN_BUY_PRESSES,
    interval_sec: float = _DEFAULT_SPAWN_BUY_INTERVAL_SEC,
    console_fallback: bool = True,
    on_progress: Callable[[str], None] | None = None,
    log_step: Callable[..., None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    """Press o/p/f5 N times; optional console buy fallback."""
    if hwnd is None or sys.platform != "win32":
        return False

    wait = max(0.0, delay_sec)
    if wait > 0.05 and on_progress:
        on_progress(f"dm nav: autobuy wait {wait:.1f}s after spawn HUD")

    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if should_stop and should_stop():
            return False
        time.sleep(0.05)

    sent = False
    count = max(1, int(presses))
    for i in range(count):
        if should_stop and should_stop():
            break
        if on_progress:
            on_progress(f"dm nav: autobuy o ({i + 1}/{count})")
        try:
            press_spawn_buy(hwnd, focus=True)
            sent = True
            if log_step:
                log_step("dm_autobuy_burst", attempt=i + 1, total=count, keys=list(_BUY_KEYS))
        except UiNavError as exc:
            if on_progress:
                on_progress(f"dm nav: autobuy keys failed ({exc})")
            break
        if i + 1 < count:
            time.sleep(max(0.05, interval_sec))

    if console_fallback:
        _console_buy_fallback(hwnd, on_progress=on_progress, log_step=log_step)
        sent = True

    if sent and on_progress:
        on_progress("dm nav: autobuy startup done")
    return sent


def wait_invuln_and_autobuy(
    hwnd: int,
    driver,
    coords: NavCoords,
    *,
    timeout_sec: float = 25.0,
    presses: int = 3,
    interval_sec: float = 0.25,
    console_fallback: bool = True,
    on_progress: Callable[[str], None] | None = None,
    log_step: Callable[..., None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    """
    Poll for НЕУЯЗВИМОСТЬ panel; fire buy binds immediately on first sight.

    Does not open console for exec cfg — binds are loaded at game launch.
    """
    if sys.platform != "win32":
        return False

    deadline = time.monotonic() + max(1.0, timeout_sec)
    burst_count = 0
    console_done = False
    target_bursts = max(1, int(presses))

    while time.monotonic() < deadline:
        if should_stop and should_stop():
            return False
        img = driver.capture()
        if detect_probe_key(img, coords, "spawn_invuln", min_match=2):
            if burst_count == 0 and on_progress:
                on_progress("dm nav: invuln buy panel visible — buying now")
            if burst_count < target_bursts:
                burst_count += 1
                if on_progress:
                    on_progress(f"dm nav: autobuy o ({burst_count}/{target_bursts})")
                try:
                    press_spawn_buy(hwnd, focus=True)
                    if log_step:
                        log_step(
                            "dm_autobuy_invuln_burst",
                            attempt=burst_count,
                            total=target_bursts,
                            keys=list(_BUY_KEYS),
                        )
                except UiNavError as exc:
                    if on_progress:
                        on_progress(f"dm nav: autobuy keys failed ({exc})")
                time.sleep(max(0.05, interval_sec))
            elif console_fallback and not console_done:
                console_done = _console_buy_fallback(
                    hwnd, on_progress=on_progress, log_step=log_step
                )
                time.sleep(0.15)
            else:
                time.sleep(0.15)
            continue

        if burst_count > 0 or console_done:
            if on_progress:
                on_progress("dm nav: autobuy startup done")
            return True

        time.sleep(0.15)

    if on_progress:
        on_progress(f"dm nav: timeout waiting for invuln buy panel ({timeout_sec:.0f}s)")
    return burst_count > 0 or console_done
