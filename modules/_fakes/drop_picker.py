"""Fake drop picker — delegates to pick_care_package sim."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.session_fsm import SessionContext


def run(ctx: SessionContext) -> None:
    os.environ.setdefault("DROP_PICKER_SIM", "1")
    os.environ.setdefault("DROP_PRICING_OFFLINE", "1")
    from modules.drop_picker import pick_care_package

    pick_care_package(
        {
            "login": ctx.login,
            "emit": ctx.emit,
            "session_id": ctx.session_id,
            "config": __import__("config.loader", fromlist=["load_config"]).load_config(),
        }
    )
