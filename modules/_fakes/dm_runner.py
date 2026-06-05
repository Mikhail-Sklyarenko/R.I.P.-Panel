"""Fake DM runner: menu → search → in_dm → exit."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.events import EventType
from modules._fakes.timing import sleep_step

if TYPE_CHECKING:
    from core.session_fsm import SessionContext


def run_to_dm(ctx: SessionContext) -> None:
    sleep_step()
    ctx.emit(EventType.IN_MENU, "dm_runner: in_menu")
    sleep_step()
    ctx.emit(EventType.SEARCHING_DM, "dm_runner: searching_dm")
    sleep_step()
    ctx.emit(EventType.IN_DM, "dm_runner: in_dm")


def run_exit(ctx: SessionContext) -> None:
    sleep_step()
    ctx.emit(EventType.EXITED, "dm_runner: exited")
