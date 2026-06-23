"""Patrol camera look: single smooth yaw sweep, hold, alternate direction (PR-L1)."""

from __future__ import annotations

import logging
import random
from enum import Enum, auto
from typing import TYPE_CHECKING, Optional

from .config_resolve import look_debug_enabled
from .easing import smootherstep

if TYPE_CHECKING:
    from aiming.fov_mouse import FOVMouseMovement
    from config import LookConfig

logger = logging.getLogger("CS2Bot.look")


class _State(Enum):
    IDLE = auto()
    SWEEPING = auto()


class LookController:
    """Smooth patrol yaw sweeps; combat / unstuck must call abort() from main."""

    def __init__(
        self,
        *,
        config: LookConfig,
        fov_mouse: FOVMouseMovement,
        rng: Optional[random.Random] = None,
    ) -> None:
        self._config = config
        self._fov_mouse = fov_mouse
        self._rng = rng or random.Random()
        self._debug = look_debug_enabled()
        self._state = _State.IDLE
        self._idle_until = 0.0
        self._idle_scheduled = False
        self._sweep_start = 0.0
        self._sweep_duration = 0.0
        self._total_counts = 0
        self._applied_counts = 0
        self._swept_float = 0.0
        self._next_sign: Optional[int] = None
        self._current_yaw_deg = 0.0

    def abort(self, *, now: float | None = None) -> None:
        if self._state == _State.SWEEPING and self._debug:
            logger.info("look: abort mid-sweep (yaw=%.1f°)", self._current_yaw_deg)
        self._state = _State.IDLE
        self._swept_float = 0.0
        self._applied_counts = 0
        self._idle_scheduled = False
        if now is not None:
            self._schedule_idle(now)

    def tick(self, *, now: float, active: bool) -> tuple[int, int]:
        if not self._config.enabled or not active:
            return (0, 0)

        if self._state == _State.IDLE:
            return self._tick_idle(now)

        return self._tick_sweep(now)

    def _tick_idle(self, now: float) -> tuple[int, int]:
        if not self._idle_scheduled:
            self._schedule_idle(now)

        if now < self._idle_until:
            return (0, 0)

        self._begin_sweep(now)
        return self._tick_sweep(now)

    def _tick_sweep(self, now: float) -> tuple[int, int]:
        elapsed = now - self._sweep_start
        progress = min(elapsed / self._sweep_duration, 1.0) if self._sweep_duration > 0 else 1.0
        eased = smootherstep(progress)
        if progress >= 1.0:
            dx = self._total_counts - self._applied_counts
            self._applied_counts = self._total_counts
            self._swept_float = float(self._total_counts)
        else:
            target_applied = int(round(self._total_counts * eased))
            dx = target_applied - self._applied_counts
            self._applied_counts = target_applied
            self._swept_float = float(self._applied_counts)

        if progress >= 1.0:
            self._state = _State.IDLE
            self._swept_float = 0.0
            self._applied_counts = 0
            self._idle_scheduled = False
            if self._debug:
                logger.info(
                    "look: sweep done yaw=%.1f° counts=%d next_sign=%+d",
                    self._current_yaw_deg,
                    self._total_counts,
                    self._next_sign or 0,
                )

        return (dx, 0)

    def _schedule_idle(self, now: float) -> None:
        delay = self._rng.uniform(
            self._config.idle_sec_min,
            self._config.idle_sec_max,
        )
        self._idle_until = now + delay
        self._idle_scheduled = True

    def _begin_sweep(self, now: float) -> None:
        yaw_deg = self._rng.uniform(
            self._config.yaw_deg_min,
            self._config.yaw_deg_max,
        )
        if self._next_sign is None:
            sign = self._rng.choice((-1, 1))
        else:
            sign = self._next_sign
        self._next_sign = -sign

        self._current_yaw_deg = yaw_deg
        self._total_counts = self._fov_mouse.angle_to_mouse(sign * yaw_deg, 0.0)[0]
        self._sweep_duration = self._rng.uniform(
            self._config.sweep_sec_min,
            self._config.sweep_sec_max,
        )
        self._sweep_start = now
        self._swept_float = 0.0
        self._applied_counts = 0
        self._state = _State.SWEEPING

        if self._debug:
            logger.info(
                "look: sweep start yaw=%.1f° sign=%+d counts=%d dur=%.2fs",
                yaw_deg,
                sign,
                self._total_counts,
                self._sweep_duration,
            )
