"""Human-like locomotion layer for minimap nav (PR-N4)."""

from __future__ import annotations

import random
from dataclasses import dataclass

from aiming.fov_mouse import FOVMouseMovement
from nav.goal_follower import compute_follow_plan
from nav.pack import HumanizeConfig, NavGoal
from nav.pose import PoseResult


@dataclass(frozen=True)
class HumanizedMotion:
    mouse_dx: int
    mouse_dy: int
    forward: bool
    paused: bool
    yaw_error_deg: float
    dist_to_goal: float
    micro_pause: bool = False
    forward_jitter: bool = False
    look_yield: bool = False


class NavHumanizer:
    """Stateful turn smoothing, pauses, forward jitter, look-yield."""

    def __init__(
        self,
        config: HumanizeConfig,
        *,
        rng: random.Random | None = None,
    ) -> None:
        self._cfg = config
        self._rng = rng or random.Random()
        self._smooth_turn_deg = 0.0
        self._wobble_bias = 0.0
        self._wobble_refresh_at = 0.0
        self._micro_pause_until = 0.0
        self._forward_jitter_until = 0.0

    def reset(self) -> None:
        self._smooth_turn_deg = 0.0
        self._wobble_bias = 0.0
        self._wobble_refresh_at = 0.0
        self._micro_pause_until = 0.0
        self._forward_jitter_until = 0.0

    def _refresh_wobble(self, now: float) -> None:
        if now >= self._wobble_refresh_at:
            span = self._cfg.path_wobble_deg
            self._wobble_bias = self._rng.uniform(-span, span)
            self._wobble_refresh_at = now + self._cfg.wobble_refresh_sec

    def _jittered_turn_rate(self) -> float:
        jitter = self._cfg.speed_jitter
        if jitter <= 0.0:
            return self._cfg.turn_rate_deg_per_sec
        scale = 1.0 + self._rng.uniform(-jitter, jitter)
        return max(30.0, self._cfg.turn_rate_deg_per_sec * scale)

    def compute(
        self,
        pose: PoseResult,
        goal: NavGoal,
        fov_mouse: FOVMouseMovement,
        *,
        dt_sec: float,
        now: float,
        look_sweeping: bool = False,
        allow_forward: bool = True,
    ) -> HumanizedMotion:
        if now < self._micro_pause_until:
            return HumanizedMotion(
                mouse_dx=0,
                mouse_dy=0,
                forward=False,
                paused=True,
                yaw_error_deg=0.0,
                dist_to_goal=0.0,
                micro_pause=True,
            )

        if (
            self._rng.random() < self._cfg.micro_pause_chance
            and now >= self._micro_pause_until
        ):
            pause = self._rng.uniform(
                self._cfg.micro_pause_sec_min,
                self._cfg.micro_pause_sec_max,
            )
            self._micro_pause_until = now + pause
            return HumanizedMotion(
                mouse_dx=0,
                mouse_dy=0,
                forward=False,
                paused=True,
                yaw_error_deg=0.0,
                dist_to_goal=0.0,
                micro_pause=True,
            )

        self._refresh_wobble(now)
        plan = compute_follow_plan(
            pose,
            goal,
            self._cfg,
            dt_sec=dt_sec,
            wobble_bias_deg=self._wobble_bias,
            allow_forward=allow_forward,
            turn_rate_deg_per_sec=self._jittered_turn_rate(),
        )

        alpha = self._cfg.turn_smooth_alpha
        self._smooth_turn_deg = (
            alpha * plan.turn_step_deg + (1.0 - alpha) * self._smooth_turn_deg
        )

        look_yield = look_sweeping and self._cfg.look_yield_turn
        if look_yield:
            mouse_dx, mouse_dy = 0, 0
        else:
            mouse_dx, mouse_dy = fov_mouse.angle_to_mouse(
                self._smooth_turn_deg,
                0.0,
            )

        forward = plan.forward
        forward_jitter = False
        if forward and now < self._forward_jitter_until:
            forward = False
            forward_jitter = True
        elif forward and self._rng.random() < self._cfg.forward_jitter_chance:
            jitter = self._rng.uniform(
                self._cfg.forward_jitter_sec_min,
                self._cfg.forward_jitter_sec_max,
            )
            self._forward_jitter_until = now + jitter
            forward = False
            forward_jitter = True

        return HumanizedMotion(
            mouse_dx=mouse_dx,
            mouse_dy=mouse_dy,
            forward=forward,
            paused=False,
            yaw_error_deg=plan.yaw_error_deg,
            dist_to_goal=plan.dist_to_goal,
            forward_jitter=forward_jitter,
            look_yield=look_yield,
        )
