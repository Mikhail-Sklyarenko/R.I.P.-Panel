"""DM startup rifle buy — press p a few times after team select + fixed delay."""

from __future__ import annotations

import sys
import time
from typing import Callable

from modules.ui_nav.errors import UiNavError
from modules.ui_nav.game_keys import press_game_bind

_BUY_KEY = "p"
_DEFAULT_SPAWN_BUY_DELAY_SEC = 10.0
_DEFAULT_SPAWN_BUY_PRESSES = 3
_DEFAULT_SPAWN_BUY_INTERVAL_SEC = 0.35


def press_spawn_buy(hwnd: int, *, focus: bool = True) -> None:
    """Single buy bind press (buy_rifle_dm on p)."""
    press_game_bind(hwnd, _BUY_KEY, focus=focus)


def run_simple_startup_autobuy(
    hwnd: int | None,
    team_done_mono: float,
    *,
    delay_sec: float = _DEFAULT_SPAWN_BUY_DELAY_SEC,
    presses: int = _DEFAULT_SPAWN_BUY_PRESSES,
    interval_sec: float = _DEFAULT_SPAWN_BUY_INTERVAL_SEC,
    before_press: Callable[[], None] | None = None,
    on_progress: Callable[[str], None] | None = None,
    log_step: Callable[..., None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    """
    After team select: wait fixed delay for spawn, then press p N times.

    No image probes — timing only.
    """
    if hwnd is None or sys.platform != "win32":
        return False

    wait = max(0.0, delay_sec - (time.monotonic() - team_done_mono))
    if on_progress:
        on_progress(f"dm nav: autobuy wait {wait:.1f}s after team select")

    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if should_stop and should_stop():
            return False
        time.sleep(0.1)

    if before_press:
        before_press()

    sent = False
    count = max(1, int(presses))
    for i in range(count):
        if should_stop and should_stop():
            break
        if on_progress:
            on_progress(f"dm nav: autobuy p ({i + 1}/{count})")
        try:
            press_spawn_buy(hwnd, focus=True)
            sent = True
            if log_step:
                log_step("dm_autobuy_simple_p", attempt=i + 1, total=count)
        except UiNavError as exc:
            if on_progress:
                on_progress(f"dm nav: autobuy p failed ({exc})")
            break
        if i + 1 < count:
            time.sleep(max(0.05, interval_sec))

    if sent and on_progress:
        on_progress("dm nav: autobuy startup done")
    return sent
