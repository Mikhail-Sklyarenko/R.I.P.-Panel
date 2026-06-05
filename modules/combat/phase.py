"""Combat + level_detector: stop on level_up → LEVEL_UP, timeout → CLEANUP."""

from __future__ import annotations

import threading
from typing import Any

from config.schema import AppConfig
from core.events import EventType
from modules.combat.factory import _run_bot_loop, stop_combat
from modules.level_detector import WatchResult, watch


def run_combat_phase(ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    if ctx is None:
        ctx = {}
    emit = ctx.get("emit")
    config: AppConfig | None = ctx.get("config")
    if config is None:
        from config.loader import load_config

        config = load_config()
        ctx = {**ctx, "config": config}

    if emit:
        emit(EventType.FARMING, "combat phase: start")

    ctx["stop_requested"] = False
    worker = threading.Thread(
        target=_run_bot_loop,
        args=(ctx,),
        name="combat-bot",
        daemon=True,
    )
    worker.start()

    outcome = watch(ctx)

    ctx["stop_requested"] = True
    stop_combat()
    worker.join(timeout=20.0)

    if emit:
        emit(EventType.COMBAT_STOPPED, f"combat phase: {outcome.value}")

    if outcome == WatchResult.LEVEL_UP and emit:
        emit(EventType.LEVEL_UP, "level_detector: UI level up")
        return {"ok": True, "outcome": outcome.value, "state": "level_up"}

    if outcome == WatchResult.COMBAT_TIMEOUT and emit:
        emit(
            EventType.COMBAT_TIMEOUT,
            f"max_dm_minutes={config.max_dm_minutes}",
        )
        return {"ok": True, "outcome": outcome.value, "state": "cleanup"}

    if outcome == WatchResult.STOPPED:
        return {"ok": False, "outcome": outcome.value}

    return {"ok": True, "outcome": outcome.value}
