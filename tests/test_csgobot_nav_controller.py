"""Unit tests for minimap nav movement (PR-N2/N3)."""

from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


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
    entry = importlib.import_module("nav.entry_picker")
    g["pick_nearest_entry"] = entry.pick_nearest_entry
    g["should_use_entry"] = entry.should_use_entry
    g["compute_goal_follow"] = importlib.import_module("nav.goal_follower").compute_goal_follow
    g["NavMetrics"] = importlib.import_module("nav.metrics").NavMetrics
    pack = importlib.import_module("nav.pack")
    g["NavEntry"] = pack.NavEntry
    g["load_nav_pack"] = pack.load_nav_pack
    g["resolve_nav_pack_path"] = importlib.import_module("nav.paths").resolve_nav_pack_path
    g["PoseResult"] = importlib.import_module("nav.pose").PoseResult


def _fov_mouse():
    return FOVMouseMovement(
        screen=CaptureRegion(width=1280, height=720),
        fov=FOVConfig(horizontal=106.26, vertical=73.74, x360=16364),
    )


def _pack():
    return load_nav_pack(resolve_nav_pack_path("dust2_dm"))


def _controller(
    *,
    pose_lost_sec: float = 2.5,
):
    keys_down: list[str] = []
    keys_up: list[str] = []
    moves: list[tuple[int, int]] = []

    ctrl = NavController(
        _pack(),
        _fov_mouse(),
        key_down=keys_down.append,
        key_up=keys_up.append,
        move_relative=lambda dx, dy: moves.append((dx, dy)),
        pose_lost_sec=pose_lost_sec,
    )
    return ctrl, keys_down, keys_up, moves


def _pose(
    x: float,
    y: float,
    yaw: float,
    *,
    valid: bool = True,
):
    return PoseResult(x, y, yaw, 0.9, valid, 20)


def test_load_pack_has_entries_and_route_cycle() -> None:
    pack = _pack()
    assert pack.strategy == "route_cycle"
    assert len(pack.goals) == 2
    assert len(pack.entries) == 3
    assert pack.route.direct_goal_dist == 0.12


def test_pick_nearest_entry() -> None:
    pack = _pack()
    pose = _pose(0.20, 0.70, 0.0)
    entry = pick_nearest_entry(pose, pack.entries)
    assert entry is not None
    assert entry.id == "long_doors"


def test_should_use_entry_when_far_from_goal() -> None:
    pack = _pack()
    pose = _pose(0.20, 0.70, 0.0)
    assert should_use_entry(
        pose,
        pack.goal,
        pack.entries,
        direct_goal_dist=pack.route.direct_goal_dist,
    )


def test_should_skip_entry_when_near_goal() -> None:
    pack = _pack()
    pose = _pose(0.50, 0.50, 0.0)
    assert not should_use_entry(
        pose,
        pack.goal,
        pack.entries,
        direct_goal_dist=pack.route.direct_goal_dist,
    )


def test_compute_goal_follow_turns_toward_goal() -> None:
    pack = _pack()
    pose = _pose(0.2, 0.8, 0.0)
    out = compute_goal_follow(
        pose,
        pack.goal,
        pack.humanize,
        _fov_mouse(),
        dt_sec=1.0 / 60.0,
    )
    assert out.dist_to_goal > pack.goal.arrive_radius
    assert out.mouse_dx != 0 or out.mouse_dy != 0
    assert not out.forward


def test_compute_goal_follow_moves_forward_when_aligned() -> None:
    pack = _pack()
    pose = _pose(0.40, 0.60, -45.0)
    out = compute_goal_follow(
        pose,
        pack.goal,
        pack.humanize,
        _fov_mouse(),
        dt_sec=1.0 / 60.0,
    )
    assert out.forward


def test_nav_controller_seek_entry_when_far() -> None:
    ctrl, keys_down, _, moves = _controller()
    pose = _pose(0.20, 0.70, 0.0)
    result = ctrl.tick(pose, now=1.0, paused=False)
    assert result.state == NavState.SEEK_ENTRY
    assert result.target_id == "long_doors"
    assert result.entry_pick_event
    assert moves or keys_down


