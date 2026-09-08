"""Product locomotion: yaw gate, crawl fail-open, stuck thrust."""

from __future__ import annotations

import importlib
import math

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
    g["should_hold_forward"] = importlib.import_module(
        "nav.goal_follower"
    ).should_hold_forward
    g["compute_follow_plan"] = importlib.import_module(
        "nav.goal_follower"
    ).compute_follow_plan
    g["bearing_deg"] = importlib.import_module("nav.coords").bearing_deg
    pack = importlib.import_module("nav.pack")
    g["HumanizeConfig"] = pack.HumanizeConfig
    g["NavGoal"] = pack.NavGoal
    g["load_nav_pack"] = pack.load_nav_pack
    g["resolve_nav_pack_path"] = importlib.import_module("nav.paths").resolve_nav_pack_path
    g["PoseResult"] = importlib.import_module("nav.pose").PoseResult
    g["_yaw_from_arrow_tip"] = importlib.import_module(
        "nav.minimap_reader"
    )._yaw_from_arrow_tip
    import numpy as np

    g["np"] = np


def _fov():
    return FOVMouseMovement(
        screen=CaptureRegion(width=1280, height=720),
        fov=FOVConfig(horizontal=106.26, vertical=73.74, x360=16364),
    )


def _hum(**overrides):
    base = dict(
        speed_jitter=0.0,
        micro_pause_chance=0.0,
        micro_pause_sec_min=0.1,
        micro_pause_sec_max=0.1,
        turn_rate_deg_per_sec=90.0,
        path_wobble_deg=0.0,
        forward_max_yaw_deg=48.0,
        turn_smooth_alpha=1.0,
        wobble_refresh_sec=1.0,
        forward_jitter_chance=0.0,
        forward_jitter_sec_min=0.05,
        forward_jitter_sec_max=0.1,
        look_yield_turn=True,
        forward_crawl_yaw_deg=125.0,
        forward_fail_open_after_sec=0.9,
        micro_pause_min_interval_sec=2.5,
    )
    base.update(overrides)
    return HumanizeConfig(**base)


def test_dust2_pack_product_locomotion_defaults() -> None:
    pack = load_nav_pack(resolve_nav_pack_path("dust2_dm"))
    assert pack.version == "2.0.0"
    assert pack.humanize.forward_max_yaw_deg >= 40.0
    assert pack.humanize.forward_crawl_yaw_deg >= 100.0
    assert pack.humanize.forward_fail_open_after_sec <= 1.5
    assert pack.waypoints
    assert pack.edges


def test_should_hold_forward_aligned_and_crawl() -> None:
    hum = _hum()
    assert should_hold_forward(20.0, hum)
    assert not should_hold_forward(80.0, hum)
    assert should_hold_forward(80.0, hum, force_crawl=True)
    assert not should_hold_forward(140.0, hum, force_crawl=True)
    assert should_hold_forward(140.0, hum, force_walk=True)


def test_follow_plan_fail_open_walks_with_large_yaw_error() -> None:
    hum = _hum()
    goal = NavGoal(id="mid", x=0.39, y=0.78, arrive_radius=0.05)
    # Farm soak pose: far from target bearing with noisy yaw.
    pose = PoseResult(0.68, 0.68, 45.0, 0.9, True, 20)
    cold = compute_follow_plan(pose, goal, hum, dt_sec=1 / 60)
    assert cold.forward is False
    assert abs(cold.yaw_error_deg) > 48.0
    hot = compute_follow_plan(
        pose, goal, hum, dt_sec=1 / 60, force_crawl=True, force_walk=True
    )
    assert hot.forward is True


def test_controller_holds_w_after_fail_open_stall() -> None:
    pack = load_nav_pack(resolve_nav_pack_path("dust2_dm"))
    keys: list[str] = []
    ctrl = NavController(
        pack,
        _fov(),
        key_down=keys.append,
        key_up=lambda _k: None,
        move_relative=lambda *_: None,
    )
    # World pose far from mid; misaligned yaw — needs fail-open crawl.
    pose = PoseResult(0.39, 0.91, 45.0, 0.9, True, 20, "world")
    ctrl.tick(pose, now=1.0, paused=False, radar_progressing=True)
    keys.clear()
    result = ctrl.tick(
        pose,
        now=1.0 + pack.humanize.forward_fail_open_after_sec + 0.05,
        paused=False,
        radar_progressing=False,
    )
    assert result.forward_fail_open is True
    assert result.forward_held is True
    assert ctrl._held_key == "w"


def test_stuck_escape_thrusts_forward() -> None:
    pack = load_nav_pack(resolve_nav_pack_path("dust2_dm"))
    keys: list[str] = []
    ctrl = NavController(
        pack,
        _fov(),
        key_down=keys.append,
        key_up=lambda _k: None,
        move_relative=lambda *_: None,
    )
    pose = PoseResult(0.39, 0.91, -90.0, 0.9, True, 20, "world")
    t0 = 100.0
    ctrl.tick(pose, now=t0, paused=False, radar_progressing=True)
    ctrl._session_started_at = t0 - 30
    ctrl._last_progress_at = t0
    ctrl._held_key = "w"
    keys.clear()
    stuck = ctrl.tick(
        pose,
        now=t0 + pack.stuck.progress_timeout_sec + 0.1,
        paused=False,
        radar_progressing=False,
    )
    assert stuck.state == NavState.STUCK_ESCAPE
    assert stuck.stuck_event
    keys.clear()
    esc = ctrl.tick(
        pose,
        now=t0 + pack.stuck.progress_timeout_sec + 0.2,
        paused=False,
        radar_progressing=False,
    )
    assert esc.state == NavState.STUCK_ESCAPE
    assert "w" in keys


def test_arrow_tip_yaw_matches_bearing_convention() -> None:
    """Synthetic chevron pointing east → yaw ≈ 0° (bearing_deg frame)."""
    h = w = 32
    crop = np.zeros((h, w, 3), dtype=np.uint8)
    crop[:, :] = (0, 200, 200)
    component = np.zeros((h, w), dtype=bool)
    # Triangle tip at right of centroid.
    for y in range(12, 20):
        for x in range(10, 14 + (y - 12)):
            component[y, x] = True
    # Bright tip pixels further right.
    for y in range(14, 18):
        component[y, 22] = True
        crop[y, 22] = (180, 255, 255)
    yaw = _yaw_from_arrow_tip(crop, component)
    assert abs(yaw) < 35.0, yaw
    # East bearing of a step to the right is 0°.
    assert abs(bearing_deg(0.0, 0.0, 1.0, 0.0)) < 1e-6
