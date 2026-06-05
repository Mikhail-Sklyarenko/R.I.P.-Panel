"""Combat + level_detector phase (B7)."""

from __future__ import annotations

from typing import Any

from modules.combat.errors import CombatError
from modules.combat.factory import resolve_mode, stop_combat
from modules.combat.phase import run_combat_phase

__all__ = [
    "CombatError",
    "resolve_mode",
    "run_combat_phase",
    "start",
    "stop",
]


def start(ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    return run_combat_phase(ctx)


def stop(ctx: dict[str, Any] | None = None) -> None:
    if ctx is not None:
        ctx["stop_requested"] = True
    stop_combat()
