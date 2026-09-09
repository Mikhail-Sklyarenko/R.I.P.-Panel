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
    assert loc.template_count >= 20
    ref = resolve_nav_root() / "maps" / "de_dust2" / "hud_ref"
    frames = sorted(ref.glob("*_frame.jpg"))
    assert len(frames) >= 20
    ok = 0
    for path in frames:
        expect = path.name.replace("_frame.jpg", "")
        img = np.asarray(Image.open(path).convert("RGB"))
        hit = loc.localize(img)
        assert hit is not None, path.name
        assert hit.place_id == expect, (path.name, hit.place_id, hit.score, hit.margin)
        assert hit.score >= 0.50
        assert hit.margin >= 0.15
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
    assert abs(out.pose.y_norm - 0.30) < 0.02


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
    # Start at tunnel with place lock — corridor script + Safe-W with flow
    world = PoseResult(0.22, 0.28, -90.0, 0.9, True, 40, "world", place_id="tunnel")
    r = ctrl.tick(world, now=1.0, paused=False, radar_progressing=True)
    assert r.pose_mode == "world"
    assert r.state == NavState.SEEK_GOAL
    assert r.path
    assert "tunnel" in r.path or "corridor" in r.path or "mid" in r.path
    assert pack.version.startswith("2.")
    assert len(pack.waypoints) >= 20
    assert ctrl.suppresses_look is True
    # With radar flow, Safe-W may walk or turn toward face landmark.
    assert r.forward_held is True or abs(r.yaw_error_deg) < 90.0

def test_perception_holds_world_across_place_flicker() -> None:
    cal = load_calibration(resolve_calibration_path())
    reader = MinimapReader(cal)
    loc = PlaceLocalizer("de_dust2")
    perc = NavPerception(reader, loc, hold_sec=4.0)
    ref = resolve_nav_root() / "maps" / "de_dust2" / "hud_ref"
    img = np.asarray(Image.open(ref / "mid_frame.jpg").convert("RGB"))
    hit = perc.update(img, face_x=0.55, face_y=0.28, now=10.0)
    assert hit.pose.radar_mode == "world"
    assert hit.place is not None
    # Simulate frames with icon but no place match: still world while hold alive.
    icon_only = PoseResult(0.5, 0.5, -90.0, 0.8, True, 40, "centered")

    class _FakeReader:
        last_circle = reader.last_circle

        def read(self, _frame):
            return icon_only

    perc.reader = _FakeReader()  # type: ignore[assignment]
    perc.localizer.localize = lambda *_a, **_k: None  # type: ignore[method-assign]
    held = perc.update(img, face_x=0.55, face_y=0.28, now=12.0)
    assert held.pose.radar_mode == "world"
    assert held.place_held is True
    assert abs(held.pose.x_norm - hit.pose.x_norm) < 0.02


def test_place_localizer_multi_offset_still_ids_all() -> None:
    loc = PlaceLocalizer("de_dust2")
    ref = resolve_nav_root() / "maps" / "de_dust2" / "hud_ref"
    for path in sorted(ref.glob("*_frame.jpg")):
        expect = path.name.replace("_frame.jpg", "")
        img = np.asarray(Image.open(path).convert("RGB"))
        dbg = loc.match_debug(img)
        assert dbg.accepted, (path.name, dbg.top)
        assert dbg.best is not None
        assert dbg.best.place_id == expect


def test_perception_switch_hysteresis() -> None:
    cal = load_calibration(resolve_calibration_path())
    reader = MinimapReader(cal)
    loc = PlaceLocalizer("de_dust2")
    perc = NavPerception(reader, loc, hold_sec=4.0, switch_confirm=2)
    ref = resolve_nav_root() / "maps" / "de_dust2" / "hud_ref"
    mid = np.asarray(Image.open(ref / "mid_frame.jpg").convert("RGB"))
    short = np.asarray(Image.open(ref / "short_frame.jpg").convert("RGB"))
    a = perc.update(mid, face_x=0.5, face_y=0.5, now=1.0)
    assert a.place is not None and a.place.place_id == "mid"
    # One frame of short is not enough to switch
    b = perc.update(short, face_x=0.5, face_y=0.5, now=1.1)
    assert b.place is not None and b.place.place_id == "mid"
    c = perc.update(short, face_x=0.5, face_y=0.5, now=1.2)
    assert c.place is not None and c.place.place_id == "short"


