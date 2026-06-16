"""DM startup rifle buy — schedule from team join (invuln window), not after in_dm wait."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Callable

from modules.ui_nav.errors import UiNavError
from modules.ui_nav.game_keys import press_game_bind

# Keys bound to buy_rifle_dm in resources/cs2/fsm.cfg (F5 + letter fallback).
_BUY_KEYS = ("f5", "o")

# Seconds after «Случайный выбор» while spawn invuln + buy menu is open (stand still).
_DEFAULT_BUY_OFFSETS_SEC = (3.0, 5.0, 7.0, 9.0, 11.0)


def parse_buy_offsets(raw: str | None, default: tuple[float, ...] = _DEFAULT_BUY_OFFSETS_SEC) -> tuple[float, ...]:
    if not raw or not str(raw).strip():
        return default
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    if not parts:
        return default
    return tuple(max(0.0, float(part)) for part in parts)


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
                "dm nav: autobuy armed from team join "
                f"({','.join(f'{o:.0f}s' for o in self.offsets_sec)})"
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
            on_progress(f"dm nav: autobuy @+{offset:.0f}s from team join")
        for key in self.buy_keys:
            try:
                press_game_bind(hwnd, key)
                self.sent = True
            except UiNavError as exc:
                if on_progress:
                    on_progress(f"dm nav: autobuy {key} failed ({exc})")
                if log_step:
                    log_step("dm_autobuy_key_failed", key=key, err=str(exc))
                return
        if log_step:
            log_step("dm_autobuy_burst", offset_sec=offset, keys=list(self.buy_keys))


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
