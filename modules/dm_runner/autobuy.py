"""DM startup rifle buy — schedule from team join (invuln window), not after in_dm wait."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Callable

from modules.ui_nav.errors import UiNavError
from modules.ui_nav.game_keys import press_game_bind

# User-confirmed working bind on farm PC; fire first for lowest latency.
_BUY_KEYS = ("p", "f5", "o")

# Seconds after spawn detect — first burst at 0s (invuln is short).
_DEFAULT_BUY_OFFSETS_SEC = (0.0, 0.15, 0.35, 0.6, 1.0, 1.5, 2.5, 4.0, 6.0)
_DEFAULT_BUY_WINDOW_SEC = 10.0
_EARLY_BUY_AFTER_TEAM_SEC = 2.0
_EARLY_BUY_INTERVAL_SEC = 0.35
_EARLY_BUY_MAX_SEC = 28.0


def parse_buy_offsets(raw: str | None, default: tuple[float, ...] = _DEFAULT_BUY_OFFSETS_SEC) -> tuple[float, ...]:
    if not raw or not str(raw).strip():
        return default
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    if not parts:
        return default
    return tuple(max(0.0, float(part)) for part in parts)


def press_spawn_buy(hwnd: int, *, focus: bool = True) -> None:
    """Single fast buy burst — prefer bind p (buy_rifle_dm)."""
    press_game_bind(hwnd, _BUY_KEYS[0], focus=focus)


@dataclass
class SpawnAutobuyScheduler:
    """Fire buy binds at offsets from team-random click (DM invuln window)."""

    spawn_mono: float
    offsets_sec: tuple[float, ...] = _DEFAULT_BUY_OFFSETS_SEC
    buy_keys: tuple[str, ...] = _BUY_KEYS
    _next_index: int = 0
    sent: bool = False
    _logged_start: bool = field(default=False, repr=False)

    def tick(
        self,
        hwnd: int | None,
        *,
        on_progress: Callable[[str], None] | None = None,
        log_step: Callable[..., None] | None = None,
    ) -> None:
        if hwnd is None or sys.platform != "win32":
            return
        if not self._logged_start and on_progress:
            on_progress(
                "dm nav: autobuy armed on spawn HUD "
                f"({','.join(f'{o:.1f}s' for o in self.offsets_sec)})"
            )
            self._logged_start = True

        elapsed = time.monotonic() - self.spawn_mono
        while self._next_index < len(self.offsets_sec):
            if elapsed + 0.05 < self.offsets_sec[self._next_index]:
                break
            offset = self.offsets_sec[self._next_index]
            self._fire_burst(hwnd, offset=offset, on_progress=on_progress, log_step=log_step)
            self._next_index += 1

    def finish(
        self,
        hwnd: int | None,
        *,
        on_progress: Callable[[str], None] | None = None,
        log_step: Callable[..., None] | None = None,
    ) -> bool:
        """Flush any missed buy slots (e.g. before combat AI starts)."""
        self.tick(hwnd, on_progress=on_progress, log_step=log_step)
        while self._next_index < len(self.offsets_sec):
            offset = self.offsets_sec[self._next_index]
            if hwnd is not None and sys.platform == "win32":
                self._fire_burst(
                    hwnd, offset=offset, on_progress=on_progress, log_step=log_step
                )
            self._next_index += 1
        if self.sent and on_progress:
            on_progress("dm nav: autobuy startup done")
        return self.sent

    def _fire_burst(
        self,
        hwnd: int,
        *,
        offset: float,
        on_progress: Callable[[str], None] | None,
        log_step: Callable[..., None] | None,
    ) -> None:
        if on_progress:
            on_progress(f"dm nav: autobuy @+{offset:.1f}s from spawn")
        try:
            from modules.ui_nav.actions import focus_window

            focus_window(hwnd)
        except UiNavError:
            pass
        for key in self.buy_keys:
            try:
                press_game_bind(hwnd, key, focus=False)
                self.sent = True
            except UiNavError as exc:
                if on_progress:
                    on_progress(f"dm nav: autobuy {key} failed ({exc})")
                if log_step:
                    log_step("dm_autobuy_key_failed", key=key, err=str(exc))
                return
        if log_step:
            log_step("dm_autobuy_burst", offset_sec=offset, keys=list(self.buy_keys))


def hold_buy_window(
    hwnd: int | None,
    scheduler: SpawnAutobuyScheduler | None,
    *,
    window_sec: float = _DEFAULT_BUY_WINDOW_SEC,
    on_progress: Callable[[str], None] | None = None,
    log_step: Callable[..., None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[SpawnAutobuyScheduler, bool]:
    """
    Stand still and fire scheduled buys until window ends (before combat AI).

    Returns (scheduler, sent_any).
    """
    sched = scheduler or SpawnAutobuyScheduler(spawn_mono=time.monotonic())
    if hwnd is None or sys.platform != "win32":
        return sched, False

    window = max(0.5, window_sec)
    deadline = sched.spawn_mono + window
    if on_progress:
        on_progress(f"dm nav: buy window {window:.0f}s from spawn (stand still)")

    while time.monotonic() < deadline:
        if should_stop and should_stop():
            break
        sched.tick(hwnd, on_progress=on_progress, log_step=log_step)
        time.sleep(0.1)

    sent = sched.finish(hwnd, on_progress=on_progress, log_step=log_step)
    return sched, sent


def run_startup_autobuy(
    hwnd: int | None,
    *,
    spawn_wait_sec: float = 0.0,
    buy_delays_sec: tuple[float, ...] = _DEFAULT_BUY_OFFSETS_SEC,
    buy_keys: tuple[str, ...] = _BUY_KEYS,
    on_progress: Callable[[str], None] | None = None,
    log_step: Callable[..., None] | None = None,
) -> bool:
    """Legacy one-shot helper (tests); prefer SpawnAutobuyScheduler from team join."""
    if hwnd is None or sys.platform != "win32":
        return False

    if spawn_wait_sec > 0:
        if on_progress:
            on_progress(f"dm nav: autobuy wait {spawn_wait_sec:.0f}s")
        time.sleep(spawn_wait_sec)

    sched = SpawnAutobuyScheduler(
        spawn_mono=time.monotonic() - (buy_delays_sec[0] if buy_delays_sec else 0.0),
        offsets_sec=buy_delays_sec,
        buy_keys=buy_keys,
    )
    return sched.finish(hwnd, on_progress=on_progress, log_step=log_step)