def test_perception_rejects_weak_teleport() -> None:
    """FermK soak: a_ramp ↔ tunnel_stairs with score~0.5 must not jump."""
    from nav.place_localizer import PlaceHit

    cal = load_calibration(resolve_calibration_path())
    reader = MinimapReader(cal)
    loc = PlaceLocalizer("de_dust2")
    perc = NavPerception(reader, loc, hold_sec=4.0, switch_confirm=3)
    under = PlaceHit("under_a", 0.78, 0.28, 0.55, 0.28)
    tunnel = PlaceHit("tunnel_stairs", 0.20, 0.25, 0.52, 0.20)
    perc._last_hit = under
    perc._last_hit_at = 10.0
    # Weak teleport candidate — keep under_a
    kept = perc._resolve_place(tunnel, now=10.0)
    assert kept is not None and kept.place_id == "under_a"
    # Even after several frames without override score
    for i in range(5):
        kept = perc._resolve_place(tunnel, now=10.1 + i * 0.1)
    assert kept is not None and kept.place_id == "under_a"
    # Strong override after confirm frames (update() would commit last_hit)
    strong = PlaceHit("tunnel_stairs", 0.20, 0.25, 0.70, 0.30)
    accepted = None
    for i in range(6):
        accepted = perc._resolve_place(strong, now=11.0 + i * 0.05)
        if accepted is not None and accepted.place_id == "tunnel_stairs":
            perc._last_hit = accepted
            break
    assert accepted is not None and accepted.place_id == "tunnel_stairs"


def test_perception_clears_lock_after_reject_streak() -> None:
    from nav.place_localizer import PlaceHit

    cal = load_calibration(resolve_calibration_path())
    reader = MinimapReader(cal)
    loc = PlaceLocalizer("de_dust2")
    perc = NavPerception(reader, loc, hold_sec=2.5, switch_confirm=3)
    under = PlaceHit("ct_spawn", 0.62, 0.21, 0.55, 0.28)
    tunnel = PlaceHit("tunnel_upper", 0.20, 0.22, 0.58, 0.30)
    perc._last_hit = under
    perc._last_hit_at = 1.0
    out = None
    for i in range(8):
        out = perc._resolve_place(tunnel, now=1.0 + i * 0.4)
    # After ~2.5s of rejects, lock clears (None) — no eternal ct_spawn
    assert out is None
    assert perc._last_hit is None


def test_controller_corridor_ct_spawn_and_safe_w() -> None:
    pack = load_nav_pack(resolve_nav_pack_path("dust2_dm"))
    keys: list[str] = []
    ups: list[str] = []
    ctrl = NavController(
        pack,
        FOVMouseMovement(
            screen=CaptureRegion(width=1280, height=720),
            fov=FOVConfig(horizontal=106.26, vertical=73.74, x360=16364),
        ),
        key_down=keys.append,
        key_up=ups.append,
        move_relative=lambda *_: None,
    )
    world = PoseResult(0.62, 0.21, 0.0, 0.9, True, 40, "world", place_id="ct_spawn")
    r0 = ctrl.tick(world, now=1.0, paused=False, radar_progressing=True)
    assert "ct_spawn_to_mid" in r0.path or r0.target_id == "short"
    # No flow and burst expired → Safe-W must release W (not wall-run)
    ctrl._walk_burst_until = 0.0
    ctrl._held_key = "w"
    keys.clear()
    r1 = ctrl.tick(world, now=5.0, paused=False, radar_progressing=False)
    assert r1.forward_held is False
    # Hold W with no flow → wall-stop (rotate, no thrust)
    ctrl._held_key = "w"
    ctrl._no_flow_while_w_since = 5.0
    stuck = ctrl.tick(world, now=6.3, paused=False, radar_progressing=False)
    assert stuck.state == NavState.STUCK_ESCAPE
    assert stuck.forward_held is False


