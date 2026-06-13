"""PR-6d: burst, hold, and tap fire controller."""

from __future__ import annotations

import sys
from pathlib import Path

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"
if str(_CSGOBOT) not in sys.path:
    sys.path.insert(0, str(_CSGOBOT))

from aim_tuning import (  # noqa: E402
    resolve_burst_gap_sec,
    resolve_burst_size,
    resolve_hold_max_sec,
    resolve_shoot_mode,
)
from aiming.fire_controller import (  # noqa: E402
    FireConfig,
    FireController,
    target_in_shoot_zone,
)
from config import AimConfig  # noqa: E402


def _on_target_cfg() -> FireConfig:
    return FireConfig(
        enabled=True,
        mode="hold",
        shoot_dead_zone=18.0,
        head_confidence=0.65,
        body_confidence=0.55,
        hold_max_sec=0.3,
        hold_release_grace_sec=0.05,
        humanize_jitter_sec=0.0,
    )


def test_target_in_shoot_zone_body() -> None:
    assert target_in_shoot_zone(
        pixel_distance=16.0,
        shoot_dead_zone=18.0,
        confidence=0.7,
        is_head=False,
        head_confidence=0.65,
        body_confidence=0.55,
    )


def test_hold_press_and_release_max_duration() -> None:
    fc = FireController(_on_target_cfg())
    r0 = fc.tick(
        pixel_distance=10.0,
        confidence=0.8,
        is_head=False,
        now=0.0,
    )
    assert r0.press
    assert fc.is_holding

    r1 = fc.tick(
        pixel_distance=10.0,
        confidence=0.8,
        is_head=False,
        now=0.35,
    )
    assert r1.release
    assert not fc.is_holding


def test_hold_release_after_off_target_grace() -> None:
    fc = FireController(_on_target_cfg())
    fc.tick(pixel_distance=10.0, confidence=0.8, is_head=False, now=0.0)
    fc.tick(pixel_distance=30.0, confidence=0.8, is_head=False, now=0.02)
    r = fc.tick(pixel_distance=30.0, confidence=0.8, is_head=False, now=0.08)
    assert r.release


def test_burst_fires_multiple_clicks() -> None:
    cfg = FireConfig(
        enabled=True,
        mode="burst",
        shoot_dead_zone=18.0,
        body_confidence=0.55,
        burst_size=3,
        burst_shot_interval_sec=0.05,
        burst_gap_sec=0.1,
        humanize_jitter_sec=0.0,
    )
    fc = FireController(cfg)
    clicks = 0
    t = 0.0
    for _ in range(6):
        r = fc.tick(
            pixel_distance=10.0,
            confidence=0.8,
            is_head=False,
            now=t,
        )
        if r.click:
            clicks += 1
        t += 0.06
    assert clicks >= 3


def test_tap_respects_cooldown() -> None:
    cfg = FireConfig(
        enabled=True,
        mode="tap",
        shoot_dead_zone=18.0,
        body_confidence=0.55,
        shoot_cooldown_sec=0.1,
        humanize_jitter_sec=0.0,
    )
    fc = FireController(cfg)
    assert fc.tick(
        pixel_distance=10.0, confidence=0.8, is_head=False, now=0.0
    ).click
    assert not fc.tick(
        pixel_distance=10.0, confidence=0.8, is_head=False, now=0.05
    ).click
    assert fc.tick(
        pixel_distance=10.0, confidence=0.8, is_head=False, now=0.12
    ).click


def test_force_release_when_target_lost() -> None:
    fc = FireController(_on_target_cfg())
    fc.tick(pixel_distance=10.0, confidence=0.8, is_head=False, now=0.0)
    r = fc.force_release(0.1)
    assert r.release
    assert not fc.is_holding


def test_from_aim_config_defaults() -> None:
    fc = FireController.from_aim_config(AimConfig(auto_shoot=True))
    assert fc.config.mode == "hold"
    assert fc.config.burst_size == 7


def test_hold_represses_quickly_after_max_duration() -> None:
    cfg = FireConfig(
        enabled=True,
        mode="hold",
        shoot_dead_zone=18.0,
        body_confidence=0.55,
        hold_max_sec=0.2,
        hold_repress_gap_sec=0.05,
        humanize_jitter_sec=0.0,
    )
    fc = FireController(cfg)
    fc.tick(pixel_distance=10.0, confidence=0.8, is_head=False, now=0.0)
    r_release = fc.tick(pixel_distance=10.0, confidence=0.8, is_head=False, now=0.21)
    assert r_release.release
    r_repress = fc.tick(pixel_distance=10.0, confidence=0.8, is_head=False, now=0.27)
    assert r_repress.press


def test_env_resolvers_6d(monkeypatch) -> None:
    monkeypatch.setenv("CSGOBOT_SHOOT_MODE", "burst")
    monkeypatch.setenv("CSGOBOT_BURST_SIZE", "4")
    monkeypatch.setenv("CSGOBOT_BURST_GAP_MS", "200")
    monkeypatch.setenv("CSGOBOT_HOLD_MAX_MS", "500")
    assert resolve_shoot_mode("hold") == "burst"
    assert resolve_burst_size(5) == 4
    assert resolve_burst_gap_sec(0.15) == 0.2
    assert resolve_hold_max_sec(0.4) == 0.5
