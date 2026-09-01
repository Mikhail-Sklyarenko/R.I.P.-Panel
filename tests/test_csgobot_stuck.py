"""Unit tests for csgobot anti-stuck (frame diff + unstuck sequence)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"
if str(_CSGOBOT) not in sys.path:
    sys.path.append( str(_CSGOBOT))

from patrol.state import PatrolMode  # noqa: E402
from patrol.stuck import StuckDetector, should_trigger_unstuck  # noqa: E402
from patrol.unstuck import UnstuckSequence  # noqa: E402


def _rgb_frame(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8)


def test_should_trigger_unstuck_requires_patrol_moving() -> None:
    assert should_trigger_unstuck(
        anti_stuck_enabled=True,
        activated=True,
        patrol_mode=PatrolMode.PATROL,
        in_combat=False,
        is_moving=True,
        stuck_since=0.0,
        now=7.0,
        stuck_sec=6.0,
        last_unstuck_time=0.0,
        unstuck_cooldown_sec=3.0,
    )
    assert not should_trigger_unstuck(
        anti_stuck_enabled=True,
        activated=True,
        patrol_mode=PatrolMode.COMBAT,
        in_combat=True,
        is_moving=True,
        stuck_since=0.0,
        now=7.0,
        stuck_sec=6.0,
        last_unstuck_time=0.0,
        unstuck_cooldown_sec=3.0,
    )
    assert not should_trigger_unstuck(
        anti_stuck_enabled=True,
        activated=True,
        patrol_mode=PatrolMode.PATROL,
        in_combat=False,
        is_moving=False,
        stuck_since=0.0,
        now=7.0,
        stuck_sec=6.0,
        last_unstuck_time=0.0,
        unstuck_cooldown_sec=3.0,
    )


def test_should_trigger_unstuck_respects_cooldown() -> None:
    assert not should_trigger_unstuck(
        anti_stuck_enabled=True,
        activated=True,
        patrol_mode=PatrolMode.PATROL,
        in_combat=False,
        is_moving=True,
        stuck_since=0.0,
        now=8.0,
        stuck_sec=6.0,
        last_unstuck_time=7.5,
        unstuck_cooldown_sec=3.0,
    )


def test_stuck_detector_low_motion_on_static_frames() -> None:
    det = StuckDetector(motion_threshold=2.0)
    frame = _rgb_frame(42)
    det.update(frame)
    det.update(frame)
    assert det.is_low_motion()


def test_stuck_detector_high_motion_on_change() -> None:
    det = StuckDetector(motion_threshold=2.0)
    det.update(_rgb_frame(1))
    det.update(_rgb_frame(2))
    assert not det.is_low_motion()


def test_unstuck_sequence_full_flow() -> None:
    pressed: list[str] = []
    down: list[str] = []
    up: list[str] = []

    seq = UnstuckSequence(
        press=pressed.append,
        key_down=down.append,
        key_up=up.append,
        back_sec=0.5,
        strafe_min_sec=1.0,
        strafe_max_sec=1.0,
    )
    seq.start(0.0)
    assert pressed == ["space"]
    assert seq.is_running

    assert seq.tick(0.0)
    assert down == ["s"]

    assert seq.tick(0.4)
    assert seq.is_running

    assert seq.tick(0.5)
    assert "s" in up
    assert down[-1] in ("a", "d")

    assert seq.tick(1.4)
    assert seq.is_running

    assert not seq.tick(1.5)
    assert not seq.is_running
    assert down[-1] in up


def test_unstuck_abort_releases_keys() -> None:
    down: list[str] = []
    up: list[str] = []
    seq = UnstuckSequence(
        press=lambda k: None,
        key_down=down.append,
        key_up=up.append,
    )
    seq.start(0.0)
    seq.tick(0.0)
    seq.abort()
    assert "s" in up
    assert not seq.is_running
