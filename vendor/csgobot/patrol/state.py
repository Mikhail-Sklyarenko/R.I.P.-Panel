"""Patrol vs combat mode transitions."""

from __future__ import annotations

from enum import Enum


class PatrolMode(Enum):
    PATROL = "patrol"
    COMBAT = "combat"


def should_patrol_tick(
    *,
    patrol_enabled: bool,
    activated: bool,
    mode: PatrolMode,
) -> bool:
    return patrol_enabled and activated and mode == PatrolMode.PATROL


def next_mode_after_combat_check(
    *,
    mode: PatrolMode,
    in_combat: bool,
    now: float,
    last_enemy_seen: float,
    combat_clear_sec: float,
) -> PatrolMode:
    if in_combat:
        return PatrolMode.COMBAT
    if mode == PatrolMode.COMBAT and (now - last_enemy_seen) >= combat_clear_sec:
        return PatrolMode.PATROL
    return mode
