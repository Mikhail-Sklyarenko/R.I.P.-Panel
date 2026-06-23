"""Unit tests for csgobot patrol look (PR-L1)."""

from __future__ import annotations

import random
import sys
from pathlib import Path

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"
if str(_CSGOBOT) not in sys.path:
    sys.path.insert(0, str(_CSGOBOT))

from config import CaptureRegion, FOVConfig, LookConfig  # noqa: E402
from aiming.fov_mouse import FOVMouseMovement  # noqa: E402
from look.easing import smoothstep, smootherstep  # noqa: E402
from look.look_controller import LookController  # noqa: E402


def _fov_mouse() -> FOVMouseMovement:
    return FOVMouseMovement(
        screen=CaptureRegion(width=1280, height=720),
        fov=FOVConfig(horizontal=106.26, vertical=73.74, x360=16364),
    )


def _ctrl(
    *,
    seed: int = 42,
    idle_min: float = 12.0,
    idle_max: float = 15.0,
    sweep_min: float = 0.45,
    sweep_max: float = 0.65,
) -> LookController:
    return LookController(
        config=LookConfig(
            enabled=True,
            yaw_deg_min=80.0,
            yaw_deg_max=90.0,
            sweep_sec_min=sweep_min,
            sweep_sec_max=sweep_max,
            idle_sec_min=idle_min,
            idle_sec_max=idle_max,
        ),
        fov_mouse=_fov_mouse(),
        rng=random.Random(seed),
    )


def _run_full_sweep(ctrl: LookController, start: float = 100.0) -> tuple[list[int], float]:
    """Skip idle by forcing schedule, then advance sweep to completion."""
    ctrl._idle_scheduled = True
    ctrl._idle_until = start
    dx_log: list[int] = []
    t = start
    for _ in range(500):
        dx, dy = ctrl.tick(now=t, active=True)
        assert dy == 0
        if dx:
            dx_log.append(dx)
        t += 1.0 / 120.0
        if ctrl._state.name == "IDLE" and t > start + 0.01 and dx_log:
            break
    return dx_log, t


def test_easing_endpoints() -> None:
    assert smoothstep(0.0) == 0.0
    assert smoothstep(1.0) == 1.0
    assert smootherstep(0.0) == 0.0
    assert smootherstep(1.0) == 1.0
    assert 0.0 < smoothstep(0.5) < 1.0


def test_idle_does_not_move_before_delay() -> None:
    ctrl = _ctrl(seed=1)
    for step in range(50):
        dx, dy = ctrl.tick(now=float(step) * 0.1, active=True)
        assert dx == 0 and dy == 0


def test_tick_inactive_returns_zero() -> None:
    ctrl = _ctrl(idle_min=0.0, idle_max=0.0)
    ctrl._idle_scheduled = True
    ctrl._idle_until = 0.0
    dx, dy = ctrl.tick(now=1.0, active=False)
    assert dx == 0 and dy == 0


def test_full_sweep_reaches_target_counts() -> None:
    ctrl = _ctrl(seed=7, sweep_min=0.5, sweep_max=0.5)
    fov = _fov_mouse()
    rng = random.Random(7)
    yaw = rng.uniform(80.0, 90.0)
    sign = rng.choice((-1, 1))
    expected = fov.angle_to_mouse(sign * yaw, 0.0)[0]

    dx_log, _ = _run_full_sweep(ctrl, start=0.0)
    assert abs(sum(dx_log) - expected) <= 1


def test_fractional_carry_converges_with_tiny_steps() -> None:
    ctrl = _ctrl(seed=3, sweep_min=0.4, sweep_max=0.4)
    ctrl._idle_scheduled = True
    ctrl._idle_until = 0.0
    ctrl.tick(now=0.0, active=True)

    total = ctrl._total_counts
    dx_log: list[int] = []
    t = 0.0
    while ctrl._state.name == "SWEEPING" and t < 2.0:
        dx, _ = ctrl.tick(now=t, active=True)
        if dx:
            dx_log.append(dx)
        t += 1.0 / 1000.0
    assert abs(sum(dx_log) - total) <= 1


def test_direction_alternates() -> None:
    ctrl = _ctrl(seed=99, idle_min=0.0, idle_max=0.0, sweep_min=0.3, sweep_max=0.3)
    signs: list[int] = []
    t = 0.0
    for _ in range(3):
        ctrl._idle_scheduled = True
        ctrl._idle_until = t
        ctrl.tick(now=t, active=True)
        signs.append(1 if ctrl._total_counts > 0 else -1)
        while ctrl._state.name == "SWEEPING":
            t += 1.0 / 120.0
            ctrl.tick(now=t, active=True)
        t += 13.0

    assert signs[0] != signs[1]
    assert signs[1] != signs[2]


def test_abort_mid_sweep_stops_motion_without_return() -> None:
    ctrl = _ctrl(seed=5, sweep_min=1.0, sweep_max=1.0)
    ctrl._idle_scheduled = True
    ctrl._idle_until = 0.0
    ctrl.tick(now=0.0, active=True)

    mid_dx = 0
    for i in range(20):
        dx, _ = ctrl.tick(now=i / 120.0, active=True)
        mid_dx += dx
    ctrl.abort(now=0.2)

    after: list[int] = []
    for i in range(30):
        dx, _ = ctrl.tick(now=0.5 + i / 120.0, active=True)
        after.append(dx)

    assert mid_dx != 0
    assert all(d == 0 for d in after[:5])


def test_yaw_and_idle_within_config_bounds() -> None:
    rng = random.Random(123)
    ctrl = LookController(
        config=LookConfig(
            enabled=True,
            yaw_deg_min=80.0,
            yaw_deg_max=90.0,
            sweep_sec_min=0.45,
            sweep_sec_max=0.65,
            idle_sec_min=12.0,
            idle_sec_max=15.0,
        ),
        fov_mouse=_fov_mouse(),
        rng=rng,
    )
    ctrl._schedule_idle(now=0.0)
    delay = ctrl._idle_until
    assert 12.0 <= delay <= 15.0

    ctrl._begin_sweep(now=delay)
    assert 80.0 <= ctrl._current_yaw_deg <= 90.0
    assert 0.45 <= ctrl._sweep_duration <= 0.65
