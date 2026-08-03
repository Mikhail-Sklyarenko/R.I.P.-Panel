"""Unit tests for AimMouseController (PR-A1 / Aim L1.3-style)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"
if str(_CSGOBOT) not in sys.path:
    sys.path.insert(0, str(_CSGOBOT))

from aiming.aim_mouse_controller import AimMouseController  # noqa: E402
from aiming.fov_mouse import FOVMouseMovement  # noqa: E402
from config import AimConfig, CaptureRegion, FOVConfig  # noqa: E402


def _fov() -> FOVMouseMovement:
    screen = CaptureRegion(left=0, top=0, width=1280, height=720)
    fov = FOVConfig(horizontal=106.26, vertical=73.74, x360=16364)
    return FOVMouseMovement(screen, fov)


def _ctrl(
    *,
    mouse_hz: float = 90.0,
    mouse_step_max_delta: int = 12,
    mouse_coast: bool = True,
    mouse_coast_max_sec: float = 0.10,
    aim_dead_zone_high: float = 14.0,
    aim_dead_zone_low: float = 8.0,
    mouse_min_delta: int = 0,
) -> AimMouseController:
    aim = AimConfig(
        mouse_hz=mouse_hz,
        mouse_step_max_delta=mouse_step_max_delta,
        mouse_coast=mouse_coast,
        mouse_coast_max_sec=mouse_coast_max_sec,
        aim_dead_zone_high=aim_dead_zone_high,
        aim_dead_zone_low=aim_dead_zone_low,
        mouse_min_delta=mouse_min_delta,
        mouse_max_delta=35,
        smoothing_factor=1.0,
        adaptive_smoothing=False,
        aim_smooth_enabled=False,
        lead_aim_enabled=False,
    )
    return AimMouseController(config=aim, fov_mouse=_fov())


def test_enabled_when_hz_positive() -> None:
    assert _ctrl(mouse_hz=120.0).enabled
    assert not _ctrl(mouse_hz=0.0).enabled


def test_high_rate_thread_applies_capped_mouse() -> None:
    pieces: list[tuple[int, int]] = []
    ctrl = _ctrl(mouse_hz=90.0, mouse_step_max_delta=12, mouse_min_delta=0)
    ctrl.start(lambda dx, dy: pieces.append((dx, dy)))
    try:
        # Far from center → must move
        ctrl.set_target(900.0, 360.0, smoothing=1.0, now=time.monotonic())
        deadline = time.monotonic() + 0.8
        while time.monotonic() < deadline and len(pieces) < 5:
            time.sleep(0.02)
        assert len(pieces) >= 5
        assert all(abs(dx) <= 12 and abs(dy) <= 12 for dx, dy in pieces)
        assert ctrl.consume_applied()
    finally:
        ctrl.stop()


def test_clear_stops_tracking() -> None:
    pieces: list[tuple[int, int]] = []
    ctrl = _ctrl(mouse_hz=60.0, mouse_step_max_delta=20)
    ctrl.start(lambda dx, dy: pieces.append((dx, dy)))
    try:
        ctrl.set_target(900.0, 400.0, smoothing=1.0, now=time.monotonic())
        time.sleep(0.15)
        before = len(pieces)
        ctrl.clear()
        time.sleep(0.15)
        after = len(pieces)
        assert not ctrl.is_tracking
        # At most a couple of in-flight ticks after clear
        assert after - before <= 3
    finally:
        ctrl.stop()


def test_coast_velocity_from_successive_targets() -> None:
    ctrl = _ctrl(mouse_hz=0.0, mouse_coast=True)
    t0 = 10.0
    ctrl.set_target(640.0, 360.0, smoothing=1.0, now=t0)
    ctrl.set_target(740.0, 360.0, smoothing=1.0, now=t0 + 0.05)
    with ctrl._lock:
        assert ctrl._vx > 0
        assert abs(ctrl._vx - 2000.0) < 1.0
        assert abs(ctrl._vy) < 1e-6


def test_legacy_hz_zero_does_not_start_thread() -> None:
    ctrl = _ctrl(mouse_hz=0.0)
    ctrl.start(lambda dx, dy: None)
    assert ctrl._thread is None
    ctrl.stop()
