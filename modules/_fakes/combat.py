"""Fake combat: csgobot start, farming tick, stop."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.events import EventType
from modules._fakes.timing import sleep_step

if TYPE_CHECKING:
    from core.session_fsm import SessionContext


def run(ctx: SessionContext) -> None:
    sleep_step()
    ctx.emit(EventType.COMBAT_AI_STARTED, "combat: ai started (fake)")
    sleep_step()
    ctx.emit(EventType.FARMING, "combat: farming")
    sleep_step()
    ctx.emit(EventType.FARMING, "combat: farming (tick)")
    sleep_step()
    ctx.emit(EventType.COMBAT_STOPPED, "combat: stopped")
