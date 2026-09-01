"""Load minimap HUD calibration YAML."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class NavCalibrationError(ValueError):
    pass


@dataclass(frozen=True)
class MinimapRect:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class PlayerIconConfig:
    mode: str
    rgb_min: tuple[int, int, int]
    rgb_max: tuple[int, int, int]
    min_area_px: int
    max_area_px: int
    prefer_center_px: float


@dataclass(frozen=True)
class MinimapCalibration:
    rect: MinimapRect
    shape: str
    center_x: int
    center_y: int
    radius_px: int
    player_icon: PlayerIconConfig


@dataclass(frozen=True)
class PoseFilterConfig:
    smooth_alpha: float
    lost_timeout_sec: float
    min_confidence: float


@dataclass(frozen=True)
class NavCalibration:
    profile: str
    resolution: tuple[int, int]
    minimap: MinimapCalibration
    pose: PoseFilterConfig


def _rgb_triplet(raw: Any, name: str) -> tuple[int, int, int]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        raise NavCalibrationError(f"{name} must be [r,g,b]")
    return (int(raw[0]), int(raw[1]), int(raw[2]))


def parse_calibration_data(data: dict[str, Any]) -> NavCalibration:
    meta = data.get("meta") or {}
    profile = str(meta.get("profile", "unknown"))
    res_raw = meta.get("resolution") or [1280, 720]
    resolution = (int(res_raw[0]), int(res_raw[1]))

    minimap_raw = data.get("minimap") or {}
    rect_raw = minimap_raw.get("rect") or {}
    rect = MinimapRect(
        x=int(rect_raw.get("x", 0)),
        y=int(rect_raw.get("y", 0)),
        w=int(rect_raw.get("w", 0)),
        h=int(rect_raw.get("h", 0)),
    )
    if rect.w <= 0 or rect.h <= 0:
        raise NavCalibrationError("minimap.rect must have positive w/h")

    center_raw = minimap_raw.get("center") or {}
    center_x = int(center_raw.get("x", rect.x + rect.w // 2))
    center_y = int(center_raw.get("y", rect.y + rect.h // 2))
    radius_px = int(minimap_raw.get("radius_px", min(rect.w, rect.h) // 2))

    icon_raw = minimap_raw.get("player_icon") or {}
    player_icon = PlayerIconConfig(
        mode=str(icon_raw.get("mode", "color_blob")),
        rgb_min=_rgb_triplet(icon_raw.get("rgb_min", [0, 170, 170]), "rgb_min"),
        rgb_max=_rgb_triplet(icon_raw.get("rgb_max", [160, 255, 255]), "rgb_max"),
        min_area_px=int(icon_raw.get("min_area_px", 5)),
        max_area_px=int(icon_raw.get("max_area_px", 90)),
        prefer_center_px=float(icon_raw.get("prefer_center_px", 18.0)),
    )

    pose_raw = data.get("pose") or {}
    pose = PoseFilterConfig(
        smooth_alpha=float(pose_raw.get("smooth_alpha", 0.35)),
        lost_timeout_sec=float(pose_raw.get("lost_timeout_sec", 0.8)),
        min_confidence=float(pose_raw.get("min_confidence", 0.35)),
    )

    return NavCalibration(
        profile=profile,
        resolution=resolution,
        minimap=MinimapCalibration(
            rect=rect,
            shape=str(minimap_raw.get("shape", "circle")),
            center_x=center_x,
            center_y=center_y,
            radius_px=radius_px,
            player_icon=player_icon,
        ),
        pose=pose,
    )


def load_calibration(path: Path) -> NavCalibration:
    if not path.is_file():
        raise NavCalibrationError(f"calibration not found: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise NavCalibrationError("calibration root must be a mapping")
    return parse_calibration_data(data)
