"""Unit tests for minimap nav humanization (PR-N4)."""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture(scope="module", autouse=True)
def _load_csgobot_nav(csgobot_module_path) -> None:
    g = globals()
    cfg = importlib.import_module("config")
    g["CaptureRegion"] = cfg.CaptureRegion
    g["FOVConfig"] = cfg.FOVConfig
    g["FOVMouseMovement"] = importlib.import_module("aiming.fov_mouse").FOVMouseMovement
    nav_ctrl = importlib.import_module("nav.controller")
    g["NavController"] = nav_ctrl.NavController
    g["NavState"] = nav_ctrl.NavState
    g["compute_follow_plan"] = importlib.import_module("nav.goal_follower").compute_follow_plan
    g["NavHumanizer"] = importlib.import_module("nav.humanize").NavHumanizer
    pack = importlib.import_module("nav.pack")
    g["HumanizeConfig"] = pack.HumanizeConfig
    g["NavGoal"] = pack.NavGoal
    g["load_nav_pack"] = pack.load_nav_pack
    g["resolve_nav_pack_path"] = importlib.import_module("nav.paths").resolve_nav_pack_path
    g["PoseResult"] = importlib.import_module("nav.pose").PoseResult


def _fov_mouse():
    return FOVMouseMovement(
        screen=CaptureRegion(width=1280, height=720),
        fov=FOVConfig(horizontal=106.26, vertical=73.74, x360=16364),
    )


def _pose(x: float, y: float, yaw: float):
    return PoseResult(x, y, yaw, 0.9, True, 20)


def _goal():
    return NavGoal(id="mid", x=0.52, y=0.48, arrive_radius=0.06)


def test_turn_smoothing_reduces_step_spike() -> None:
    cfg = load_nav_pack(resolve_nav_pack_path("dust2_dm")).humanize
    hum = NavHumanizer(cfg, rng=__import__("random").Random(1))
    goal = _goal()
    fov = _fov_mouse()
    pose = _pose(0.2, 0.8, 0.0)

    first = hum.compute(pose, goal, fov, dt_sec=1.0 / 60.0, now=1.0)
    raw = compute_follow_plan(pose, goal, cfg, dt_sec=1.0 / 60.0)
    assert abs(first.yaw_error_deg) > 0.0
    assert abs(raw.turn_step_deg) > 0.0
    raw_mx, _ = fov.angle_to_mouse(raw.turn_step_deg, 0.0)
    assert first.mouse_dx != raw_mx or cfg.turn_smooth_alpha < 1.0


def test_look_yield_suppresses_nav_mouse() -> None:
    cfg = load_nav_pack(resolve_nav_pack_path("dust2_dm")).humanize
    hum = NavHumanizer(cfg, rng=__import__("random").Random(2))
    goal = _goal()
    fov = _fov_mouse()
    pose = _pose(0.2, 0.8, 0.0)

    normal = hum.compute(pose, goal, fov, dt_sec=1.0 / 60.0, now=1.0)
    yielded = hum.compute(
        pose,
        goal,
        fov,
        dt_sec=1.0 / 60.0,
        now=1.1,
        look_sweeping=True,
    )
    assert normal.mouse_dx != 0 or normal.mouse_dy != 0
    assert yielded.mouse_dx == 0 and yielded.mouse_dy == 0
    assert yielded.look_yield


def test_nav_controller_reports_look_yield() -> None:
    pack = load_nav_pack(resolve_nav_pack_path("dust2_dm"))
    ctrl = NavController(
        pack,
        _fov_mouse(),
        key_down=lambda _: None,
        key_up=lambda _: None,
        move_relative=lambda *_: None,
    )
    pose = _pose(0.44, 0.54, -37.0)
    result = ctrl.tick(pose, now=1.0, paused=False, look_sweeping=True)
    assert result.state == NavState.SEEK_GOAL
    assert result.humanize_look_yield


def test_micro_pause_stops_forward() -> None:
    cfg = HumanizeConfig(
        speed_jitter=0.0,
        micro_pause_chance=1.0,
        micro_pause_sec_min=0.2,
        micro_pause_sec_max=0.2,
        turn_rate_deg_per_sec=90.0,
        path_wobble_deg=0.0,
        forward_max_yaw_deg=22.0,
        turn_smooth_alpha=1.0,
        wobble_refresh_sec=1.0,
        forward_jitter_chance=0.0,
        forward_jitter_sec_min=0.05,
        forward_jitter_sec_max=0.1,
        look_yield_turn=True,
    )
    hum = NavHumanizer(cfg, rng=__import__("random").Random(0))
    motion = hum.compute(
        _pose(0.44, 0.54, -37.0),
        _goal(),
        _fov_mouse(),
        dt_sec=1.0 / 60.0,
        now=1.0,
    )
    assert motion.paused
    assert motion.micro_pause