def test_nav_controller_seek_goal_when_near() -> None:
    ctrl, keys_down, _, moves = _controller()
    pose = _pose(0.44, 0.54, -37.0)
    result = ctrl.tick(pose, now=1.0, paused=False)
    assert result.state == NavState.SEEK_GOAL
    assert result.target_id == "mid"
    for i in range(12):
        ctrl.tick(pose, now=1.0 + i * 0.05, paused=False)
    assert keys_down or moves


def test_nav_controller_at_goal() -> None:
    ctrl, _, _, _ = _controller()
    pack = _pack()
    pose = _pose(pack.goal.x, pack.goal.y, 0.0)
    result = ctrl.tick(pose, now=1.0, paused=False)
    assert result.state == NavState.AT_GOAL
    assert result.dist_to_goal <= pack.goal.arrive_radius


def test_nav_controller_paused_releases_keys() -> None:
    ctrl, keys_down, keys_up, _ = _controller()
    pose = _pose(0.44, 0.54, -37.0)
    for i in range(12):
        ctrl.tick(pose, now=1.0 + i * 0.05, paused=False)
    assert keys_down
    result = ctrl.tick(pose, now=1.8, paused=True)
    assert result.state == NavState.PAUSED
    assert "w" in keys_up


def test_nav_controller_pose_lost_triggers_macro_fallback() -> None:
    ctrl, _, _, _ = _controller(pose_lost_sec=0.5)
    invalid = PoseResult.invalid()
    ctrl.tick(invalid, now=0.0, paused=False)
    result = ctrl.tick(invalid, now=0.6, paused=False)
    assert result.state == NavState.MACRO_FALLBACK
    assert result.use_macro_patrol
    assert result.fallback_event


def test_nav_controller_stuck_triggers_escape() -> None:
    ctrl, _, _, _ = _controller()
    pack = _pack()
    pose = _pose(0.44, 0.54, -37.0)
    now = 0.0
    result = None
    for _ in range(200):
        now += 0.05
        result = ctrl.tick(pose, now=now, paused=False)
        if result.state == NavState.STUCK_ESCAPE:
            break
    assert result is not None
    assert result.state == NavState.STUCK_ESCAPE
    assert result.stuck_event
    assert result.dist_to_goal > pack.goal.arrive_radius


def test_nav_controller_release_keys() -> None:
    ctrl, keys_down, keys_up, _ = _controller()
    pose = _pose(0.44, 0.54, -37.0)
    for i in range(12):
        ctrl.tick(pose, now=1.0 + i * 0.05, paused=False)
    assert keys_down
    ctrl.release_keys()
    assert "w" in keys_up


def test_nav_controller_reload_pack_switches_goal() -> None:
    ctrl, _, _, _ = _controller()
    assert ctrl.goal_id == "mid"
    mirage_pack = load_nav_pack(resolve_nav_pack_path("mirage_dm"))
    ctrl.reload_pack(mirage_pack)
    assert ctrl.goal_id == "mid"
    assert ctrl._pack.pack_id == "mirage_dm"


def test_nav_metrics_summary_and_log() -> None:
    metrics = NavMetrics(log_interval_sec=30.0)
    pose = _pose(0.44, 0.54, -37.0)
    result = NavController(
        _pack(),
        _fov_mouse(),
        key_down=lambda _: None,
        key_up=lambda _: None,
        move_relative=lambda *_: None,
    ).tick(pose, now=1.0, paused=False)

    metrics.observe_tick(
        result,
        pose,
        now=1.0,
        dt=0.016,
        goal_id=result.goal_id,
        target_id=result.target_id,
    )
    summary = metrics.summary(now=5.0)
    assert summary["goal_id"] == "mid"
    assert summary["stuck_events"] >= 0
    assert "pose_valid_pct" in summary

    logged: list[str] = []

    class _H(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            logged.append(record.getMessage())

    logger = logging.getLogger("test.nav.metrics")
    handler = _H()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    metrics.maybe_log(40.0, logger, force=True)
    logger.removeHandler(handler)
    assert logged
    assert "nav_metrics:" in logged[0]
    payload = json.loads(logged[0].split("nav_metrics: ", 1)[1])
    assert payload["goal_id"] == "mid"
