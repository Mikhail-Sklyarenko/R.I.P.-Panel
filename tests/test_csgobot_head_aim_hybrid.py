"""PR-H1: hybrid head aim — conf≥0.8 + large bbox; body @ long range."""

from __future__ import annotations

import sys
from pathlib import Path

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"
if str(_CSGOBOT) not in sys.path:
    sys.path.append( str(_CSGOBOT))

from aim_tuning import resolve_head_aim_min_conf  # noqa: E402
from aiming.target_selector import TargetSelector  # noqa: E402
from config import AimConfig, CaptureRegion  # noqa: E402


def _selector(**aim_kw: object) -> TargetSelector:
    cfg = AimConfig(current_team=__import__("config", fromlist=["Team"]).Team.CT, **aim_kw)
    return TargetSelector(cfg, CaptureRegion(width=1280, height=720))


def test_high_conf_large_head_preferred() -> None:
    selector = _selector(
        prioritize_heads=True,
        head_aim_min_conf=0.8,
        long_range_body_bias=True,
        min_bbox_height_for_head=28.0,
    )
    detections = {
        "th": [{"xyxy": [620, 330, 660, 370], "conf": 0.85, "cls": 3}],
        "t": [{"xyxy": [100, 100, 160, 260], "conf": 0.9, "cls": 2}],
    }
    target = selector.select_best_target(detections, max_distance=400)
    assert target is not None
    assert target.is_head


def test_low_conf_head_falls_back_to_body() -> None:
    selector = _selector(
        prioritize_heads=True,
        head_aim_min_conf=0.8,
    )
    detections = {
        "th": [{"xyxy": [620, 330, 660, 370], "conf": 0.72, "cls": 3}],
        "t": [{"xyxy": [600, 320, 660, 480], "conf": 0.85, "cls": 2}],
    }
    target = selector.select_best_target(detections, max_distance=400)
    assert target is not None
    assert not target.is_head


def test_tiny_head_at_range_skipped_for_body() -> None:
    selector = _selector(
        prioritize_heads=True,
        head_aim_min_conf=0.8,
        long_range_body_bias=True,
        min_bbox_height_for_head=28.0,
    )
    detections = {
        "th": [{"xyxy": [600, 300, 620, 316], "conf": 0.9, "cls": 3}],
        "t": [{"xyxy": [590, 320, 650, 480], "conf": 0.85, "cls": 2}],
    }
    target = selector.select_best_target(detections, max_distance=400)
    assert target is not None
    assert not target.is_head


def test_prioritize_heads_off_uses_nearest() -> None:
    selector = _selector(prioritize_heads=False)
    detections = {
        "th": [{"xyxy": [620, 330, 660, 370], "conf": 0.95, "cls": 3}],
        "t": [{"xyxy": [600, 320, 660, 480], "conf": 0.85, "cls": 2}],
    }
    target = selector.select_best_target(detections, max_distance=400)
    assert target is not None
    assert target.is_head


def test_qualifying_heads_filters_conf_and_height() -> None:
    selector = _selector(head_aim_min_conf=0.8, min_bbox_height_for_head=28.0)
    enemies = selector.filter_enemies(
        {
            "th": [
                {"xyxy": [600, 300, 640, 340], "conf": 0.85, "cls": 3},
                {"xyxy": [600, 300, 618, 316], "conf": 0.9, "cls": 3},
                {"xyxy": [600, 300, 640, 340], "conf": 0.7, "cls": 3},
            ],
        }
    )
    qualified = selector._qualifying_heads(enemies)
    assert len(qualified) == 1
    assert qualified[0].confidence == 0.85


def test_resolve_head_aim_min_conf_env(monkeypatch) -> None:
    monkeypatch.setenv("CSGOBOT_HEAD_AIM_MIN_CONF", "0.75")
    assert resolve_head_aim_min_conf(0.8) == 0.75


def test_create_config_h1_defaults(monkeypatch) -> None:
    monkeypatch.delenv("CSGOBOT_PRIORITIZE_HEADS", raising=False)
    monkeypatch.delenv("CSGOBOT_HEAD_AIM_MIN_CONF", raising=False)
    from run import create_config  # noqa: E402

    cfg = create_config()
    assert cfg.aim.prioritize_heads is True
    assert cfg.aim.head_aim_min_conf == 0.8
    assert cfg.aim.long_range_body_bias is True
