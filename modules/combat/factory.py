"""Выбор бота: auto | ai | simple; цикл до stop_requested."""

from __future__ import annotations

import os
from typing import Any

from config.schema import AppConfig, BotMode
from core.events import EventType
from modules.combat import csgobot_ai, simple
from modules.combat.errors import CombatError


def resolve_mode(config: AppConfig) -> BotMode:
    if os.environ.get("CSGOBOT_NAV_MODE", "").strip().lower() == "expanded_roam":
        return BotMode.AI
    if config.bot_mode != BotMode.AUTO:
        return config.bot_mode
    if csgobot_ai.is_installed() and csgobot_ai.python_executable() is not None:
        return BotMode.AI
    return BotMode.SIMPLE


def _run_bot_loop(ctx: dict[str, Any]) -> None:
    """Фоновый бой до stop_requested (управляет level_detector)."""
    config: AppConfig = ctx.get("config")
    if config is None:
        from config.loader import load_config

        config = load_config()
        ctx["config"] = config

    emit = ctx.get("emit")
    mode = resolve_mode(config)
    cap_minutes = max(config.combat_simple_minutes, config.max_dm_minutes)

    try:
        if mode == BotMode.SIMPLE:
            if emit:
                emit(EventType.FARMING, "factory: mode=simple")
            simple.run_simple(ctx, minutes=cap_minutes)
            return

        if mode == BotMode.AI:
            ok = csgobot_ai.start_ai(ctx)
            if ok:
                return
            if os.environ.get("CSGOBOT_NAV_MODE", "").strip().lower() == "expanded_roam":
                if emit:
                    emit(EventType.SESSION_FAILED,"Навигация и автострельба: боевой процесс не запустился; проверьте журнал csgobot")
                ctx["stop_requested"] = True
                return
            if emit:
                emit(EventType.COMBAT_FALLBACK, "factory: ai failed → simple")
            simple.run_simple(ctx, minutes=cap_minutes)
            return

        raise CombatError(f"unknown bot_mode: {mode}")
    except Exception as exc:
        csgobot_ai.stop_ai()
        if emit:
            emit(EventType.SESSION_FAILED, f"combat: worker failed: {exc}")
        ctx["stop_requested"] = True


def run_combat(ctx: dict[str, Any] | None = None) -> bool:
    """Legacy: полный цикл без detector (используйте combat.phase)."""
    if ctx is None:
        ctx = {}
    ctx["stop_requested"] = False
    _run_bot_loop(ctx)
    stop_combat()
    return not ctx.get("stop_requested")


def stop_combat() -> None:
    csgobot_ai.stop_ai()
