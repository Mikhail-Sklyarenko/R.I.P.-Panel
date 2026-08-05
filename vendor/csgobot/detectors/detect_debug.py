"""Optional detection debug logging."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("DetectionProcess")


def detect_debug_enabled() -> bool:
    return os.environ.get("CSGOBOT_DETECT_DEBUG", "").lower() in (
        "1",
        "true",
        "yes",
    )


def log_detect_status(
    *,
    detections: dict[str, list[dict[str, Any]]],
    enemy_classes: tuple[str, ...],
    roi_used: bool,
    activated: bool,
    now: float,
    last_log: float,
    interval_sec: float = 3.0,
) -> float:
    """Periodic detect summary; returns updated last_log time."""
    if not detect_debug_enabled() or now - last_log < interval_sec:
        return last_log

    enemies: list[dict[str, Any]] = []
    for class_name in enemy_classes:
        for box in detections.get(class_name, []):
            x1, y1, x2, y2 = box["xyxy"]
            enemies.append(
                {
                    "cls": class_name,
                    "conf": float(box.get("conf", 0.0)),
                    "h": float(y2 - y1),
                }
            )

    if enemies:
        best = max(enemies, key=lambda e: e["conf"])
        logger.info(
            "detect: enemies=%d roi=%s best=%s conf=%.2f bbox_h=%.0f",
            len(enemies),
            roi_used,
            best["cls"],
            best["conf"],
            best["h"],
        )
    elif activated:
        logger.info(
            "detect: no enemies (roi=%s) — try CSGOBOT_CONFIDENCE=0.45 "
            "or per-class CSGOBOT_CONF_C/CH/T/TH",
            roi_used,
        )
    return now
