"""DM rifle autobuy pulse (F9 CT / F10 T binds in fsm.cfg)."""

from __future__ import annotations

import logging
import os
from typing import Callable

from config import AutoBuyConfig

logger = logging.getLogger("DetectionProcess")


def _env_bool(name: str) -> bool | None:
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


def resolve_autobuy_enabled(default: bool) -> bool:
    val = _env_bool("CSGOBOT_AUTO_BUY")
    return default if val is None else val


def resolve_autobuy_interval(default: float) -> float:
    raw = os.environ.get("CSGOBOT_AUTO_BUY_INTERVAL", "").strip()
    if raw:
        return max(1.0, float(raw))
    return default


def buy_key_for_team(team: str, config: AutoBuyConfig) -> str:
    return config.ct_key if team.lower() == "ct" else config.t_key


def maybe_autobuy_pulse(
    *,
    config: AutoBuyConfig,
    team: str,
    activated: bool,
    now: float,
    last_pulse: float,
    press: Callable[[str], None],
    unstuck_running: bool = False,
) -> float:
    """Press team buy key if interval elapsed; returns updated last_pulse."""
    if not config.enabled or not activated or unstuck_running:
        return last_pulse
    if now - last_pulse < config.interval_sec:
        return last_pulse

    key = buy_key_for_team(team, config)
    press(key)
    logger.info("autobuy: pulse team=%s key=%s", team, key)
    return now
