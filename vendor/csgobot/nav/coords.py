"""Coordinate helpers for minimap and map landmarks."""

from __future__ import annotations

import math


def normalize_angle_deg(angle: float) -> float:
    """Wrap angle to [-180, 180)."""
    while angle >= 180.0:
        angle -= 360.0
    while angle < -180.0:
        angle += 360.0
    return angle


def pixel_to_norm(
    px: float,
    py: float,
    *,
    rect_x: int,
    rect_y: int,
    rect_w: int,
    rect_h: int,
) -> tuple[float, float]:
    """Map frame pixel to normalized coords inside minimap rect."""
    local_x = px - rect_x
    local_y = py - rect_y
    x_norm = local_x / max(rect_w, 1)
    y_norm = local_y / max(rect_h, 1)
    return (
        max(0.0, min(1.0, x_norm)),
        max(0.0, min(1.0, y_norm)),
    )


def bearing_deg(
    from_x: float,
    from_y: float,
    to_x: float,
    to_y: float,
) -> float:
    """Compass bearing in degrees (0 = east, 90 = south in image coords)."""
    dx = to_x - from_x
    dy = to_y - from_y
    # Image y grows downward; negate dy for compass-up convention.
    return math.degrees(math.atan2(dy, dx))


def dist_norm(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.hypot(x2 - x1, y2 - y1)
