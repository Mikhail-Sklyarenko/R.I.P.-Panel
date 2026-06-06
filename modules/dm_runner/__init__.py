"""DM runner: solo Deathmatch UI navigation via ui_nav."""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from config.loader import load_config
from config.schema import AppConfig
from core.events import EventType
from modules.dm_runner.navigate import DmNavigator
from modules.ui_nav.errors import UiNavError, UiNavTimeoutError

__all__ = ["run", "run_exit", "run_in_dm_cycles", "DmNavigator"]


class _Emit(Protocol):
    def __call__(
        self,
        event: EventType,
        detail: str = "",
        *,
        drop_log: bool = False,
    ) -> None: ...


def _session_id(ctx: dict[str, Any]) -> str:
    return str(ctx.get("session_id") or uuid.uuid4().hex[:12])


def run(ctx: dict[str, Any] | None = None) -> bool:
    """
    До in_dm. ctx: login, emit, session_id?, config?, hwnd?.
    """
    if ctx is None:
        ctx = {}
    emit: _Emit | None = ctx.get("emit")
    login = str(ctx.get("login", ""))
    config: AppConfig = ctx.get("config") or load_config()
    try:
        nav = DmNavigator(
            config=config,
            session_id=_session_id(ctx),
            login=login,
            emit=emit,
            hwnd=ctx.get("hwnd"),
            on_nav_progress=ctx.get("on_nav_progress"),
            menu_probe_warn=bool(ctx.get("cs2_menu_probe_warn")),
        )
    except UiNavError as exc:
        if emit:
            emit(EventType.SESSION_FAILED, f"dm_runner init: {exc}")
        return False
    try:
        nav.navigate_to_dm_with_retries()
        return True
    except (UiNavTimeoutError, UiNavError) as exc:
        if emit:
            emit(EventType.SESSION_FAILED, f"dm_runner: {exc}")
        return False


def run_exit(ctx: dict[str, Any] | None = None) -> bool:
    if ctx is None:
        ctx = {}
    emit: _Emit | None = ctx.get("emit")
    config: AppConfig = ctx.get("config") or load_config()
    nav = DmNavigator(
        config=config,
        session_id=_session_id(ctx),
        login=str(ctx.get("login", "")),
        emit=emit,
        hwnd=ctx.get("hwnd"),
    )
    try:
        nav.disconnect()
        return True
    except (UiNavTimeoutError, UiNavError) as exc:
        if emit:
            emit(EventType.SESSION_FAILED, f"dm_runner exit: {exc}")
        return False


def run_in_dm_cycles(
    cycles: int = 5,
    *,
    ctx: dict[str, Any] | None = None,
) -> int:
    """Smoke: 5× in_dm (Windows + CS2 или DM_NAV_SIM=1)."""
    if ctx is None:
        ctx = {}
    config: AppConfig = ctx.get("config") or load_config()
    nav = DmNavigator(
        config=config,
        session_id=_session_id(ctx),
        login=str(ctx.get("login", "smoke")),
        emit=ctx.get("emit"),
        hwnd=ctx.get("hwnd"),
    )
    return nav.run_in_dm_cycles(cycles=cycles)
