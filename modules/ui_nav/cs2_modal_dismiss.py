"""Dismiss CS2 Panorama overlays (news, tournament promos) via Escape."""

from __future__ import annotations

import sys
import time
from typing import Callable

from modules.ui_nav.errors import UiNavError, UiNavPlatformError
from modules.ui_nav.window import is_valid_hwnd

_DEFAULT_BURSTS = 3
_DEFAULT_INTERVAL_SEC = 0.3


def dismiss_cs2_modals(
    hwnd: int,
    *,
    bursts: int = _DEFAULT_BURSTS,
    interval_sec: float = _DEFAULT_INTERVAL_SEC,
    on_progress: Callable[[str], None] | None = None,
) -> int:
    """
    Press Escape in CS2 to close blocking main-menu overlays.

    Returns number of Esc bursts sent (0 if hwnd invalid).
    """
    if sys.platform != "win32":
        raise UiNavPlatformError("dismiss_cs2_modals is Windows-only")
    if not is_valid_hwnd(hwnd):
        return 0

    from modules.ui_nav.actions import press_escape

    count = max(1, bursts)
    sent = 0
    for i in range(count):
        try:
            press_escape(hwnd)
            sent += 1
        except UiNavError as exc:
            if on_progress:
                on_progress(f"cs2 modal dismiss: esc failed ({exc})")
            break
        if i + 1 < count:
            time.sleep(max(0.1, interval_sec))
    if sent and on_progress:
        on_progress(f"cs2 modal dismiss: sent Esc x{sent}")
    return sent
