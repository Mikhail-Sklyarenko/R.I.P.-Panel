"""PR-6c: aim stabilizer, hysteresis, mouse filter, pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"
if str(_CSGOBOT) not in sys.path:
    sys.path.insert(0, str(_CSGOBOT))

from aim_tuning import (  # noqa: E402
    resolve_aim_dead_zone_high,
    resolve_aim_dead_zone_low,
    resolve_shoot_dead_zone,
)
from aiming.aim_pipeline import AimPipelineState, process_aim_frame  # noqa: E402
from aiming.aim_point_smoother import AimPointSmoother, AimSmoothConfig  # noqa: E402
from aiming.auto_shoot import should_auto_shoot  # noqa: E402
from aiming.dead_zone import AimHysteresis, AimHysteresisConfig  # noqa: E402
from aiming.fov_mouse import FOVMouseMovement  # noqa: E402
from aiming.mouse_filter import filter_mouse_delta  # noqa: E402
from aiming.velocity_lead import LeadConfig, VelocityLead  # noqa: E402
from config import AimConfig, CaptureRegion, FOVConfig  # noqa: E402


def test_aim_smoother_reduces_jitter() -> None:
    s = AimPointSmoother(AimSmoothConfig(enabled=True, alpha=0.3))
    out = []
    for i in range(10):
        x = 100.0 + (5.0 if i % 2 == 0 else -5.0)
        sx, _ = s.update(x, 200.0, float(i) * 0.05)
        out.append(sx)
    assert max(out) - min(out) < 8.0


def test_aim_smoother_jump_reset() -> None:
    s = AimPointSmoother(AimSmoothConfig(jump_reset_px=50.0))
    s.update(100.0, 200.0, 0.0)
    x, y = s.update(200.0, 200.0, 0.1)
    assert x == 200.0
    assert y == 200.0


def test_velocity_lead_variance_gate_blocks_noisy_motion() -> None:
    lead = VelocityLead(
        LeadConfig(
            enabled=True,
            lead_ms=100.0,
            ema_alpha=1.0,
            variance_gate=True,
            min_speed_px_s=40.0,
            max_speed_variance=100.0,
        )
    )
    t = 0.0
    stable_flags = []
    for i in range(8):
        x = 100.0 + (30.0 if i % 2 == 0 else -30.0)
        r = lead.predict(x, 200.0, t)
        stable_flags.append(r.stable)
        t += 0.05
    assert not any(stable_flags)


def test_velocity_lead_stable_motion_applies() -> None:
    lead = VelocityLead(
        LeadConfig(
            enabled=True,
            lead_ms=100.0,
            ema_alpha=1.0,
            variance_gate=True,
            min_speed_px_s=40.0,
            max_speed_variance=5000.0,
        )
    )
    r = lead.predict(100.0, 200.0, 0.0)
    for step in range(1, 6):
        r = lead.predict(100.0 + step * 50.0, 200.0, step * 0.1)
    assert r.stable
    assert r.lead_applied
    assert r.x > 100.0 + 5 * 50.0


def test_hysteresis_no_oscillation_in_band() -> None:
    h = AimHysteresis(AimHysteresisConfig(high=14.0, low=8.0))
    assert h.should_move(20.0) is True
    assert h.should_move(10.0) is True
    assert h.should_move(10.0) is True
    assert h.should_move(9.0) is True
    assert h.should_move(7.0) is False
    assert h.should_move(10.0) is False


def test_mouse_filter_clamp_and_min() -> None:
    assert filter_mouse_delta(100, 0, max_delta=35, min_delta=2) == (35, 0)
    assert filter_mouse_delta(1, 0, max_delta=35, min_delta=2) == (0, 0)


def test_shoot_zone_wider_than_aim_hysteresis_low() -> None:
    assert should_auto_shoot(
        auto_shoot=True,
        pixel_distance=16.0,
        shoot_dead_zone=18.0,
        confidence=0.9,
        is_head=False,
        head_confidence=0.8,
        body_confidence=0.7,
        now=1.0,
        last_shot_time=0.0,
        shoot_cooldown_sec=0.1,
    )
    h = AimHysteresis(AimHysteresisConfig(high=14.0, low=8.0))
    h.should_move(20.0)
    assert h.should_move(16.0) is True


def test_process_aim_frame_integration() -> None:
    aim = AimConfig(
        smoothing_factor=2.0,
        adaptive_smoothing=False,
        aim_dead_zone_high=14.0,
        aim_dead_zone_low=8.0,
        shoot_dead_zone=18.0,
        mouse_max_delta=35,
        mouse_min_delta=2,
    )
    screen = CaptureRegion(width=1280, height=720)
    fov = FOVConfig(horizontal=106.26, vertical=73.74, x360=8182)
    mover = FOVMouseMovement(screen, fov)
    pipe = AimPipelineState.from_aim_config(aim)
    frame = process_aim_frame(
        raw_x=700.0,
        raw_y=400.0,
        target_distance=120.0,
        now=1.0,
        aim_config=aim,
        fov_mouse=mover,
        pipeline=pipe,
        fps_value=30.0,
    )
    assert frame.pixel_distance > 0
    assert abs(frame.mouse_dx) <= 35
    assert abs(frame.mouse_dy) <= 35


def test_env_resolvers_6c(monkeypatch) -> None:
    monkeypatch.setenv("CSGOBOT_AIM_DEAD_ZONE_HIGH", "16")
    monkeypatch.setenv("CSGOBOT_SHOOT_DEAD_ZONE", "20")
    assert resolve_aim_dead_zone_high(14.0, 12.0) == 16.0
    assert resolve_aim_dead_zone_low(8.0, 16.0) == 8.0
    assert resolve_shoot_dead_zone(18.0) == 20.0
