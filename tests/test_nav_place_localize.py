"""Objective tests: place-label localization + path planner (no seed GPS)."""

from __future__ import annotations

import importlib

import numpy as np
import pytest
from PIL import Image
from pathlib import Path


@pytest.fixture(scope="module", autouse=True)
def _load(csgobot_module_path) -> None:
    g = globals()
    g["PlaceLocalizer"] = importlib.import_module("nav.place_localizer").PlaceLocalizer
    g["detect_radar_circle"] = importlib.import_module("nav.radar_geom").detect_radar_circle
    g["MinimapReader"] = importlib.import_module("nav.minimap_reader").MinimapReader
    g["load_calibration"] = importlib.import_module("nav.calibration").load_calibration
    g["resolve_calibration_path"] = importlib.import_module("nav.paths").resolve_calibration_path
    g["resolve_nav_root"] = importlib.import_module("nav.paths").resolve_nav_root
    g["plan_path"] = importlib.import_module("nav.planner").plan_path
    g["NavWaypoint"] = importlib.import_module("nav.planner").NavWaypoint
    g["NavGoal"] = importlib.import_module("nav.pack").NavGoal
    g["NavPerception"] = importlib.import_module("nav.perception").NavPerception
    g["load_nav_pack"] = importlib.import_module("nav.pack").load_nav_pack
    g["resolve_nav_pack_path"] = importlib.import_module("nav.paths").resolve_nav_pack_path
    cfg = importlib.import_module("config")
    g["CaptureRegion"] = cfg.CaptureRegion
    g["FOVConfig"] = cfg.FOVConfig
    g["FOVMouseMovement"] = importlib.import_module("aiming.fov_mouse").FOVMouseMovement
    g["NavController"] = importlib.import_module("nav.controller").NavController
    g["NavState"] = importlib.import_module("nav.controller").NavState
    g["PoseResult"] = importlib.import_module("nav.pose").PoseResult
    g["_ROOT"] = Path(__file__).resolve().parents[1]


def test_hud_ref_manifest_exists() -> None:
    man = resolve_nav_root() / "maps" / "de_dust2" / "hud_ref" / "manifest.json"
    assert man.is_file()


def test_place_localizer_ids_all_labeled_frames() -> None:
    loc = PlaceLocalizer("de_dust2")
    assert loc.ready
    assert loc.template_count >= 8
    ref = resolve_nav_root() / "maps" / "de_dust2" / "hud_ref"
    frames = {
        "t_spawn_frame.jpg": "t_spawn",
        "mid_frame.jpg": "mid",
        "long_frame.jpg": "long",
        "short_frame.jpg": "short",
        "bombsite_a_frame.jpg": "bombsite_a",
        "bombsite_b_frame.jpg": "bombsite_b",
        "tunnel_frame.jpg": "tunnel",
        "ct_spawn_ct_frame.jpg": "ct_spawn",
    }
    ok = 0
    for fname, expect in frames.items():
        img = np.asarray(Image.open(ref / fname).convert("RGB"))
        hit = loc.localize(img)
        assert hit is not None, fname
        assert hit.place_id == expect, (fname, hit.place_id, hit.score, hit.margin)
        assert hit.score >= 0.55
        assert hit.margin >= 0.20
        ok += 1
    assert ok == len(frames)


def test_minimap_reader_locks_yellow_player_on_new_hud() -> None:
    cal = load_calibration(resolve_calibration_path())
    reader = MinimapReader(cal)
    ref = resolve_nav_root() / "maps" / "de_dust2" / "hud_ref"
    img = np.asarray(Image.open(ref / "mid_frame.jpg").convert("RGB"))
    pose = reader.read(img)
    assert pose.valid
    assert pose.radar_mode == "centered"
    assert reader.last_circle is not None
    assert reader.last_circle.radius >= 90  # large radar profile


def test_perception_produces_world_pose() -> None:
    cal = load_calibration(resolve_calibration_path())
    reader = MinimapReader(cal)
    loc = PlaceLocalizer("de_dust2")
    perc = NavPerception(reader, loc)
    ref = resolve_nav_root() / "maps" / "de_dust2" / "hud_ref"
    img = np.asarray(Image.open(ref / "tunnel_frame.jpg").convert("RGB"))
    out = perc.update(img, face_x=0.52, face_y=0.48)
    assert out.icon.valid
    assert out.place is not None
    assert out.place.place_id == "tunnel"
    assert out.pose.radar_mode == "world"
    assert abs(out.pose.x_norm - 0.22) < 0.02
    assert abs(out.pose.y_norm - 0.28) < 0.02


def test_planner_tunnel_to_mid_uses_corridor() -> None:
    wps = (
        NavWaypoint("t_spawn", 0.39, 0.91),
        NavWaypoint("mid", 0.52, 0.48),
        NavWaypoint("tunnel", 0.22, 0.28),
        NavWaypoint("long", 0.25, 0.58),
    )
    edges = (("t_spawn", "mid"), ("t_spawn", "long"), ("long", "mid"), ("mid", "tunnel"))
    goal = NavGoal("mid", 0.52, 0.48, 0.07)
    plan = plan_path(0.22, 0.28, goal, wps, edges)
    assert "mid" in plan.waypoint_ids
    assert plan.waypoint_ids[0] in ("tunnel", "mid")


def test_controller_waits_without_world_pose() -> None:
    pack = load_nav_pack(resolve_nav_pack_path("dust2_dm"))
    keys: list[str] = []
    ctrl = NavController(
        pack,
        FOVMouseMovement(
            screen=CaptureRegion(width=1280, height=720),
            fov=FOVConfig(horizontal=106.26, vertical=73.74, x360=16364),
        ),
        key_down=keys.append,
        key_up=lambda _k: None,
        move_relative=lambda *_: None,
    )
    centered = PoseResult(0.5, 0.5, -90.0, 0.9, True, 40, "centered")
    r = ctrl.tick(centered, now=1.0, paused=False, radar_progressing=False)
    assert r.state == NavState.WAIT_PLACE
    assert "w" not in keys


def test_controller_follows_path_with_world_pose() -> None:
    pack = load_nav_pack(resolve_nav_pack_path("dust2_dm"))
    keys: list[str] = []
    ctrl = NavController(
        pack,
        FOVMouseMovement(
            screen=CaptureRegion(width=1280, height=720),
            fov=FOVConfig(horizontal=106.26, vertical=73.74, x360=16364),
        ),
        key_down=keys.append,
        key_up=lambda _k: None,
        move_relative=lambda *_: None,
    )
    # Start at tunnel, seek mid
    world = PoseResult(0.22, 0.28, -90.0, 0.9, True, 40, "world")
    r = ctrl.tick(world, now=1.0, paused=False, radar_progressing=True)
    assert r.pose_mode == "world"
    assert r.state == NavState.SEEK_GOAL
    assert r.path
    assert r.forward_held is True or abs(r.yaw_error_deg) > 5
    assert pack.version.startswith("2.")
