"""Combat detection wrapper: full frame + optional ROI fallback."""

from __future__ import annotations

from typing import Any

from config import AimConfig, DetectorConfig
from detectors.base import BaseDetector
from detectors.roi_detect import RoiDetectConfig, detect_with_roi_fallback


def run_combat_detection(
    detector: BaseDetector,
    img: Any,
    detector_config: DetectorConfig,
    aim_config: AimConfig,
) -> tuple[dict[str, list[dict[str, Any]]], bool]:
    """Run YOLO on full frame; ROI center crop if no enemy detections."""
    roi = RoiDetectConfig(
        enabled=detector_config.roi_enabled,
        fraction=detector_config.roi_fraction,
    )
    return detect_with_roi_fallback(
        detector,
        img,
        roi_config=roi,
        enemy_classes=aim_config.enemy_classes,
        class_conf_thresholds=detector_config.class_confidence_thresholds,
        min_enemy_count=1,
    )
