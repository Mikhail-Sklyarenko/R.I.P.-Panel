"""DM startup rifle buy — press p after in_dm (spawn), not during map load."""

from __future__ import annotations

import sys
import time
from typing import Callable

from modules.ui_nav.errors import UiNavError
from modules.ui_nav.game_keys import press_game_bind

_BUY_KEY = "p"
_DEFAULT_SPAWN_BUY_DELAY_SEC = 2.0
_DEFAULT_SPAWN_BUY_PRESSES = 3
_DEFAULT_SPAWN_BUY_INTERVAL_SEC = 0.35


def press_spawn_buy(hwnd: int, *, focus: bool = True) -> None:
    """Single buy bind press (buy_rifle_dm on p)."""
    press_game_bind(hwnd, _BUY_KEY, focus=focus)


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
    """
    After in_dm HUD detected: brief pause, exec cfg, press p N times.

    Must run when the player is alive on the map — not after team select.
    """
    if hwnd is None or sys.platform != "win32":
        return False

    wait = max(0.0, delay_sec)
    if on_progress:
        on_progress(f"dm nav: autobuy wait {wait:.1f}s after spawn HUD")

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
