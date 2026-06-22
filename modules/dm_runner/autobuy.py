"""DM startup rifle buy — CS2 console buy commands (keys unreliable on farm PC)."""

from __future__ import annotations

import sys
import time
from typing import Callable

from modules.ui_nav.coords import NavCoords
from modules.ui_nav.detectors import detect_probe_key
from modules.ui_nav.errors import UiNavError

_DEFAULT_CONSOLE_BUY_PRESSES = 5
_DEFAULT_CONSOLE_BUY_INTERVAL_SEC = 0.35


def run_console_autobuy(
    hwnd: int | None,
    *,
    attempt: int = 1,
    total: int = 1,
    on_progress: Callable[[str], None] | None = None,
    log_step: Callable[..., None] | None = None,
) -> bool:
    """Open CS2 console and run buy ak47; buy m4a1_silencer; …"""
    if hwnd is None or sys.platform != "win32":
        return False

    from modules.ui_nav.cs2_console import run_console_dm_rifle_buy

    if on_progress:
        on_progress(f"dm nav: autobuy console ({attempt}/{total})")
    try:
        run_console_dm_rifle_buy(hwnd)
        if log_step:
            log_step("dm_autobuy_console", attempt=attempt, total=total, cmd="buy_rifle_dm")
        return True
    except UiNavError as exc:
        if on_progress:
            on_progress(f"dm nav: autobuy console failed ({exc})")
        return False


def run_console_autobuy_burst(
    hwnd: int | None,
    *,
    presses: int = _DEFAULT_CONSOLE_BUY_PRESSES,
    interval_sec: float = _DEFAULT_CONSOLE_BUY_INTERVAL_SEC,
    on_progress: Callable[[str], None] | None = None,
    log_step: Callable[..., None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    """Run console buy N times with pauses."""
    if hwnd is None or sys.platform != "win32":
        return False

    count = max(1, int(presses))
    sent = False
    for i in range(count):
        if should_stop and should_stop():
            break
        if run_console_autobuy(
            hwnd,
            attempt=i + 1,
            total=count,
            on_progress=on_progress,
            log_step=log_step,
        ):
            sent = True
        if i + 1 < count:
            time.sleep(max(0.15, interval_sec))
    if sent and on_progress:
        on_progress("dm nav: autobuy startup done")
    return sent


def wait_spawn_console_autobuy(
    hwnd: int,
    driver,
    coords: NavCoords,
    *,
    timeout_sec: float = 25.0,
    presses: int = _DEFAULT_CONSOLE_BUY_PRESSES,
    interval_sec: float = _DEFAULT_CONSOLE_BUY_INTERVAL_SEC,
    on_progress: Callable[[str], None] | None = None,
    log_step: Callable[..., None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    """
    Retry console buy while spawn invuln panel visible, then until timeout.

    Complements the first console buy fired right after team-random click.
    """
    if sys.platform != "win32":
        return False

    deadline = time.monotonic() + max(1.0, timeout_sec)
    burst_count = 0
    target = max(1, int(presses))
    last_buy = 0.0

    while time.monotonic() < deadline:
        if should_stop and should_stop():
            return burst_count > 0
        img = driver.capture()
        invuln = detect_probe_key(img, coords, "spawn_invuln", min_match=2)
        now = time.monotonic()

        if invuln and burst_count < target and now - last_buy >= interval_sec:
            if burst_count == 0 and on_progress:
                on_progress("dm nav: invuln panel — console buy retry")
            burst_count += 1
            run_console_autobuy(
                hwnd,
                attempt=burst_count,
                total=target,
                on_progress=on_progress,
                log_step=log_step,
            )
            last_buy = now
            time.sleep(0.1)
            continue

        if burst_count >= target:
            if on_progress:
                on_progress("dm nav: autobuy startup done")
            return True

        time.sleep(0.15)

    if on_progress and burst_count == 0:
        on_progress(f"dm nav: spawn console buy timeout ({timeout_sec:.0f}s)")
    return burst_count > 0
