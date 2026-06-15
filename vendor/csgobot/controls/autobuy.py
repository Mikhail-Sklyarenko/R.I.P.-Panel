"""DM rifle autobuy — burst buy on interval, team change, and respawn heuristic."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Callable

from config import AutoBuyConfig

logger = logging.getLogger("DetectionProcess")

_DEFAULT_RESPAWN_DELAYS_SEC = (0.4, 0.9, 1.4)


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


def resolve_respawn_burst_delays(
    default: tuple[float, ...] = _DEFAULT_RESPAWN_DELAYS_SEC,
) -> tuple[float, ...]:
    raw = os.environ.get("CSGOBOT_AUTOBUY_RESPAWN_DELAYS_MS", "").strip()
    if not raw:
        return default
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not parts:
        return default
    return tuple(max(0.0, float(part) / 1000.0) for part in parts)


def resolve_respawn_burst_cooldown(default: float) -> float:
    raw = os.environ.get("CSGOBOT_AUTOBUY_RESPAWN_COOLDOWN_MS", "").strip()
    if raw:
        return max(0.1, float(raw) / 1000.0)
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
    scheduled_presses: list[tuple[float, str]] = field(default_factory=list)


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


def _flush_scheduled_presses(
    state: AutoBuyState,
    now: float,
    press: Callable[[str], None],
) -> int:
    if not state.scheduled_presses:
        return 0

    due: list[tuple[float, str]] = []
    pending: list[tuple[float, str]] = []
    for at, key in state.scheduled_presses:
        if at <= now:
            due.append((at, key))
        else:
            pending.append((at, key))

    state.scheduled_presses = pending
    for _, key in due:
        press(key)
    return len(due)


def _schedule_respawn_presses(
    state: AutoBuyState,
    *,
    key: str,
    now: float,
    delays_sec: tuple[float, ...],
) -> None:
    for delay in delays_sec:
        state.scheduled_presses.append((now + delay, key))
    state.scheduled_presses.sort(key=lambda item: item[0])


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
    Periodic burst buy + staggered respawn buys after combat→idle heuristic.

    Respawn buys are scheduled (not immediate) to hit DM buy window after spawn.
    """
    if not config.enabled or not activated:
        return state

    key = buy_key_for_team(team, config)
    _flush_scheduled_presses(state, now, press)

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
            delays = config.respawn_burst_delays_sec
            if delays:
                _schedule_respawn_presses(
                    state,
                    key=key,
                    now=now,
                    delays_sec=delays,
                )
                logger.info(
                    "autobuy: respawn stagger key=%s delays=%s",
                    key,
                    ",".join(f"{delay:.1f}s" for delay in delays),
                )
            state.last_respawn_burst = now
            state.last_pulse = now

    state.was_in_combat = in_combat

    if now - state.last_pulse >= config.interval_sec:
        burst_press(press, key, config.burst_count, config.burst_gap_sec)
        state.last_pulse = now

    return state
