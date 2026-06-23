"""Environment overrides for patrol look (PR-L1)."""

from __future__ import annotations

import os

from config import LookConfig


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


def look_debug_enabled() -> bool:
    return os.environ.get("CSGOBOT_LOOK_DEBUG", "").lower() in ("1", "true", "yes")


def resolve_look_enabled(default: bool) -> bool:
    val = _env_bool("CSGOBOT_LOOK")
    return default if val is None else val


def resolve_look_config(default: LookConfig) -> LookConfig:
    yaw_min = _env_float("CSGOBOT_LOOK_YAW_MIN")
    yaw_max = _env_float("CSGOBOT_LOOK_YAW_MAX")
    sweep_min = _env_float("CSGOBOT_LOOK_SWEEP_MIN")
    sweep_max = _env_float("CSGOBOT_LOOK_SWEEP_MAX")
    idle_min = _env_float("CSGOBOT_LOOK_IDLE_MIN")
    idle_max = _env_float("CSGOBOT_LOOK_IDLE_MAX")
    return LookConfig(
        enabled=resolve_look_enabled(default.enabled),
        yaw_deg_min=yaw_min if yaw_min is not None else default.yaw_deg_min,
        yaw_deg_max=yaw_max if yaw_max is not None else default.yaw_deg_max,
        sweep_sec_min=sweep_min if sweep_min is not None else default.sweep_sec_min,
        sweep_sec_max=sweep_max if sweep_max is not None else default.sweep_sec_max,
        idle_sec_min=idle_min if idle_min is not None else default.idle_sec_min,
        idle_sec_max=idle_max if idle_max is not None else default.idle_sec_max,
    )
