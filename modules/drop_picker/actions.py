"""Клики по слотам и Confirm (Windows / sim log)."""

from __future__ import annotations

import os
import sys
import time

from modules.drop_picker.pricing import PricedItem
from modules.drop_picker.slots import DropLayout
from modules.ui_nav.artifacts import ArtifactStore
from modules.ui_nav.coords import Point


def click_slots(
    ctx: dict,
    layout: DropLayout,
    picks: list[PricedItem],
    artifacts: ArtifactStore,
) -> None:
    click_map = {s.slot_id: Point(s.click_x, s.click_y) for s in layout.slots}
    for item in picks:
        pt = click_map[item.slot_id]
        _click(ctx, pt)
        artifacts.log_step(
            "drop_slot_click",
            slot_id=item.slot_id,
            name=item.market_hash_name,
            price=item.price_usd,
        )
        time.sleep(0.35)

    cx, cy = layout.confirm_click
    _click(ctx, Point(cx, cy))
    artifacts.log_step("drop_confirm_click")


def _click(ctx: dict, point: Point) -> None:
    if os.environ.get("DROP_PICKER_SIM", "").lower() in ("1", "true", "yes"):
        return
    if sys.platform != "win32":
        return
    from modules.ui_nav.actions import click_client
    from modules.ui_nav.window import find_cs2_hwnd

    hwnd = ctx.get("hwnd")
    if hwnd is None:
        hwnd = find_cs2_hwnd()
        ctx["hwnd"] = hwnd
    click_client(hwnd, point)
