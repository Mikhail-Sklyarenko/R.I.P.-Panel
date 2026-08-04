"""Unit tests for AimMouseController (PR-A1 / A1.1 settle)."""

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
    mouse_coast_min_speed_px_s: float = 150.0,
    aim_dead_zone_high: float = 14.0,
    aim_dead_zone_low: float = 8.0,
    mouse_min_delta: int = 0,
    aim_settle_enabled: bool = True,
    aim_settle_px: float = 10.0,
    aim_unlock_px: float = 18.0,
    aim_near_px: float = 56.0,
    aim_near_step_max_delta: int = 8,
    aim_near_y_scale: float = 1.0,
) -> AimMouseController:
    aim = AimConfig(
        mouse_hz=mouse_hz,
        mouse_step_max_delta=mouse_step_max_delta,
        mouse_coast=mouse_coast,
        mouse_coast_max_sec=mouse_coast_max_sec,
        mouse_coast_min_speed_px_s=mouse_coast_min_speed_px_s,
        aim_dead_zone_high=aim_dead_zone_high,
        aim_dead_zone_low=aim_dead_zone_low,
        mouse_min_delta=mouse_min_delta,
        mouse_max_delta=35,
        smoothing_factor=1.0,
        adaptive_smoothing=False,
        aim_smooth_enabled=False,
        lead_aim_enabled=False,
        aim_settle_enabled=aim_settle_enabled,
        aim_settle_px=aim_settle_px,
        aim_unlock_px=aim_unlock_px,
        aim_near_px=aim_near_px,
        aim_near_step_max_delta=aim_near_step_max_delta,
        aim_near_y_scale=aim_near_y_scale,
    )
    return AimMouseController(config=aim, fov_mouse=_fov())


def test_enabled_when_hz_positive() -> None:
    assert _ctrl(mouse_hz=120.0).enabled
    assert not _ctrl(mouse_hz=0.0).enabled


def test_high_rate_thread_applies_capped_mouse() -> None:
    pieces: list[tuple[int, int]] = []
    ctrl = _ctrl(
        mouse_hz=90.0,
        mouse_step_max_delta=12,
        mouse_min_delta=0,
        aim_settle_px=2.0,
    )
    ctrl.start(lambda dx, dy: pieces.append((dx, dy)))
    try:
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
        assert after - before <= 3
    finally:
        ctrl.stop()


def test_coast_velocity_from_successive_targets() -> None:
    ctrl = _ctrl(mouse_hz=0.0, mouse_coast=True, mouse_coast_min_speed_px_s=100.0)
    t0 = 10.0
    ctrl.set_target(640.0, 360.0, smoothing=1.0, now=t0)
    ctrl.set_target(740.0, 360.0, smoothing=1.0, now=t0 + 0.05)
    with ctrl._lock:
        assert ctrl._vx > 0
        assert abs(ctrl._vx - 2000.0) < 1.0
        assert abs(ctrl._vy) < 1e-6


def test_coast_velocity_gated_for_slow_jitter() -> None:
    ctrl = _ctrl(mouse_hz=0.0, mouse_coast_min_speed_px_s=150.0)
    t0 = 10.0
    ctrl.set_target(640.0, 360.0, smoothing=1.0, now=t0)
    # 5 px / 0.05 s = 100 px/s < 150 → no coast velocity
    ctrl.set_target(645.0, 360.0, smoothing=1.0, now=t0 + 0.05)
    with ctrl._lock:
        assert ctrl._vx == 0.0
        assert ctrl._vy == 0.0


def test_settle_ignores_bbox_jitter_until_unlock() -> None:
    ctrl = _ctrl(
        mouse_hz=0.0,
        aim_settle_enabled=True,
        aim_settle_px=10.0,
        aim_unlock_px=18.0,
    )
    # Force settle state as if crosshair already on target.
    with ctrl._lock:
        ctrl._settled = True
        ctrl._lock_x = 640.0
        ctrl._lock_y = 360.0
        ctrl._target_x = 640.0
        ctrl._target_y = 360.0
        ctrl._has_sample = True
        ctrl._active = True

    ctrl.set_target(646.0, 368.0, smoothing=1.0, now=1.0)  # ~10 px jitter
    with ctrl._lock:
        assert ctrl._settled
        assert ctrl._target_x == 640.0
        assert ctrl._target_y == 360.0
        assert ctrl._vx == 0.0

    ctrl.set_target(670.0, 360.0, smoothing=1.0, now=1.1)  # 30 px → unlock
    with ctrl._lock:
        assert not ctrl._settled
        assert abs(ctrl._target_x - 670.0) < 1e-6


def test_on_target_settle_stops_mouse() -> None:
    pieces: list[tuple[int, int]] = []
    ctrl = _ctrl(
        mouse_hz=90.0,
        mouse_step_max_delta=20,
        mouse_min_delta=0,
        aim_settle_px=12.0,
        aim_near_px=80.0,
        aim_near_step_max_delta=6,
    )
    ctrl.start(lambda dx, dy: pieces.append((dx, dy)))
    try:
        # Slightly off center → pull in, then settle
        ctrl.set_target(648.0, 362.0, smoothing=1.0, now=time.monotonic())
        time.sleep(0.35)
        mid = len(pieces)
        # Feed jitter while hopefully settled
        for i in range(8):
            ctrl.set_target(
                640.0 + (i % 3) - 1,
                360.0 + (i % 2),
                smoothing=1.0,
                now=time.monotonic(),
            )
            time.sleep(0.03)
        # After settle, additional applies should be rare/none
        assert ctrl.is_settled or (len(pieces) - mid) <= 4
    finally:
        ctrl.stop()


def test_near_y_scale_damps_vertical_moves() -> None:
    """A1.2.1: near-zone dy should be smaller with y_scale < 1."""

    def _collect(y_scale: float) -> list[tuple[int, int]]:
        pieces: list[tuple[int, int]] = []
        ctrl = _ctrl(
            mouse_hz=90.0,
            mouse_step_max_delta=20,
            mouse_min_delta=0,
            aim_settle_enabled=False,
            aim_near_px=200.0,
            aim_near_step_max_delta=20,
            aim_near_y_scale=y_scale,
            aim_dead_zone_high=2.0,
            aim_dead_zone_low=1.0,
        )
        ctrl.start(lambda dx, dy: pieces.append((dx, dy)))
        try:
            # Pure vertical offset inside near zone
            ctrl.set_target(640.0, 400.0, smoothing=1.0, now=time.monotonic())
            deadline = time.monotonic() + 0.25
            while time.monotonic() < deadline and len(pieces) < 8:
                time.sleep(0.02)
        finally:
            ctrl.stop()
        return pieces

    full = _collect(1.0)
    damp = _collect(0.5)
    assert full and damp
    full_dy = sum(abs(dy) for _, dy in full[:5])
    damp_dy = sum(abs(dy) for _, dy in damp[:5])
    assert damp_dy < full_dy


def test_legacy_hz_zero_does_not_start_thread() -> None:
    ctrl = _ctrl(mouse_hz=0.0)
    ctrl.start(lambda dx, dy: None)
    assert ctrl._thread is None
    ctrl.stop()
