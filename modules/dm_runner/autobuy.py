"""DM startup rifle buy — press buy binds at spawn (invuln window)."""

from __future__ import annotations

import sys
import time
from typing import Callable

from modules.ui_nav.coords import NavCoords
from modules.ui_nav.detectors import detect_probe_key
from modules.ui_nav.errors import UiNavError
from modules.ui_nav.game_keys import press_game_bind

# Farm PC confirmed: o works; p/f5 are aliases on buy_rifle_dm.
_BUY_KEYS = ("o", "p", "f5")
_DEFAULT_SPAWN_BUY_DELAY_SEC = 0.0
_DEFAULT_SPAWN_BUY_PRESSES = 3
_DEFAULT_SPAWN_BUY_INTERVAL_SEC = 0.25


def press_spawn_buy(hwnd: int, *, focus: bool = True) -> None:
    """Fire all buy binds once (buy_rifle_dm)."""
    for key in _BUY_KEYS:
        press_game_bind(hwnd, key, focus=focus)


def run_simple_startup_autobuy(
    hwnd: int | None,
    *,
    delay_sec: float = _DEFAULT_SPAWN_BUY_DELAY_SEC,
    presses: int = _DEFAULT_SPAWN_BUY_PRESSES,
    interval_sec: float = _DEFAULT_SPAWN_BUY_INTERVAL_SEC,
    before_press: Callable[[], None] | None = None,
    on_progress: Callable[[str], None] | None = None,
    log_step: Callable[..., None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    """Press o/p/f5 N times after spawn buy window opens."""
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

    if before_press:
        before_press()

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
                on_progress(f"dm nav: autobuy failed ({exc})")
            break
        if i + 1 < count:
            time.sleep(max(0.05, interval_sec))

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
    before_press: Callable[[], None] | None = None,
    on_progress: Callable[[str], None] | None = None,
    log_step: Callable[..., None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    """
    Poll for НЕУЯЗВИМОСТЬ panel; fire buy binds immediately on first sight.

    Keeps bursting while the panel stays visible (invuln window is short).
    """
    if sys.platform != "win32":
        return False

    deadline = time.monotonic() + max(1.0, timeout_sec)
    cfg_loaded = False
    burst_count = 0
    target_bursts = max(1, int(presses))

    while time.monotonic() < deadline:
        if should_stop and should_stop():
            return False
        img = driver.capture()
        if detect_probe_key(img, coords, "spawn_invuln", min_match=2):
            if not cfg_loaded and before_press:
                before_press()
                cfg_loaded = True
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
                        on_progress(f"dm nav: autobuy failed ({exc})")
                    return burst_count > 0
                time.sleep(max(0.05, interval_sec))
            else:
                time.sleep(0.15)
            continue

        if burst_count > 0:
            if on_progress:
                on_progress("dm nav: autobuy startup done")
            return True

        time.sleep(0.15)

    if on_progress:
        on_progress(f"dm nav: timeout waiting for invuln buy panel ({timeout_sec:.0f}s)")
    return burst_count > 0
