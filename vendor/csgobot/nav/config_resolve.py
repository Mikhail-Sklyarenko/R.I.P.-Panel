"""Environment overrides for minimap navigation (PR-N0/N1)."""

from __future__ import annotations

import os

from config import NavConfig


def _env_bool(name: str) -> bool | None:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return None
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


def _env_float(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    return float(raw)


def nav_debug_enabled() -> bool:
    return os.environ.get("CSGOBOT_NAV_DEBUG", "").lower() in ("1", "true", "yes")


def resolve_nav_enabled(default: bool) -> bool:
    val = _env_bool("CSGOBOT_NAV")
    return default if val is None else val


def resolve_nav_config(default: NavConfig) -> NavConfig:
    pack = os.environ.get("CSGOBOT_NAV_PACK", "").strip()
    cal_path = os.environ.get("CSGOBOT_NAV_CALIBRATION", "").strip()
    debug_iv = _env_float("CSGOBOT_NAV_DEBUG_INTERVAL")
    read_only = _env_bool("CSGOBOT_NAV_READ_ONLY")
    pose_lost = _env_float("CSGOBOT_NAV_POSE_LOST_SEC")
    metrics_iv = _env_float("CSGOBOT_NAV_METRICS_INTERVAL")
    return NavConfig(
        enabled=resolve_nav_enabled(default.enabled),
        read_only=default.read_only if read_only is None else read_only,
        debug=nav_debug_enabled() or default.debug,
        pack_id=pack or default.pack_id,
        calibration_path=cal_path or default.calibration_path,
        debug_log_interval_sec=(
            debug_iv if debug_iv is not None else default.debug_log_interval_sec
        ),
        pose_lost_fallback_sec=(
            pose_lost if pose_lost is not None else default.pose_lost_fallback_sec
        ),
        metrics_log_interval_sec=(
            metrics_iv if metrics_iv is not None else default.metrics_log_interval_sec
        ),
    )
