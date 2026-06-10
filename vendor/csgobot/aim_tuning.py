"""Resolve aim parameters from run.py defaults and environment overrides."""

from __future__ import annotations

import os

CSGO_YAW = 0.022


def x360_from_sensitivity(sensitivity: float, m_yaw: float = CSGO_YAW) -> int:
    """Mouse counts for a 360° turn at given CS2 sensitivity."""
    if sensitivity <= 0:
        raise ValueError("sensitivity must be positive")
    return int(round(360.0 / (m_yaw * sensitivity)))


def resolve_x360(default: int) -> int:
    """
    Priority: CSGOBOT_X360 > CS2_SENSITIVITY > default from run.py.
    """
    raw = os.environ.get("CSGOBOT_X360", "").strip()
    if raw:
        return max(1, int(float(raw)))

    sens = os.environ.get("CS2_SENSITIVITY", "").strip()
    if sens:
        return x360_from_sensitivity(float(sens))

    return default


def resolve_smoothing(default: float) -> float:
    raw = os.environ.get("CSGOBOT_SMOOTHING", "").strip()
    if raw:
        return max(1.0, float(raw))
    return default


def resolve_dead_zone(default: float) -> float:
    raw = os.environ.get("CSGOBOT_DEAD_ZONE", "").strip()
    if raw:
        return max(0.0, float(raw))
    return default


def aim_debug_enabled() -> bool:
    return os.environ.get("CSGOBOT_AIM_DEBUG", "").lower() in ("1", "true", "yes")
