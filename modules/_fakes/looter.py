"""Fake looter: log vendor path, loot_ok."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.events import EventType
from modules._fakes.timing import sleep_step

if TYPE_CHECKING:
    from core.session_fsm import SessionContext

LOOTER_SCRIPT = "vendor/looter/looter_core.js"


def run(ctx: SessionContext) -> None:
    from config.loader import load_config

    if not load_config().auto_collect_drop:
        ctx.emit(
            EventType.LOOT_OK,
            "looter skipped: auto_collect_drop=false",
            drop_log=True,
        )
        return
    sleep_step()
    msg = f"would call {LOOTER_SCRIPT}"
    ctx.emit(EventType.LOOT_OK, msg, drop_log=True)
    sleep_step()
