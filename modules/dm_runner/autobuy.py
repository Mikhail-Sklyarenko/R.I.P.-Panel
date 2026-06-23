"""DM startup rifle buy — single CS2 console buy after team random."""

from __future__ import annotations

import sys
from typing import Callable

from modules.ui_nav.errors import UiNavError


def run_console_autobuy(
    hwnd: int | None,
    *,
    attempt: int = 1,
    total: int = 1,
    on_progress: Callable[[str], None] | None = None,
    log_step: Callable[..., None] | None = None,
) -> bool:
    """Open CS2 console and run buy ak47; buy m4a1_silencer; …"""
    if hwnd is None or sys.platform != "win32":
        return False

    from modules.ui_nav.cs2_console import run_console_dm_rifle_buy

    if on_progress:
        on_progress(f"dm nav: autobuy console ({attempt}/{total})")
    try:
        run_console_dm_rifle_buy(hwnd)
        if log_step:
            log_step("dm_autobuy_console", attempt=attempt, total=total, cmd="buy_rifle_dm")
        return True
    except UiNavError as exc:
        if on_progress:
            on_progress(f"dm nav: autobuy console failed ({exc})")
        return False
