"""Patrol camera look: smooth yaw sweeps (PR-L1 / L1.1 / L1.2)."""

from __future__ import annotations

import logging
import random
import time
from enum import Enum, auto
from typing import TYPE_CHECKING, Callable, Optional

from .config_resolve import look_debug_enabled
from .easing import smootherstep

if TYPE_CHECKING:
    from aiming.fov_mouse import FOVMouseMovement
    from config import LookConfig

logger = logging.getLogger("CS2Bot.look")

ApplyMouseFn = Callable[[int, int], None]


class _State(Enum):
    IDLE = auto()
    SWEEPING = auto()


class LookController:
    """
    Smooth patrol yaw sweeps.

    L1.1 — wall-clock ``due_at`` survives combat abort (no full idle reset).
    L1.2 — capped mouse substeps + yaw-rate floor on duration so sweeps are
    not one huge ``move_relative`` per YOLO frame (jerky / frame smear).
    """

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
        self._due_at = 0.0
        self._due_scheduled = False
        self._sweep_start = 0.0
        self._sweep_duration = 0.0
        self._total_counts = 0
        self._applied_counts = 0
        self._swept_float = 0.0
        self._next_sign: Optional[int] = None
        self._current_yaw_deg = 0.0
        self._pending_finish = False

    @property
    def is_sweeping(self) -> bool:
        return self._state == _State.SWEEPING

    # --- test / legacy aliases -------------------------------------------------
    @property
    def _idle_until(self) -> float:
        return self._due_at

    @_idle_until.setter
    def _idle_until(self, value: float) -> None:
        self._due_at = float(value)

    @property
    def _idle_scheduled(self) -> bool:
        return self._due_scheduled

    @_idle_scheduled.setter
    def _idle_scheduled(self, value: bool) -> None:
        self._due_scheduled = bool(value)

    def abort(self, *, now: float | None = None) -> None:
        """Cancel in-flight sweep; preserve look cadence (do not full-reset idle)."""
        was_sweeping = self._state == _State.SWEEPING
        if was_sweeping:
            logger.info(
                "look: abort mid-sweep (yaw=%.1f°)",
                self._current_yaw_deg,
            )
            if now is not None:
                cooldown = max(0.0, float(self._config.abort_cooldown_sec))
                self._due_at = max(self._due_at, now + cooldown)
                self._due_scheduled = True
                if self._debug:
                    logger.info(
                        "look: abort cooldown %.2fs → due_in=%.2fs",
                        cooldown,
                        max(0.0, self._due_at - now),
                    )
        self._clear_sweep()
        self._state = _State.IDLE

    def tick(
        self,
        *,
        now: float,
        active: bool,
        apply_mouse: ApplyMouseFn | None = None,
    ) -> tuple[int, int]:
        """
        Advance look state.

        If ``apply_mouse`` is set, large deltas are split into capped substeps
        (with optional micro-sleep) before returning the total dx applied.
        """
        if not self._config.enabled:
            return (0, 0)

        if not active:
            if self._state == _State.SWEEPING:
                self.abort(now=now)
            return (0, 0)

        if self._state == _State.IDLE:
            raw_dx, _ = self._tick_idle(now)
        else:
            raw_dx, _ = self._tick_sweep(now)

        emitted = self._emit_mouse(raw_dx, apply_mouse)
        self._finish_if_needed(now)
        return emitted

    def _emit_mouse(
        self,
        dx: int,
        apply_mouse: ApplyMouseFn | None,
    ) -> tuple[int, int]:
        if dx == 0:
            return (0, 0)

        # Unit tests call tick() without apply_mouse — keep single-step math.
        if apply_mouse is None:
            return (dx, 0)

        max_delta = max(1, int(self._config.max_delta))
        max_sub = max(1, int(self._config.substeps_per_tick))
        sleep_s = max(0.0, float(self._config.substep_sleep_sec))

        remaining = abs(dx)
        sign = 1 if dx > 0 else -1
        applied = 0
        steps = 0

        while remaining > 0 and steps < max_sub:
            step = min(remaining, max_delta)
            piece = sign * step
            apply_mouse(piece, 0)
            if sleep_s > 0 and remaining - step > 0:
                time.sleep(sleep_s)
            applied += piece
            remaining -= step
            steps += 1

        # Carry unfinished easing target to next tick (avoid huge single jumps).
        if remaining > 0:
            rewind = sign * remaining
            self._applied_counts -= rewind
            self._swept_float = float(self._applied_counts)

        return (applied, 0)

    def _tick_idle(self, now: float) -> tuple[int, int]:
        if not self._due_scheduled:
            self._schedule_idle(now)

        if now < self._due_at:
            return (0, 0)

        self._begin_sweep(now)
        return self._tick_sweep(now)

    def _tick_sweep(self, now: float) -> tuple[int, int]:
        elapsed = now - self._sweep_start
        progress = (
            min(elapsed / self._sweep_duration, 1.0) if self._sweep_duration > 0 else 1.0
        )
        eased = smootherstep(progress)
        if progress >= 1.0:
            dx = self._total_counts - self._applied_counts
            self._applied_counts = self._total_counts
            self._swept_float = float(self._total_counts)
            self._pending_finish = True
        else:
            target_applied = int(round(self._total_counts * eased))
            dx = target_applied - self._applied_counts
            self._applied_counts = target_applied
            self._swept_float = float(self._applied_counts)
            self._pending_finish = False

        return (dx, 0)

    def _finish_if_needed(self, now: float) -> None:
        if not self._pending_finish:
            return
        if self._state != _State.SWEEPING:
            self._pending_finish = False
            return
        # Wait until capped emit has caught up to total.
        if self._applied_counts != self._total_counts:
            return

        yaw = self._current_yaw_deg
        counts = self._total_counts
        next_sign = self._next_sign or 0
        self._clear_sweep()
        self._state = _State.IDLE
        self._schedule_idle(now)
        logger.info(
            "look: sweep done yaw=%.1f° counts=%d next_sign=%+d next_in=%.1fs",
            yaw,
            counts,
            next_sign,
            max(0.0, self._due_at - now),
        )

    def _schedule_idle(self, now: float) -> None:
        delay = self._rng.uniform(
            self._config.idle_sec_min,
            self._config.idle_sec_max,
        )
        self._due_at = now + delay
        self._due_scheduled = True

    def _clear_sweep(self) -> None:
        self._swept_float = 0.0
        self._applied_counts = 0
        self._total_counts = 0
        self._sweep_duration = 0.0
        self._pending_finish = False

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

        dur = self._rng.uniform(
            self._config.sweep_sec_min,
            self._config.sweep_sec_max,
        )
        max_rate = float(self._config.max_yaw_deg_per_sec)
        if max_rate > 0:
            dur = max(dur, float(yaw_deg) / max_rate)
        self._sweep_duration = dur
        self._sweep_start = now
        self._swept_float = 0.0
        self._applied_counts = 0
        self._pending_finish = False
        self._state = _State.SWEEPING

        logger.info(
            "look: sweep start yaw=%.1f° sign=%+d counts=%d dur=%.2fs "
            "max_delta=%d substeps=%d",
            yaw_deg,
            sign,
            self._total_counts,
            self._sweep_duration,
            int(self._config.max_delta),
            int(self._config.substeps_per_tick),
        )