def test_controller_hop_by_place_lock() -> None:
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
    # Start at tunnel_stairs on path toward mid
    start = PoseResult(
        0.20, 0.25, 0.0, 0.9, True, 40, "world", place_id="tunnel_stairs",
    )
    r0 = ctrl.tick(start, now=1.0, paused=False, radar_progressing=True)
    assert r0.state == NavState.SEEK_GOAL
    assert "tunnel" in r0.path or "mid" in r0.path
    # Jump place along path without XY motion — advance hop
    nxt = PoseResult(
        0.20, 0.25, 0.0, 0.9, True, 40, "world", place_id="outside_tunnel",
    )
    # outside_tunnel may not be on every plan; use a place that is on path
    path_ids = r0.path.split(">")
    if len(path_ids) >= 2:
        later = path_ids[min(1, len(path_ids) - 1)]
        if later != "tunnel_stairs":
            nxt = PoseResult(
                0.20, 0.25, 0.0, 0.9, True, 40, "world", place_id=later,
            )
            r1 = ctrl.tick(nxt, now=2.0, paused=False, radar_progressing=True)
            assert r1.target_id == later or later in r1.path


def test_controller_paused_keeps_path() -> None:
    pack = load_nav_pack(resolve_nav_pack_path("dust2_dm"))
    ctrl = NavController(
        pack,
        FOVMouseMovement(
            screen=CaptureRegion(width=1280, height=720),
            fov=FOVConfig(horizontal=106.26, vertical=73.74, x360=16364),
        ),
        key_down=lambda _k: None,
        key_up=lambda _k: None,
        move_relative=lambda *_: None,
    )
    world = PoseResult(0.22, 0.28, -90.0, 0.9, True, 40, "world", place_id="tunnel")
    r0 = ctrl.tick(world, now=1.0, paused=False, radar_progressing=True)
    assert r0.path
    r1 = ctrl.tick(world, now=1.5, paused=True, radar_progressing=False)
    assert r1.state == NavState.PAUSED
    assert r1.path == r0.path or ctrl.path_label == r0.path


def test_controller_aborts_macro_when_world_returns() -> None:
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
        allow_macro_fallback=True,
        place_wait_sec=2.0,
    )
    centered = PoseResult(0.5, 0.5, -90.0, 0.9, True, 40, "centered")
    r1 = ctrl.tick(centered, now=1.0, paused=False)
    assert r1.state == NavState.WAIT_PLACE
    r2 = ctrl.tick(centered, now=3.5, paused=False)
    assert r2.state == NavState.MACRO_FALLBACK
    assert r2.use_macro_patrol is True
    world = PoseResult(0.52, 0.48, -90.0, 0.9, True, 40, "world")
    r3 = ctrl.tick(world, now=4.0, paused=False, radar_progressing=True)
    assert r3.state in (NavState.SEEK_GOAL, NavState.AT_GOAL)
    assert r3.use_macro_patrol is False
    assert r3.pose_mode == "world"


def test_controller_no_macro_when_disabled() -> None:
    pack = load_nav_pack(resolve_nav_pack_path("dust2_dm"))
    ctrl = NavController(
        pack,
        FOVMouseMovement(
            screen=CaptureRegion(width=1280, height=720),
            fov=FOVConfig(horizontal=106.26, vertical=73.74, x360=16364),
        ),
        key_down=lambda _k: None,
        key_up=lambda _k: None,
        move_relative=lambda *_: None,
        allow_macro_fallback=False,
        place_wait_sec=2.0,
    )
    centered = PoseResult(0.5, 0.5, -90.0, 0.9, True, 40, "centered")
    ctrl.tick(centered, now=1.0, paused=False)
    r = ctrl.tick(centered, now=4.0, paused=False)
    assert r.state == NavState.WAIT_PLACE
    assert r.use_macro_patrol is False
