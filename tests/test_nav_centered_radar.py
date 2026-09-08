"""Centered-radar + place-nav regression tests."""

from __future__ import annotations

import importlib

import numpy as np
import pytest
from PIL import Image
from pathlib import Path


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
    g["Image"] = Image
    g["Path"] = Path
    g["_ROOT"] = Path(__file__).resolve().parents[1]


def _fov():
    return FOVMouseMovement(
        screen=CaptureRegion(width=1280, height=720),
        fov=FOVConfig(horizontal=106.26, vertical=73.74, x360=16364),
    )


def test_legacy_fixtures_still_lock_or_detect_circle() -> None:
    cal = load_calibration(resolve_calibration_path())
    reader = MinimapReader(cal)
    fixtures = _ROOT / "tests" / "fixtures" / "csgobot_nav"
    ok = 0
    for name in ("dust2_mid.jpg", "dust2_t_spawn.jpg", "dust2_long.jpg"):
        img = np.asarray(Image.open(fixtures / name).convert("RGB"))
        pose = reader.read(img)
        # Circle must be found; pose valid preferred (cyan/yellow icon).
        assert reader.last_circle is not None, name
        if pose.valid:
            assert pose.radar_mode == "centered"
            ok += 1
    assert ok >= 2  # mid may be marginal on old cyan-only frames


def test_peripheral_cyan_blob_rejected() -> None:
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


def test_radar_flow_detects_texture_motion() -> None:
    sensor = RadarFlowSensor(progress_threshold=1.5)
    a = np.zeros((80, 80), dtype=np.float32)
    a[20:60, 20:60] = 100
    assert not sensor.update(a).progressing
    b = a.copy()
    b[20:60, 20:60] = 0
    b[25:65, 25:65] = 100
    assert sensor.update(b).motion > 0.0


def test_controller_requires_world_pose() -> None:
    pack = load_nav_pack(resolve_nav_pack_path("dust2_dm"))
    keys: list[str] = []
    ctrl = NavController(
        pack, _fov(), key_down=keys.append, key_up=lambda _k: None,
        move_relative=lambda *_: None,
    )
    centered = PoseResult(0.5, 0.5, -90.0, 0.9, True, 40, "centered")
    r = ctrl.tick(centered, now=1.0, paused=False, radar_progressing=True)
    assert r.state == NavState.WAIT_PLACE


def test_controller_world_pose_seeks_with_path() -> None:
    pack = load_nav_pack(resolve_nav_pack_path("dust2_dm"))
    keys: list[str] = []
    ctrl = NavController(
        pack, _fov(), key_down=keys.append, key_up=lambda _k: None,
        move_relative=lambda *_: None,
    )
    world = PoseResult(0.39, 0.91, -90.0, 0.9, True, 40, "world")
    r = ctrl.tick(world, now=1.0, paused=False, radar_progressing=True)
    assert r.state == NavState.SEEK_GOAL
    assert r.pose_mode == "world"
    assert "mid" in r.path or r.target_id
    assert r.forward_held or abs(r.yaw_error_deg) > 1


def test_stuck_without_flow_while_holding_w() -> None:
    pack = load_nav_pack(resolve_nav_pack_path("dust2_dm"))
    keys: list[str] = []
    ctrl = NavController(
        pack, _fov(), key_down=keys.append, key_up=lambda _k: None,
        move_relative=lambda *_: None,
    )
    world = PoseResult(0.39, 0.91, bearing := -90.0, 0.9, True, 40, "world")
    from nav.coords import bearing_deg
    # Face mid so W engages
    yaw = bearing_deg(0.39, 0.91, 0.52, 0.48)
    world = PoseResult(0.39, 0.91, yaw, 0.9, True, 40, "world")
    t0 = 20.0
    ctrl.tick(world, now=t0, paused=False, radar_progressing=True)
    ctrl._session_started_at = t0 - 30
    ctrl._last_progress_at = t0
    ctrl._held_key = "w"
    stuck = ctrl.tick(
        world,
        now=t0 + pack.stuck.progress_timeout_sec + 0.2,
        paused=False,
        radar_progressing=False,
    )
    assert stuck.state == NavState.STUCK_ESCAPE
    assert stuck.stuck_event
