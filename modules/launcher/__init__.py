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
from modules.ui_nav.artifacts import ArtifactStore
from modules.ui_nav.errors import UiNavError

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
            auth = _login_steam(
                login,
                config,
                on_progress=ctx.get("on_login_progress"),
            )
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
        on_cs2_progress = ctx.get("on_cs2_progress")

        from modules.ui_nav.window import wait_for_cs2_hwnd

        timeout = max(15, int(config.cs2_window_wait_timeout_sec))
        try:
            cs2_hwnd = wait_for_cs2_hwnd(
                timeout_sec=float(timeout),
                on_progress=on_cs2_progress,
            )
        except UiNavError as exc:
            raise LauncherError(f"CS2 window wait: {exc}") from exc

        ctx["cs2_hwnd"] = cs2_hwnd

        from modules.ui_nav.coords import load_nav_coords_for_hwnd
        from modules.ui_nav.window import wait_for_cs2_main_menu

        session_id = str(ctx.get("session_id") or login or "launch")
        artifacts = ArtifactStore(session_id)
        coords = load_nav_coords_for_hwnd(
            cs2_hwnd,
            config.cs_resolution,
            on_warn=on_cs2_progress,
        )
        menu_timeout = max(15, int(config.cs2_main_menu_wait_timeout_sec))
        menu_result = wait_for_cs2_main_menu(
            cs2_hwnd,
            coords,
            timeout_sec=float(menu_timeout),
            on_progress=on_cs2_progress,
            artifacts=artifacts,
            min_match=1,
        )
        if menu_result.ok:
            _emit(
                EventType.CS2_OK,
                f"cs2 menu ready (hwnd={cs2_hwnd})",
            )
        else:
            ctx["cs2_menu_probe_warn"] = True
            _emit(
                EventType.CS2_OK,
                f"cs2 menu unconfirmed after {menu_timeout}s (hwnd={cs2_hwnd}); trying dm nav",
            )
        return True
    except LauncherError as exc:
        steam_auth.stop_steam_auth()
        if emit:
            msg = str(exc)
            if msg.startswith("CS2 window wait:"):
                emit(EventType.SESSION_FAILED, msg)
            else:
                emit(EventType.STEAM_LOGIN_FAILED, msg)
                emit(EventType.SESSION_FAILED, msg)
        return False


def _login_steam(
    login: str,
    config: AppConfig,
    *,
    on_progress=None,
) -> SteamAuthResult | SteamGuiLoginResult:
    mode = config.steam_login_mode
    if mode == "api":
        return steam_auth.login_steam_account(login, config)
    if mode == "gui":
        return steam_gui_login.login_steam_gui(
            login, config, on_progress=on_progress
        )
    gui_result = steam_gui_login.login_steam_gui(
        login, config, on_progress=on_progress
    )
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
