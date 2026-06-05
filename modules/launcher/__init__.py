"""Launcher: Steam + CS2 (Windows), proxy check, cleanup, steam auto-login."""

from __future__ import annotations

from typing import Any, Protocol

from config.loader import load_config
from config.schema import AppConfig
from core.events import EventType
from modules.launcher import cleanup, cs2, proxy_check, steam, steam_auth, steam_gui_login, steam_promo_dismiss
from modules.launcher.errors import LauncherError
from modules.launcher.steam_auth import SteamAuthResult
from modules.launcher.steam_gui_login import SteamGuiLoginResult

__all__ = [
    "run",
    "run_cleanup",
    "LauncherError",
    "steam_auth",
    "steam_gui_login",
    "steam_promo_dismiss",
]


class _Emit(Protocol):
    def __call__(
        self,
        event: EventType,
        detail: str = "",
        *,
        drop_log: bool = False,
    ) -> None: ...


def run(ctx: dict[str, Any] | None = None) -> bool:
    """
    Запуск Steam (+ auto-login из vault) и опционально CS2.
    ctx: login, emit(event, detail), stop_after_steam (optional).
    """
    if ctx is None:
        ctx = {}
    emit: _Emit | None = ctx.get("emit")
    login = str(ctx.get("login", "")).strip()
    config: AppConfig = ctx.get("config") or load_config()

    def _emit(event: EventType, detail: str) -> None:
        if emit:
            emit(event, detail)

    try:
        ok, msg = proxy_check.check_proxy(config.proxy_expected_ip)
        if not ok:
            raise LauncherError(msg)
        _emit(EventType.IP_OK, msg)

        if config.steam_kill_before_login:
            cleanup.kill_all()

        steam.launch_steam(config)

        if config.steam_auto_login and login:
            _emit(EventType.STEAM_LOGIN_START, f"steam login [{login}]")
            auth = _login_steam(login, config)
            if not auth.ok:
                raise LauncherError(auth.detail)
            detail = auth.detail
            if getattr(auth, "already_logged_in", False):
                detail = f"{detail} (already logged in)"
            _emit(EventType.STEAM_LOGIN_OK, detail)
        elif config.steam_auto_login and not login:
            raise LauncherError("steam login: login required in session context")

        steam_detail = f"steam ready ({login or 'no login'})"
        if login and config.steam_dismiss_promo:
            promo = steam_promo_dismiss.dismiss_steam_promo(login, config)
            if promo.dismissed:
                steam_detail = f"{steam_detail}; {promo.detail}"
            elif promo.found and promo.dismissed == 0 and not promo.skipped:
                steam_detail = f"{steam_detail}; promo dismiss failed ({promo.detail})"

        _emit(EventType.STEAM_OK, steam_detail)

        if config.only_launch_steam:
            ctx["stop_after_steam"] = True
            cleanup.kill_cs2()
            return True

        cs2.launch_cs2(config)
        _emit(EventType.CS2_OK, "cs2 started with resources/cs2 configs")
        return True
    except LauncherError as exc:
        steam_auth.stop_steam_auth()
        if emit:
            emit(EventType.STEAM_LOGIN_FAILED, str(exc))
            emit(EventType.SESSION_FAILED, str(exc))
        return False


def _login_steam(login: str, config: AppConfig) -> SteamAuthResult | SteamGuiLoginResult:
    mode = config.steam_login_mode
    if mode == "api":
        return steam_auth.login_steam_account(login, config)
    if mode == "gui":
        return steam_gui_login.login_steam_gui(login, config)
    gui_result = steam_gui_login.login_steam_gui(login, config)
    if gui_result.ok:
        return gui_result
    api_result = steam_auth.login_steam_account(login, config)
    if api_result.ok:
        return SteamAuthResult(
            ok=True,
            login=api_result.login,
            detail=f"gui failed ({gui_result.detail}); api fallback ok",
            simulated=api_result.simulated,
        )
    return api_result


def run_cleanup(
    *,
    kill_steam: bool = True,
    kill_cs2: bool = True,
    stop_auth: bool = True,
) -> dict[str, list[str]]:
    if stop_auth:
        steam_auth.stop_steam_auth()
    return cleanup.cleanup_session(steam=kill_steam, cs2=kill_cs2)
