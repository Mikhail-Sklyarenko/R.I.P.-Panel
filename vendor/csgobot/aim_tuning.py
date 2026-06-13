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
    """Legacy single dead zone → aim_dead_zone_high."""
    raw = os.environ.get("CSGOBOT_DEAD_ZONE", "").strip()
    if raw:
        return max(0.0, float(raw))
    return default


def resolve_aim_dead_zone_high(default: float, legacy: float) -> float:
    raw = os.environ.get("CSGOBOT_AIM_DEAD_ZONE_HIGH", "").strip()
    if raw:
        return max(0.0, float(raw))
    dz = os.environ.get("CSGOBOT_DEAD_ZONE", "").strip()
    if dz:
        return max(0.0, float(dz))
    return default if default > 0 else legacy


def resolve_aim_dead_zone_low(default: float, high: float) -> float:
    raw = os.environ.get("CSGOBOT_AIM_DEAD_ZONE_LOW", "").strip()
    if raw:
        return max(0.0, float(raw))
    if default > 0:
        return default
    return round(high * 0.65, 1)


def resolve_shoot_dead_zone(default: float) -> float:
    raw = os.environ.get("CSGOBOT_SHOOT_DEAD_ZONE", "").strip()
    if raw:
        return max(0.0, float(raw))
    return default


def resolve_aim_smooth_enabled(default: bool) -> bool:
    val = _env_bool("CSGOBOT_AIM_SMOOTH")
    return default if val is None else val


def resolve_aim_smooth_alpha(default: float) -> float:
    raw = os.environ.get("CSGOBOT_AIM_SMOOTH_ALPHA", "").strip()
    if raw:
        return max(0.05, min(1.0, float(raw)))
    return default


def resolve_mouse_max_delta(default: int) -> int:
    raw = os.environ.get("CSGOBOT_MOUSE_MAX_DELTA", "").strip()
    if raw:
        return max(1, int(float(raw)))
    return default


def resolve_mouse_min_delta(default: int) -> int:
    raw = os.environ.get("CSGOBOT_MOUSE_MIN_DELTA", "").strip()
    if raw:
        return max(0, int(float(raw)))
    return default


def resolve_lead_variance_gate(default: bool) -> bool:
    val = _env_bool("CSGOBOT_LEAD_VARIANCE_GATE")
    return default if val is None else val


def resolve_lead_min_speed(default: float) -> float:
    raw = os.environ.get("CSGOBOT_LEAD_MIN_SPEED", "").strip()
    if raw:
        return max(0.0, float(raw))
    return default


def aim_debug_enabled() -> bool:
    return os.environ.get("CSGOBOT_AIM_DEBUG", "").lower() in ("1", "true", "yes")


def _env_bool(name: str) -> bool | None:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return None
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


def resolve_confidence(default: float) -> float:
    raw = os.environ.get("CSGOBOT_CONFIDENCE", "").strip()
    if raw:
        return max(0.05, min(1.0, float(raw)))
    return default


def resolve_prioritize_heads(default: bool) -> bool:
    val = _env_bool("CSGOBOT_PRIORITIZE_HEADS")
    return default if val is None else val


def resolve_max_assist_distance(default: int) -> int:
    raw = os.environ.get("CSGOBOT_MAX_DIST", "").strip()
    if raw:
        return max(50, int(float(raw)))
    return default


def resolve_min_bbox_height_for_head(default: float) -> float:
    raw = os.environ.get("CSGOBOT_MIN_BBOX_HEIGHT", "").strip()
    if raw:
        return max(4.0, float(raw))
    return default


def resolve_long_range_body_bias(default: bool) -> bool:
    val = _env_bool("CSGOBOT_LONG_RANGE_BODY")
    return default if val is None else val


def resolve_roi_enabled(default: bool) -> bool:
    val = _env_bool("CSGOBOT_ROI_ZOOM")
    return default if val is None else val


def resolve_roi_fraction(default: float) -> float:
    raw = os.environ.get("CSGOBOT_ROI_FRACTION", "").strip()
    if raw:
        return max(0.25, min(1.0, float(raw)))
    return default


def resolve_lead_enabled(default: bool) -> bool:
    val = _env_bool("CSGOBOT_LEAD_ENABLED")
    return default if val is None else val


def resolve_lead_ms(default: float) -> float:
    raw = os.environ.get("CSGOBOT_LEAD_MS", "").strip()
    if raw:
        return max(0.0, float(raw))
    return default


def resolve_adaptive_smoothing(default: bool) -> bool:
    val = _env_bool("CSGOBOT_ADAPTIVE_SMOOTHING")
    return default if val is None else val


def resolve_shoot_mode(default: str) -> str:
    raw = os.environ.get("CSGOBOT_SHOOT_MODE", "").strip().lower()
    if raw in ("tap", "burst", "hold"):
        return raw
    return default


def resolve_burst_size(default: int) -> int:
    raw = os.environ.get("CSGOBOT_BURST_SIZE", "").strip()
    if raw:
        return max(1, int(float(raw)))
    return default


def resolve_burst_gap_sec(default: float) -> float:
    raw = os.environ.get("CSGOBOT_BURST_GAP_MS", "").strip()
    if raw:
        return max(0.0, float(raw)) / 1000.0
    return default


def resolve_burst_shot_interval_sec(default: float) -> float:
    raw = os.environ.get("CSGOBOT_BURST_INTERVAL_MS", "").strip()
    if raw:
        return max(0.02, float(raw)) / 1000.0
    return default


def resolve_hold_max_sec(default: float) -> float:
    raw = os.environ.get("CSGOBOT_HOLD_MAX_MS", "").strip()
    if raw:
        return max(0.05, float(raw)) / 1000.0
    return default


def resolve_hold_repress_gap_sec(default: float) -> float:
    raw = os.environ.get("CSGOBOT_HOLD_GAP_MS", "").strip()
    if raw:
        return max(0.0, float(raw)) / 1000.0
    return default


def resolve_hold_release_grace_sec(default: float) -> float:
    raw = os.environ.get("CSGOBOT_HOLD_RELEASE_GRACE_MS", "").strip()
    if raw:
        return max(0.0, float(raw)) / 1000.0
    return default


def resolve_shoot_cooldown_sec(default: float) -> float:
    raw = os.environ.get("CSGOBOT_SHOOT_COOLDOWN_MS", "").strip()
    if raw:
        return max(0.02, float(raw)) / 1000.0
    return default


def resolve_body_fallback_sec(default: float) -> float:
    raw = os.environ.get("CSGOBOT_BODY_FALLBACK_MS", "").strip()
    if raw:
        return max(0.0, float(raw)) / 1000.0
    return default


def adaptive_smoothing(
    base: float,
    pixel_distance: float,
    fps: float,
    *,
    max_distance: float = 300.0,
) -> float:
    """
    Scale smoothing by target distance and detector FPS.

    Far targets → lower smoothing (faster snap). Close → higher (precision).
    Low FPS → higher smoothing (less overshoot per frame).
    """
    base = max(1.0, base)
    if max_distance <= 0:
        max_distance = 300.0

    dist_norm = min(1.0, max(0.0, pixel_distance / max_distance))
    # far: *0.65, close: *1.25
    dist_factor = 1.25 - 0.6 * dist_norm

    fps_factor = 1.0
    if fps > 0:
        if fps < 15:
            fps_factor = 1.45
        elif fps < 25:
            fps_factor = 1.2
        elif fps > 35:
            fps_factor = 0.88

    return max(1.0, base * dist_factor * fps_factor)
