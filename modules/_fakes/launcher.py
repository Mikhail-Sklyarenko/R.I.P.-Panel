"""Fake launcher: steam_ok, cs2_ok (или only_launch_steam)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from config.loader import load_config
from core.events import EventType
from core.session_state import SessionState, advance
from modules._fakes.timing import sleep_step

if TYPE_CHECKING:
    from core.session_fsm import SessionContext


def run(ctx: SessionContext) -> None:
    sleep_step()
    ctx.emit(EventType.STEAM_OK, "launcher: steam_ok (fake)")
    if load_config().only_launch_steam:
        ctx.state = advance(ctx.state, SessionState.CLEANUP)
        ctx.emit(EventType.EXITED, "only_launch_steam (fake)")
        return
    sleep_step()
    ctx.emit(EventType.CS2_OK, "launcher: cs2_ok (fake)")
