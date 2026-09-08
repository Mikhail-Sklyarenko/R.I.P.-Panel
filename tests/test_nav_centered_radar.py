"""Centered-radar goal-seek (seed + dead reckoning) product tests."""

from __future__ import annotations

import importlib

import numpy as np
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
    g["RadarFlowSensor"] = importlib.import_module("nav.radar_flow").RadarFlowSensor
    g["load_calibration"] = importlib.import_module("nav.calibration").load_calibration
    g["MinimapReader"] = importlib.import_module("nav.minimap_reader").MinimapReader
    g["load_nav_pack"] = importlib.import_module("nav.pack").load_nav_pack
    paths = importlib.import_module("nav.paths")
    g["resolve_calibration_path"] = paths.resolve_calibration_path
    g["resolve_nav_pack_path"] = paths.resolve_nav_pack_path
    g["PoseResult"] = importlib.import_module("nav.pose").PoseResult
    g["WorldPoseTracker"] = importlib.import_module("nav.world_pose").WorldPoseTracker
    g["bearing_deg"] = importlib.import_module("nav.coords").bearing_deg
    g["dist_norm"] = importlib.import_module("nav.coords").dist_norm
    from PIL import Image
    from pathlib import Path

    g["Image"] = Image
    g["Path"] = Path
    g["_ROOT"] = Path(__file__).resolve().parents[1]


def _fov():
    return FOVMouseMovement(
        screen=CaptureRegion(width=1280, height=720),
        fov=FOVConfig(horizontal=106.26, vertical=73.74, x360=16364),
    )


def test_fixtures_lock_center_not_peripheral() -> None:
    cal = load_calibration(resolve_calibration_path())
    reader = MinimapReader(cal)
    fixtures = _ROOT / "tests" / "fixtures" / "csgobot_nav"
    for name in ("dust2_mid.jpg", "dust2_t_spawn.jpg", "dust2_long.jpg"):
        img = np.asarray(Image.open(fixtures / name).convert("RGB"))
        pose = reader.read(img)
        assert pose.valid, name
        assert pose.radar_mode == "centered", name
        assert abs(pose.x_norm - 0.5) < 0.08, (name, pose.x_norm)
        assert abs(pose.y_norm - 0.5) < 0.08, (name, pose.y_norm)
        assert reader.last_ring_gray is not None


def test_peripheral_cyan_blob_rejected() -> None:
    """Synthetic frame: cyan blob far from center must not become player pose."""
    cal = load_calibration(resolve_calibration_path())
    reader = MinimapReader(cal)
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    rect = cal.minimap.rect
    lx = int(rect.w * 0.68)
    ly = int(rect.h * 0.68)
    for dy in range(-4, 5):
        for dx in range(-4, 5):
            frame[rect.y + ly + dy, rect.x + lx + dx] = (40, 220, 220)
    pose = reader.read(frame)
    assert not pose.valid
    assert pose.radar_mode == "none"


def test_radar_flow_detects_texture_motion() -> None:
    sensor = RadarFlowSensor(progress_threshold=1.5)
    a = np.zeros((80, 80), dtype=np.float32)
    a[20:60, 20:60] = 100
    r1 = sensor.update(a)
    assert not r1.progressing
    b = a.copy()
    b[20:60, 20:60] = 0
    b[25:65, 25:65] = 100
    r2 = sensor.update(b)
    assert r2.motion > 0.0


def test_world_pose_seeds_facing_goal() -> None:
    pack = load_nav_pack(resolve_nav_pack_path("dust2_dm"))
    tracker = WorldPoseTracker(pack, rng=__import__("random").Random(0))
    goal = pack.goal
    hud = PoseResult(0.5, 0.5, -90.0, 0.9, True, 40, "centered")
    tracker.observe_hud(hud, now=1.0, goal=goal, team="t")
    pose = tracker.to_pose(hud)
    assert pose.radar_mode == "world"
    assert pose.valid
    expected = bearing_deg(pose.x_norm, pose.y_norm, goal.x, goal.y)
    assert abs(pose.yaw_deg - expected) < 1.0
    assert dist_norm(pose.x_norm, pose.y_norm, goal.x, goal.y) > 0.05


def test_world_pose_integrates_toward_goal() -> None:
    pack = load_nav_pack(resolve_nav_pack_path("dust2_dm"))
    tracker = WorldPoseTracker(pack, rng=__import__("random").Random(1))
    goal = pack.goals[0]  # mid
    hud = PoseResult(0.5, 0.5, -90.0, 0.9, True, 40, "centered")
    tracker.observe_hud(hud, now=1.0, goal=goal, team="t")
    tracker.face_point(goal.x, goal.y)
    start = tracker.to_pose(hud)
    d0 = dist_norm(start.x_norm, start.y_norm, goal.x, goal.y)
    for _ in range(40):
        tracker.integrate(
            dt=0.05,
            yaw_delta_deg=0.0,
            forward=True,
            radar_progressing=True,
        )
    end = tracker.to_pose(hud)
    d1 = dist_norm(end.x_norm, end.y_norm, goal.x, goal.y)
    assert d1 < d0 - 0.05


def test_controller_goal_seeks_from_centered_hud() -> None:
    """Centered HUD input must produce map-frame seek (dist + yaw_err + W)."""
    pack = load_nav_pack(resolve_nav_pack_path("dust2_dm"))
    keys: list[str] = []
    moves: list[tuple[int, int]] = []
    ctrl = NavController(
        pack,
        _fov(),
        key_down=keys.append,
        key_up=lambda _k: None,
        move_relative=lambda dx, dy: moves.append((dx, dy)),
    )
    pose = PoseResult(0.5, 0.5, -90.0, 0.9, True, 40, "centered")
    r0 = ctrl.tick(pose, now=1.0, paused=False, radar_progressing=True)
    assert r0.pose_mode == "world"
    assert r0.state in (NavState.SEEK_GOAL, NavState.SEEK_ENTRY)
    assert r0.dist_to_goal > 0.05
    assert r0.forward_held is True
    assert "w" in keys
    dists = [r0.dist_to_goal]
    last = r0
    for i in range(1, 120):
        last = ctrl.tick(
            pose,
            now=1.0 + i * 0.05,
            paused=False,
            radar_progressing=True,
        )
        dists.append(last.dist_to_goal)
    assert min(dists) < r0.dist_to_goal - 0.02 or last.state == NavState.AT_GOAL


def test_centered_stuck_uses_dist_progress() -> None:
    pack = load_nav_pack(resolve_nav_pack_path("dust2_dm"))
    keys: list[str] = []
    ctrl = NavController(
        pack,
        _fov(),
        key_down=keys.append,
        key_up=lambda _k: None,
        move_relative=lambda *_: None,
    )
    pose = PoseResult(0.5, 0.5, -90.0, 0.9, True, 40, "centered")
    t0 = 50.0
    ctrl.tick(pose, now=t0, paused=False, radar_progressing=False)
    ctrl._session_started_at = t0 - 30.0
    ctrl._last_progress_at = t0
    ctrl._best_dist = 0.0  # cannot improve → timeout must fire
    stuck = ctrl.tick(
        pose,
        now=t0 + pack.stuck.progress_timeout_sec + 0.3,
        paused=False,
        radar_progressing=False,
    )
    assert stuck.state == NavState.STUCK_ESCAPE
    assert stuck.stuck_event
