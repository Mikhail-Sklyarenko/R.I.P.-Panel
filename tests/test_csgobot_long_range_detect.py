"""PR-6f: long-range detection — ROI fallback, body bias, env defaults."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"
if str(_CSGOBOT) not in sys.path:
    sys.path.insert(0, str(_CSGOBOT))

from aim_tuning import (  # noqa: E402
    resolve_class_confidence_thresholds,
    resolve_long_range_body_bias,
    resolve_min_bbox_height_for_head,
    resolve_roi_enabled,
    resolve_roi_fraction,
)
from aiming.target_selector import TargetSelector  # noqa: E402
from config import AimConfig, CaptureRegion  # noqa: E402
from detectors.roi_detect import (  # noqa: E402
    RoiDetectConfig,
    apply_class_conf_thresholds,
    crop_center,
    detect_with_roi_fallback,
    merge_detections,
    remap_detections,
)


class _MockDetector:
    def __init__(self, responses: list[dict[str, list[dict[str, Any]]]]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def detect(self, img: np.ndarray, verbose: bool = False) -> dict:
        result = self._responses[self.calls]
        self.calls += 1
        return result


def test_crop_center_offsets() -> None:
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    crop, ox, oy = crop_center(img, 0.75)
    assert crop.shape == (540, 960, 3)
    assert ox == 160
    assert oy == 90


def test_remap_detections_shifts_xyxy() -> None:
    dets = {"t": [{"xyxy": [10, 20, 30, 40], "conf": 0.8}]}
    out = remap_detections(dets, 100, 50)
    assert out["t"][0]["xyxy"] == [110, 70, 130, 90]


def test_merge_detections_combines_classes() -> None:
    primary = {"t": [{"xyxy": [1, 2, 3, 4], "conf": 0.5}]}
    secondary = {
        "t": [{"xyxy": [5, 6, 7, 8], "conf": 0.6}],
        "th": [{"xyxy": [9, 10, 11, 12], "conf": 0.7}],
    }
    merged = merge_detections(primary, secondary)
    assert len(merged["t"]) == 2
    assert len(merged["th"]) == 1


def test_roi_fallback_triggers_on_empty_full_frame() -> None:
    crop_enemy = {"xyxy": [340, 210, 400, 330], "conf": 0.55, "cls": 2}
    detector = _MockDetector([{}, {"t": [crop_enemy]}])
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    roi = RoiDetectConfig(enabled=True, fraction=0.75)

    dets, roi_used = detect_with_roi_fallback(
        detector,
        img,
        roi_config=roi,
        enemy_classes=("t", "th"),
    )

    assert roi_used is True
    assert detector.calls == 2
    assert dets["t"][0]["xyxy"] == [500, 300, 560, 420]


def test_roi_skipped_when_full_frame_has_enemy() -> None:
    enemy = {"xyxy": [400, 200, 460, 320], "conf": 0.6, "cls": 2}
    detector = _MockDetector([{"t": [enemy]}])
    img = np.zeros((720, 1280, 3), dtype=np.uint8)

    dets, roi_used = detect_with_roi_fallback(
        detector,
        img,
        roi_config=RoiDetectConfig(enabled=True),
        enemy_classes=("t", "th"),
    )

    assert roi_used is False
    assert detector.calls == 1
    assert dets["t"][0]["xyxy"] == enemy["xyxy"]


def test_roi_disabled_single_pass() -> None:
    detector = _MockDetector([{}])
    img = np.zeros((720, 1280, 3), dtype=np.uint8)

    _, roi_used = detect_with_roi_fallback(
        detector,
        img,
        roi_config=RoiDetectConfig(enabled=False),
        enemy_classes=("t", "th"),
    )

    assert roi_used is False
    assert detector.calls == 1


def test_apply_class_conf_thresholds_keeps_only_qualified() -> None:
    dets = {
        "c": [{"xyxy": [1, 1, 2, 2], "conf": 0.41}],
        "ch": [{"xyxy": [1, 1, 2, 2], "conf": 0.39}],
        "t": [{"xyxy": [1, 1, 2, 2], "conf": 0.49}],
    }
    out = apply_class_conf_thresholds(
        dets,
        {"c": 0.40, "ch": 0.40, "t": 0.50},
    )
    assert "c" in out
    assert "ch" not in out
    assert "t" not in out


def test_roi_fallback_uses_class_specific_conf() -> None:
    low_ct = {"xyxy": [340, 210, 400, 330], "conf": 0.41, "cls": 0}
    detector = _MockDetector([{}, {"c": [low_ct]}])
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    dets, roi_used = detect_with_roi_fallback(
        detector,
        img,
        roi_config=RoiDetectConfig(enabled=True, fraction=0.75),
        enemy_classes=("c", "ch"),
        class_conf_thresholds={"c": 0.40},
    )
    assert roi_used is True
    assert detector.calls == 2
    assert "c" in dets


def test_body_bias_skips_tiny_head() -> None:
    cfg = AimConfig(
        prioritize_heads=True,
        long_range_body_bias=True,
        min_bbox_height_for_head=28.0,
    )
    selector = TargetSelector(cfg, CaptureRegion(width=1280, height=720))
    detections = {
        "th": [{"xyxy": [600, 300, 620, 318], "conf": 0.9, "cls": 3}],
        "t": [{"xyxy": [590, 320, 650, 480], "conf": 0.85, "cls": 2}],
    }
    target = selector.select_best_target(detections, max_distance=400)
    assert target is not None
    assert not target.is_head


def test_body_bias_keeps_large_head() -> None:
    cfg = AimConfig(
        prioritize_heads=True,
        long_range_body_bias=True,
        min_bbox_height_for_head=28.0,
    )
    selector = TargetSelector(cfg, CaptureRegion(width=1280, height=720))
    detections = {
        "th": [{"xyxy": [620, 330, 660, 370], "conf": 0.9, "cls": 3}],
        "t": [{"xyxy": [100, 100, 160, 260], "conf": 0.85, "cls": 2}],
    }
    target = selector.select_best_target(detections, max_distance=400)
    assert target is not None
    assert target.is_head


def test_env_resolvers_6f(monkeypatch) -> None:
    monkeypatch.setenv("CSGOBOT_MIN_BBOX_HEIGHT", "32")
    monkeypatch.setenv("CSGOBOT_LONG_RANGE_BODY", "0")
    monkeypatch.setenv("CSGOBOT_ROI_ZOOM", "0")
    monkeypatch.setenv("CSGOBOT_ROI_FRACTION", "0.6")

    assert resolve_min_bbox_height_for_head(28.0) == 32.0
    assert resolve_long_range_body_bias(True) is False
    assert resolve_roi_enabled(True) is False
    assert resolve_roi_fraction(0.75) == 0.6


def test_env_resolve_class_conf_thresholds(monkeypatch) -> None:
    monkeypatch.setenv("CSGOBOT_CONF_C", "0.38")
    monkeypatch.setenv("CSGOBOT_CONF_CH", "0.42")
    monkeypatch.setenv("CSGOBOT_CONF_T", "0.55")
    monkeypatch.setenv("CSGOBOT_CONF_TH", "0.58")
    out = resolve_class_confidence_thresholds()
    assert out == {"c": 0.38, "ch": 0.42, "t": 0.55, "th": 0.58}


def test_create_config_6f_defaults(monkeypatch) -> None:
    for key in (
        "CSGOBOT_CONFIDENCE",
        "CSGOBOT_CONF_C",
        "CSGOBOT_CONF_CH",
        "CSGOBOT_CONF_T",
        "CSGOBOT_CONF_TH",
        "CSGOBOT_PRIORITIZE_HEADS",
        "CSGOBOT_MAX_DIST",
        "CSGOBOT_ROI_ZOOM",
        "CSGOBOT_MIN_BBOX_HEIGHT",
    ):
        monkeypatch.delenv(key, raising=False)

    from run import create_config  # noqa: E402

    cfg = create_config()
    assert cfg.detector.confidence_threshold == 0.50
    assert cfg.detector.class_confidence_thresholds == {}
    assert cfg.aim.prioritize_heads is True
    assert cfg.aim.head_aim_min_conf == 0.8
    assert cfg.aim.max_assist_distance == 320
    assert cfg.detector.roi_enabled is True
    assert cfg.detector.roi_fraction == 0.75
    assert cfg.aim.min_bbox_height_for_head == 28.0
    assert cfg.aim.long_range_body_bias is True


def test_create_config_class_conf_runtime_floor(monkeypatch) -> None:
    monkeypatch.setenv("CSGOBOT_CONFIDENCE", "0.50")
    monkeypatch.setenv("CSGOBOT_CONF_C", "0.38")
    monkeypatch.setenv("CSGOBOT_CONF_CH", "0.40")
    from run import create_config  # noqa: E402

    cfg = create_config()
    assert cfg.detector.confidence_threshold == 0.38
    assert cfg.detector.class_confidence_thresholds["c"] == 0.38
    assert cfg.detector.class_confidence_thresholds["ch"] == 0.40
