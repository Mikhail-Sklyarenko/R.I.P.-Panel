"""DM startup rifle buy — panel hwnd, spawn wait, DirectInput keys."""

from __future__ import annotations

import sys
import time
from typing import Callable

from modules.ui_nav.errors import UiNavError
from modules.ui_nav.game_keys import press_game_bind

# Keys bound to buy_rifle_dm in resources/cs2/fsm.cfg (F5 + letter fallback).
_BUY_KEYS = ("f5", "o")

# After in_dm: wait for spawn + DM buy invuln, then stagger F5/o presses.
_DEFAULT_SPAWN_WAIT_SEC = 10.0
_DEFAULT_BUY_DELAYS_SEC = (0.0, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0)


def run_startup_autobuy(
    hwnd: int | None,
    *,
    spawn_wait_sec: float = _DEFAULT_SPAWN_WAIT_SEC,
    buy_delays_sec: tuple[float, ...] = _DEFAULT_BUY_DELAYS_SEC,
    buy_keys: tuple[str, ...] = _BUY_KEYS,
    on_progress: Callable[[str], None] | None = None,
    log_step: Callable[..., None] | None = None,
) -> bool:
    """
    Buy AK/M4 + armor at DM spawn. Must not move (WASD closes buy window).

    Returns True if at least one key burst was sent.
    """
    if hwnd is None or sys.platform != "win32":
        return False

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    wait = max(0.0, spawn_wait_sec)
    if wait:
        progress(f"dm nav: autobuy wait {wait:.0f}s for spawn buy window")
        time.sleep(wait)

    sent = False
    last_at = 0.0
    for delay in buy_delays_sec:
        pause = max(0.0, delay - last_at)
        if pause:
            time.sleep(pause)
        last_at = delay
        for key in buy_keys:
            try:
                press_game_bind(hwnd, key)
                sent = True
            except UiNavError as exc:
                progress(f"dm nav: autobuy {key} failed ({exc})")
                if log_step:
                    log_step("dm_autobuy_key_failed", key=key, err=str(exc))
                return sent

    if sent:
        progress("dm nav: autobuy startup done")
        if log_step:
            log_step("dm_autobuy_startup", keys=list(buy_keys), delays=list(buy_delays_sec))
    return sent
