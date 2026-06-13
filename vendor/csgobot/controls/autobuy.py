"""DM rifle autobuy — burst buy on interval, team change, and respawn heuristic."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
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
        return max(0.5, float(raw))
    return default


def buy_key_for_team(team: str, config: AutoBuyConfig) -> str:
    """Legacy team keys; prefer config.buy_key (team-agnostic alias in fsm.cfg)."""
    if config.buy_key:
        return config.buy_key
    return config.ct_key if team.lower() == "ct" else config.t_key


@dataclass
class AutoBuyState:
    last_team: str = ""
    last_pulse: float = 0.0
    was_in_combat: bool = False
    last_respawn_burst: float = 0.0
    started: bool = False


def burst_press(
    press: Callable[[str], None],
    key: str,
    count: int,
    gap_sec: float,
) -> None:
    for i in range(max(1, count)):
        press(key)
        if i + 1 < count and gap_sec > 0:
            time.sleep(gap_sec)


def update_autobuy(
    state: AutoBuyState,
    *,
    config: AutoBuyConfig,
    team: str,
    in_combat: bool,
    activated: bool,
    now: float,
    press: Callable[[str], None],
) -> AutoBuyState:
    """
    Periodic burst buy + extra bursts on team change and likely respawn.

    DM buy window after spawn is short; 3 s interval misses most respawns.
    """
    if not config.enabled or not activated:
        return state

    key = buy_key_for_team(team, config)

    if not state.started:
        burst_press(press, key, config.burst_count, config.burst_gap_sec)
        logger.info("autobuy: startup burst key=%s x%d", key, config.burst_count)
        state.started = True
        state.last_team = team
        state.last_pulse = now
        state.was_in_combat = in_combat
        return state

    if team != state.last_team:
        burst_press(press, key, config.burst_count, config.burst_gap_sec)
        logger.info("autobuy: team_change burst team=%s key=%s", team, key)
        state.last_team = team
        state.last_pulse = now
        state.was_in_combat = in_combat
        return state

    if state.was_in_combat and not in_combat:
        if now - state.last_respawn_burst >= config.respawn_burst_cooldown_sec:
            burst_press(
                press,
                key,
                config.respawn_burst_count,
                config.burst_gap_sec,
            )
            logger.info(
                "autobuy: respawn burst key=%s x%d",
                key,
                config.respawn_burst_count,
            )
            state.last_respawn_burst = now
            state.last_pulse = now

    state.was_in_combat = in_combat

    if now - state.last_pulse >= config.interval_sec:
        burst_press(press, key, config.burst_count, config.burst_gap_sec)
        state.last_pulse = now

    return state
