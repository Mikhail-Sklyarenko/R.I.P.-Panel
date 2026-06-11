"""Unit tests for csgobot auto-shoot decision logic."""

from __future__ import annotations

import sys
from pathlib import Path

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"
if str(_CSGOBOT) not in sys.path:
    sys.path.insert(0, str(_CSGOBOT))

from aiming.auto_shoot import should_auto_shoot  # noqa: E402


def test_shoot_when_on_target_and_cooldown_elapsed() -> None:
    assert should_auto_shoot(
        auto_shoot=True,
        pixel_distance=8.0,
        shoot_dead_zone=12.0,
        confidence=0.85,
        is_head=True,
        head_confidence=0.8,
        body_confidence=0.7,
        now=1.0,
        last_shot_time=0.0,
        shoot_cooldown_sec=0.1,
    )


def test_no_shoot_when_disabled() -> None:
    assert not should_auto_shoot(
        auto_shoot=False,
        pixel_distance=5.0,
        shoot_dead_zone=12.0,
        confidence=0.9,
        is_head=False,
        head_confidence=0.8,
        body_confidence=0.7,
        now=1.0,
        last_shot_time=0.0,
        shoot_cooldown_sec=0.1,
    )


def test_no_shoot_outside_dead_zone() -> None:
    assert not should_auto_shoot(
        auto_shoot=True,
        pixel_distance=20.0,
        shoot_dead_zone=12.0,
        confidence=0.9,
        is_head=False,
        head_confidence=0.8,
        body_confidence=0.7,
        now=1.0,
        last_shot_time=0.0,
        shoot_cooldown_sec=0.1,
    )


def test_no_shoot_low_confidence() -> None:
    assert not should_auto_shoot(
        auto_shoot=True,
        pixel_distance=5.0,
        shoot_dead_zone=12.0,
        confidence=0.6,
        is_head=True,
        head_confidence=0.8,
        body_confidence=0.7,
        now=1.0,
        last_shot_time=0.0,
        shoot_cooldown_sec=0.1,
    )


def test_no_shoot_during_cooldown() -> None:
    assert not should_auto_shoot(
        auto_shoot=True,
        pixel_distance=5.0,
        shoot_dead_zone=12.0,
        confidence=0.9,
        is_head=False,
        head_confidence=0.8,
        body_confidence=0.7,
        now=1.05,
        last_shot_time=1.0,
        shoot_cooldown_sec=0.1,
    )


def test_shoot_after_cooldown() -> None:
    assert should_auto_shoot(
        auto_shoot=True,
        pixel_distance=5.0,
        shoot_dead_zone=12.0,
        confidence=0.75,
        is_head=False,
        head_confidence=0.8,
        body_confidence=0.7,
        now=1.11,
        last_shot_time=1.0,
        shoot_cooldown_sec=0.1,
    )
