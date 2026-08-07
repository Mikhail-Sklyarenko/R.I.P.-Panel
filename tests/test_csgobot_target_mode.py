"""DM FFA target mode vs team opposite-side filter."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"
if str(_CSGOBOT) not in sys.path:
    sys.path.insert(0, str(_CSGOBOT))

from aim_tuning import resolve_target_mode  # noqa: E402
from aiming.target_selector import TargetSelector  # noqa: E402
from config import ALL_PLAYER_CLASSES, AimConfig, CaptureRegion, Team  # noqa: E402


def _dets_both_sides() -> dict:
    return {
        "c": [{"xyxy": [100, 100, 140, 220], "conf": 0.9, "cls": 0}],
        "ch": [{"xyxy": [110, 90, 130, 110], "conf": 0.85, "cls": 1}],
        "t": [{"xyxy": [600, 100, 640, 220], "conf": 0.88, "cls": 2}],
        "th": [{"xyxy": [610, 90, 630, 110], "conf": 0.8, "cls": 3}],
    }


def test_ffa_enemy_classes_are_all_players() -> None:
    cfg = AimConfig(current_team=Team.CT, target_mode="ffa")
    assert cfg.enemy_classes == ALL_PLAYER_CLASSES
    cfg.current_team = Team.T
    assert cfg.enemy_classes == ALL_PLAYER_CLASSES


def test_team_mode_opposite_only() -> None:
    ct = AimConfig(current_team=Team.CT, target_mode="team")
    assert ct.enemy_classes == ("t", "th")
    t = AimConfig(current_team=Team.T, target_mode="team")
    assert t.enemy_classes == ("c", "ch")


def test_ffa_filter_includes_both_sides() -> None:
    sel = TargetSelector(
        AimConfig(current_team=Team.CT, target_mode="ffa"),
        CaptureRegion(width=1280, height=720),
    )
    enemies = sel.filter_enemies(_dets_both_sides())
    classes = {e.class_name for e in enemies}
    assert classes == {"c", "ch", "t", "th"}


def test_team_ct_filter_excludes_ct_models() -> None:
    sel = TargetSelector(
        AimConfig(current_team=Team.CT, target_mode="team"),
        CaptureRegion(width=1280, height=720),
    )
    enemies = sel.filter_enemies(_dets_both_sides())
    classes = {e.class_name for e in enemies}
    assert classes == {"t", "th"}


def test_team_t_filter_excludes_t_models() -> None:
    sel = TargetSelector(
        AimConfig(current_team=Team.T, target_mode="team"),
        CaptureRegion(width=1280, height=720),
    )
    enemies = sel.filter_enemies(_dets_both_sides())
    classes = {e.class_name for e in enemies}
    assert classes == {"c", "ch"}


def test_ffa_select_best_can_pick_same_side_model() -> None:
    """Playing CT in FFA: nearest CT body is a valid target."""
    sel = TargetSelector(
        AimConfig(current_team=Team.CT, target_mode="ffa"),
        CaptureRegion(width=1280, height=720),
    )
    detections = {
        "c": [{"xyxy": [620, 300, 680, 420], "conf": 0.9, "cls": 0}],
        "t": [{"xyxy": [100, 100, 160, 260], "conf": 0.95, "cls": 2}],
    }
    target = sel.select_best_target(detections, max_distance=400)
    assert target is not None
    assert target.class_name == "c"


def test_resolve_target_mode_env() -> None:
    os.environ["CSGOBOT_TARGET_MODE"] = "team"
    try:
        assert resolve_target_mode("ffa") == "team"
    finally:
        os.environ.pop("CSGOBOT_TARGET_MODE", None)
    os.environ["CSGOBOT_TARGET_MODE"] = "nope"
    try:
        assert resolve_target_mode("ffa") == "ffa"
    finally:
        os.environ.pop("CSGOBOT_TARGET_MODE", None)


def test_create_config_defaults_ffa(monkeypatch) -> None:
    monkeypatch.delenv("CSGOBOT_TARGET_MODE", raising=False)
    from run import create_config

    cfg = create_config()
    assert cfg.aim.target_mode == "ffa"
    assert cfg.aim.enemy_classes == ALL_PLAYER_CLASSES
    assert cfg.team_detect.manual_override_sec == 30.0
