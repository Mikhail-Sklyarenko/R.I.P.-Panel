"""DM rifle autobuy — one-time startup buy (weapons persist after death in DM)."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Callable

from config import AutoBuyConfig

logger = logging.getLogger("DetectionProcess")

# Death → spawn can take several seconds; buy only works alive + before WASD.
_DEFAULT_SPAWN_BUY_DELAYS_SEC = (
    0.3, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 11.0,
)
_DEFAULT_SPAWN_PATROL_FREEZE_SEC = 12.0
_DEFAULT_STARTUP_PATROL_FREEZE_SEC = 2.0
_FREEZE_BUY_INTERVAL_SEC = 0.35


def _env_bool(name: str) -> bool | None:
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


def resolve_buy_on_respawn(default: bool) -> bool:
    val = _env_bool("CSGOBOT_AUTOBUY_RESPAWN")
    return default if val is None else val


def resolve_periodic_buy(default: bool) -> bool:
    val = _env_bool("CSGOBOT_AUTOBUY_PERIODIC")
    return default if val is None else val


def resolve_autobuy_enabled(default: bool) -> bool:
    val = _env_bool("CSGOBOT_AUTO_BUY")
    return default if val is None else val


def resolve_autobuy_interval(default: float) -> float:
    raw = os.environ.get("CSGOBOT_AUTO_BUY_INTERVAL", "").strip()
    if raw:
        return max(0.5, float(raw))
    return default


def resolve_respawn_burst_delays(
    default: tuple[float, ...] = _DEFAULT_SPAWN_BUY_DELAYS_SEC,
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


def resolve_respawn_patrol_freeze(
    default: float = _DEFAULT_SPAWN_PATROL_FREEZE_SEC,
) -> float:
    raw = os.environ.get("CSGOBOT_AUTOBUY_PATROL_FREEZE_MS", "").strip()
    if raw:
        return max(0.0, float(raw) / 1000.0)
    return default


def resolve_startup_patrol_freeze(
    default: float = _DEFAULT_STARTUP_PATROL_FREEZE_SEC,
) -> float:
    raw = os.environ.get("CSGOBOT_AUTOBUY_STARTUP_FREEZE_MS", "").strip()
    if raw:
        return max(0.0, float(raw) / 1000.0)
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
    patrol_freeze_until: float = 0.0
    spawn_freeze_active: bool = False


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


def _schedule_presses(
    state: AutoBuyState,
    *,
    key: str,
    now: float,
    delays_sec: tuple[float, ...],
) -> None:
    for delay in delays_sec:
        if delay <= 0:
            continue
        state.scheduled_presses.append((now + delay, key))
    state.scheduled_presses.sort(key=lambda item: item[0])


def _arm_patrol_freeze_until(state: AutoBuyState, *, until: float) -> None:
    if until > state.patrol_freeze_until:
        state.patrol_freeze_until = until


def _schedule_spawn_buy_window(
    state: AutoBuyState,
    *,
    config: AutoBuyConfig,
    key: str,
    now: float,
) -> None:
    """
    After death (combat→idle): schedule F5 across death-cam + spawn + invuln window.

    No immediate press while dead/spectating — movement stays frozen until window ends.
    """
    delays = tuple(delay for delay in config.respawn_burst_delays_sec if delay > 0)
    if delays:
        _schedule_presses(state, key=key, now=now, delays_sec=delays)
    freeze_until = now + config.respawn_patrol_freeze_sec
    _arm_patrol_freeze_until(state, until=freeze_until)
    state.spawn_freeze_active = True
    logger.info(
        "autobuy: spawn window key=%s freeze=%.1fs buys=%s",
        key,
        config.respawn_patrol_freeze_sec,
        ",".join(f"{delay:.1f}s" for delay in delays) or "none",
    )


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
    Startup burst buy; optional team-change / periodic / respawn buys.

    DM default: startup only — loadout persists after death, no freeze on respawn.
    """
    if not config.enabled or not activated:
        return state

    if state.patrol_freeze_until <= now:
        state.spawn_freeze_active = False

    key = buy_key_for_team(team, config)
    _flush_scheduled_presses(state, now, press)

    if not state.started:
        burst_press(press, key, config.burst_count, config.burst_gap_sec)
        retry_delays = tuple(
            delay for delay in config.startup_retry_delays_sec if delay > 0
        )
        if retry_delays:
            _schedule_presses(state, key=key, now=now, delays_sec=retry_delays)
        _arm_patrol_freeze_until(
            state,
            until=now + config.startup_patrol_freeze_sec,
        )
        logger.info(
            "autobuy: startup burst key=%s x%d retries=%s",
            key,
            config.burst_count,
            ",".join(f"{delay:.1f}s" for delay in retry_delays) or "none",
        )
        state.started = True
        state.last_team = team
        state.last_pulse = now
        state.was_in_combat = in_combat
        return state

    if team != state.last_team:
        burst_press(press, key, config.burst_count, config.burst_gap_sec)
        _arm_patrol_freeze_until(
            state,
            until=now + config.startup_patrol_freeze_sec,
        )
        logger.info("autobuy: team_change burst team=%s key=%s", team, key)
        state.last_team = team
        state.last_pulse = now
        state.was_in_combat = in_combat
        return state

    if (
        config.buy_on_respawn
        and state.was_in_combat
        and not in_combat
    ):
        if now - state.last_respawn_burst >= config.respawn_burst_cooldown_sec:
            _schedule_spawn_buy_window(
                state,
                config=config,
                key=key,
                now=now,
            )
            state.last_respawn_burst = now
            state.last_pulse = now

    state.was_in_combat = in_combat

    if not config.periodic_buy:
        return state

    buy_interval = config.interval_sec
    if state.spawn_freeze_active and state.patrol_freeze_until > now:
        buy_interval = min(buy_interval, _FREEZE_BUY_INTERVAL_SEC)

    if now - state.last_pulse >= buy_interval:
        burst_press(press, key, config.burst_count, config.burst_gap_sec)
        state.last_pulse = now

    return state
