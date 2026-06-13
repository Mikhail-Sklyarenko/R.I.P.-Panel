"""Center ROI crop detect fallback for small distant enemies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from detectors.base import BaseDetector


@dataclass
class RoiDetectConfig:
    enabled: bool = True
    fraction: float = 0.75


def crop_center(
    img: np.ndarray,
    fraction: float,
) -> tuple[np.ndarray, int, int]:
    """Return center crop and (offset_x, offset_y) in full-frame coords."""
    fraction = max(0.25, min(1.0, fraction))
    h, w = img.shape[:2]
    crop_w = max(32, int(w * fraction))
    crop_h = max(32, int(h * fraction))
    x0 = (w - crop_w) // 2
    y0 = (h - crop_h) // 2
    return img[y0 : y0 + crop_h, x0 : x0 + crop_w].copy(), x0, y0


def remap_detections(
    detections: dict[str, list[dict[str, Any]]],
    offset_x: int,
    offset_y: int,
) -> dict[str, list[dict[str, Any]]]:
    if not offset_x and not offset_y:
        return detections
    out: dict[str, list[dict[str, Any]]] = {}
    for class_name, boxes in detections.items():
        shifted: list[dict[str, Any]] = []
        for box in boxes:
            x1, y1, x2, y2 = box["xyxy"]
            shifted.append(
                {
                    **box,
                    "xyxy": [
                        x1 + offset_x,
                        y1 + offset_y,
                        x2 + offset_x,
                        y2 + offset_y,
                    ],
                }
            )
        out[class_name] = shifted
    return out


def merge_detections(
    primary: dict[str, list[dict[str, Any]]],
    secondary: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    merged: dict[str, list[dict[str, Any]]] = {
        k: list(v) for k, v in primary.items()
    }
    for class_name, boxes in secondary.items():
        merged.setdefault(class_name, []).extend(boxes)
    return merged


def count_enemy_detections(
    detections: dict[str, list[dict[str, Any]]],
    enemy_classes: tuple[str, ...],
) -> int:
    total = 0
    for class_name in enemy_classes:
        total += len(detections.get(class_name, []))
    return total


def detect_roi_pass(
    detector: BaseDetector,
    img: np.ndarray,
    fraction: float,
) -> dict[str, list[dict[str, Any]]]:
    crop, ox, oy = crop_center(img, fraction)
    if crop.size == 0:
        return {}
    return remap_detections(detector.detect(crop), ox, oy)


def detect_with_roi_fallback(
    detector: BaseDetector,
    img: np.ndarray,
    *,
    roi_config: RoiDetectConfig,
    enemy_classes: tuple[str, ...],
    min_enemy_count: int = 1,
) -> tuple[dict[str, list[dict[str, Any]]], bool]:
    """
    Full-frame detect; optional center ROI second pass if too few enemies.
    """
    detections = detector.detect(img)
    if not roi_config.enabled:
        return detections, False

    if count_enemy_detections(detections, enemy_classes) >= min_enemy_count:
        return detections, False

    roi_detections = detect_roi_pass(detector, img, roi_config.fraction)
    if count_enemy_detections(roi_detections, enemy_classes) < 1:
        return detections, False

    return merge_detections(detections, roi_detections), True
