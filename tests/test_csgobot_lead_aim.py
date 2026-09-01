"""Unit tests for lead aim, adaptive smoothing, and body fallback."""

from __future__ import annotations

import sys
from pathlib import Path

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"
if str(_CSGOBOT) not in sys.path:
    sys.path.append( str(_CSGOBOT))

from aim_tuning import (  # noqa: E402
    adaptive_smoothing,
    resolve_adaptive_smoothing,
    resolve_body_fallback_sec,
    resolve_confidence,
    resolve_lead_enabled,
    resolve_lead_ms,
    resolve_max_assist_distance,
    resolve_prioritize_heads,
)
from aiming.combat_aim import maybe_switch_to_body  # noqa: E402
from aiming.target_selector import Target, TargetSelector  # noqa: E402
from aiming.velocity_lead import LeadConfig, VelocityLead  # noqa: E402
from config import AimConfig, CaptureRegion  # noqa: E402


def _head_target(distance: float = 80.0) -> Target:
    return Target(
        class_name="th",
        class_id=3,
        confidence=0.9,
        x1=600.0,
        y1=300.0,
        x2=640.0,
        y2=340.0,
        aim_x=620.0,
        aim_y=320.0,
        distance=distance,
        is_head=True,
    )


def _body_target(distance: float = 60.0) -> Target:
    return Target(
        class_name="t",
        class_id=2,
        confidence=0.85,
        x1=590.0,
        y1=320.0,
        x2=650.0,
        y2=480.0,
        aim_x=620.0,
        aim_y=373.0,
        distance=distance,
        is_head=False,
    )


def test_velocity_lead_predicts_ahead_on_motion() -> None:
    lead = VelocityLead(
        LeadConfig(
            enabled=True,
            lead_ms=100.0,
            ema_alpha=1.0,
            variance_gate=False,
        )
    )
    t0 = 1.0
    lead.predict(100.0, 200.0, t0)
    r = lead.predict(150.0, 200.0, t0 + 0.1)
    assert r.x > 150.0
    assert abs(r.y - 200.0) < 1.0


def test_velocity_lead_disabled_returns_raw() -> None:
    lead = VelocityLead(LeadConfig(enabled=False))
    r = lead.predict(100.0, 200.0, 1.0)
    assert (r.x, r.y) == (100.0, 200.0)


def test_velocity_lead_clamps_offset() -> None:
    lead = VelocityLead(
        LeadConfig(
            enabled=True,
            lead_ms=500.0,
            ema_alpha=1.0,
            max_lead_px=30.0,
            variance_gate=False,
        ),
    )
    lead.predict(0.0, 0.0, 0.0)
    r = lead.predict(500.0, 0.0, 0.1)
    assert r.x - 500.0 <= 30.1


def test_adaptive_smoothing_far_lower_than_close() -> None:
    far = adaptive_smoothing(3.0, pixel_distance=250.0, fps=30.0)
    close = adaptive_smoothing(3.0, pixel_distance=30.0, fps=30.0)
    assert far < close


def test_adaptive_smoothing_low_fps_increases() -> None:
    low = adaptive_smoothing(3.0, pixel_distance=100.0, fps=10.0)
    high = adaptive_smoothing(3.0, pixel_distance=100.0, fps=40.0)
    assert low > high


def test_body_fallback_switches_after_timeout() -> None:
    head = _head_target(distance=80.0)
    body = _body_target()
    target, miss_since, switched = maybe_switch_to_body(
        head,
        prioritize_heads=True,
        aim_dead_zone_high=12.0,
        body_fallback_sec=0.2,
        head_miss_since=0.0,
        now=0.25,
        select_body=lambda: body,
    )
    assert switched is True
    assert target is body
    assert miss_since is None


def test_body_fallback_not_before_timeout() -> None:
    head = _head_target(distance=80.0)
    target, miss_since, switched = maybe_switch_to_body(
        head,
        prioritize_heads=True,
        aim_dead_zone_high=12.0,
        body_fallback_sec=0.2,
        head_miss_since=0.0,
        now=0.1,
        select_body=lambda: _body_target(),
    )
    assert switched is False
    assert target is head
    assert miss_since == 0.0


def test_select_nearest_body() -> None:
    selector = TargetSelector(AimConfig(), CaptureRegion(width=1280, height=720))
    detections = {
        "th": [
            {
                "xyxy": [600, 300, 640, 340],
                "conf": 0.9,
                "cls": 3,
            }
        ],
        "t": [
            {
                "xyxy": [590, 320, 650, 480],
                "conf": 0.85,
                "cls": 2,
            }
        ],
    }
    body = selector.select_nearest_body(detections, max_distance=300)
    assert body is not None
    assert not body.is_head


def test_env_resolvers_6b(monkeypatch) -> None:
    monkeypatch.setenv("CSGOBOT_CONFIDENCE", "0.6")
    monkeypatch.setenv("CSGOBOT_PRIORITIZE_HEADS", "0")
    monkeypatch.setenv("CSGOBOT_MAX_DIST", "220")
    monkeypatch.setenv("CSGOBOT_LEAD_MS", "120")
    monkeypatch.setenv("CSGOBOT_LEAD_ENABLED", "1")
    monkeypatch.setenv("CSGOBOT_ADAPTIVE_SMOOTHING", "0")
    monkeypatch.setenv("CSGOBOT_BODY_FALLBACK_MS", "300")

    assert resolve_confidence(0.7) == 0.6
    assert resolve_prioritize_heads(True) is False
    assert resolve_max_assist_distance(300) == 220
    assert resolve_lead_ms(80.0) == 120.0
    assert resolve_lead_enabled(False) is True
    assert resolve_adaptive_smoothing(True) is False
    assert resolve_body_fallback_sec(0.2) == 0.3
