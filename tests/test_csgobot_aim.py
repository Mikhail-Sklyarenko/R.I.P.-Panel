"""Unit tests for csgobot aim tuning (X360, FOV move, env overrides)."""

from __future__ import annotations

import sys
from pathlib import Path

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"
if str(_CSGOBOT) not in sys.path:
    sys.path.insert(0, str(_CSGOBOT))

from aim_tuning import (  # noqa: E402
    aim_debug_enabled,
    resolve_dead_zone,
    resolve_smoothing,
    resolve_x360,
    x360_from_sensitivity,
)
from aiming.fov_mouse import FOVMouseMovement  # noqa: E402
from config import CaptureRegion, FOVConfig  # noqa: E402


def test_x360_from_sensitivity_at_2() -> None:
    assert x360_from_sensitivity(2.0) == 8182


def test_x360_from_sensitivity_at_1() -> None:
    assert x360_from_sensitivity(1.0) == 16364


def test_resolve_x360_explicit_env(monkeypatch) -> None:
    monkeypatch.setenv("CSGOBOT_X360", "9000")
    monkeypatch.delenv("CS2_SENSITIVITY", raising=False)
    assert resolve_x360(7792) == 9000


def test_resolve_x360_from_sensitivity_env(monkeypatch) -> None:
    monkeypatch.delenv("CSGOBOT_X360", raising=False)
    monkeypatch.setenv("CS2_SENSITIVITY", "2.0")
    assert resolve_x360(7792) == 8182


def test_resolve_x360_default_when_no_env(monkeypatch) -> None:
    monkeypatch.delenv("CSGOBOT_X360", raising=False)
    monkeypatch.delenv("CS2_SENSITIVITY", raising=False)
    assert resolve_x360(7792) == 7792


def test_resolve_x360_explicit_beats_sensitivity(monkeypatch) -> None:
    monkeypatch.setenv("CSGOBOT_X360", "5000")
    monkeypatch.setenv("CS2_SENSITIVITY", "2.0")
    assert resolve_x360(7792) == 5000


def test_resolve_smoothing_env(monkeypatch) -> None:
    monkeypatch.setenv("CSGOBOT_SMOOTHING", "4.5")
    assert resolve_smoothing(3.0) == 4.5


def test_resolve_dead_zone_env(monkeypatch) -> None:
    monkeypatch.setenv("CSGOBOT_DEAD_ZONE", "14")
    assert resolve_dead_zone(12.0) == 14.0


def test_aim_debug_env(monkeypatch) -> None:
    monkeypatch.setenv("CSGOBOT_AIM_DEBUG", "1")
    assert aim_debug_enabled()
    monkeypatch.delenv("CSGOBOT_AIM_DEBUG", raising=False)
    assert not aim_debug_enabled()


def test_fov_smoothing_divides_mouse_delta() -> None:
    screen = CaptureRegion(left=0, top=0, width=1280, height=720)
    fov = FOVConfig(horizontal=106.26, vertical=73.74, x360=16364)
    mover = FOVMouseMovement(screen, fov)
    instant = mover.get_move(800, 400, smoothing=1.0)
    smooth = mover.get_move(800, 400, smoothing=3.0)
    assert smooth.mouse_x == int(instant.mouse_x / 3)
    assert smooth.mouse_y == int(instant.mouse_y / 3)


def test_create_config_uses_env_sensitivity(monkeypatch) -> None:
    monkeypatch.delenv("CSGOBOT_X360", raising=False)
    monkeypatch.setenv("CS2_SENSITIVITY", "2.0")
    from run import create_config  # noqa: E402

    cfg = create_config()
    assert cfg.fov.x360 == 8182
    assert cfg.preview.enabled is False


def test_create_config_lead_and_adaptive_defaults(monkeypatch) -> None:
    monkeypatch.delenv("CSGOBOT_LEAD_ENABLED", raising=False)
    monkeypatch.delenv("CSGOBOT_ADAPTIVE_SMOOTHING", raising=False)
    from run import create_config  # noqa: E402

    cfg = create_config()
    assert cfg.aim.lead_aim_enabled is True
    assert cfg.aim.adaptive_smoothing is True
    assert cfg.aim.body_fallback_sec == 0.2


def test_create_config_6d_shoot_defaults(monkeypatch) -> None:
    monkeypatch.delenv("CSGOBOT_SHOOT_MODE", raising=False)
    from run import create_config  # noqa: E402

    cfg = create_config()
    assert cfg.aim.shoot_mode == "hold"
    assert cfg.aim.burst_size == 5
    assert cfg.aim.head_confidence == 0.65


def test_create_config_6c_stabilizer_defaults(monkeypatch) -> None:
    monkeypatch.delenv("CSGOBOT_AIM_DEAD_ZONE_HIGH", raising=False)
    monkeypatch.delenv("CSGOBOT_SHOOT_DEAD_ZONE", raising=False)
    from run import create_config  # noqa: E402

    cfg = create_config()
    assert cfg.aim.aim_dead_zone_high == 14.0
    assert cfg.aim.aim_dead_zone_low == 8.0
    assert cfg.aim.shoot_dead_zone == 18.0
    assert cfg.aim.aim_smooth_enabled is True
    assert cfg.aim.lead_variance_gate is True
