"""Simple combat: таймер фарма (10 min), лёгкий input (Windows), без GPL."""

from __future__ import annotations

import os
import random
import sys
import time
from typing import Any, Callable, Protocol

from core.events import EventType

_DEFAULT_MINUTES = 10
_FARMING_TICK_SEC = 60


class _Emit(Protocol):
    def __call__(
        self,
        event: EventType,
        detail: str = "",
        *,
        drop_log: bool = False,
    ) -> None: ...


def _duration_sec(minutes: int | None = None) -> int:
    override = os.environ.get("COMBAT_SIMPLE_SECONDS")
    if override:
        return max(1, int(float(override)))
    mins = minutes if minutes is not None else int(
        os.environ.get("COMBAT_SIMPLE_MINUTES", str(_DEFAULT_MINUTES))
    )
    return max(60, mins * 60)


def _micro_actions(hwnd: int | None) -> None:
    if sys.platform != "win32" or hwnd is None:
        return
    from modules.ui_nav.actions import focus_window, press_key

    try:
        focus_window(hwnd)
        key = random.choice(["w", "a", "s", "d"])
        press_key(hwnd, key)
    except Exception:
        pass


def run_simple(
    ctx: dict[str, Any],
    *,
    minutes: int | None = None,
) -> None:
    """
    Блокирующий цикл фарма ~10 минут.
    Эмитит farming каждые 60s, combat_stopped в конце.
    """
    emit: _Emit | None = ctx.get("emit")
    duration = _duration_sec(minutes)
    hwnd: int | None = ctx.get("hwnd")
    if hwnd is None and sys.platform == "win32" and not os.environ.get("COMBAT_SKIP_WIN32"):
        try:
            from modules.ui_nav.window import find_cs2_hwnd

            hwnd = find_cs2_hwnd()
        except Exception:
            hwnd = None

    if emit:
        emit(EventType.FARMING, f"simple: start ({duration}s)")

    deadline = time.monotonic() + duration
    next_tick = time.monotonic() + _FARMING_TICK_SEC
    next_action = time.monotonic() + 8.0

    while time.monotonic() < deadline:
        if ctx.get("stop_requested"):
            break
        now = time.monotonic()
        if now >= next_tick:
            if emit:
                emit(EventType.FARMING, "simple: farming tick")
            next_tick = now + _FARMING_TICK_SEC
        if now >= next_action:
            _micro_actions(hwnd)
            next_action = now + random.uniform(6.0, 14.0)
        time.sleep(0.25)

    if emit:
        emit(EventType.COMBAT_STOPPED, "simple: finished")
