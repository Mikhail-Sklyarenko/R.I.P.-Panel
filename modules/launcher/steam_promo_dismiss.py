"""Detect and dismiss Steam promo/sale banners after login (post-login, pre-cs2)."""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from config.paths import get_logs_dir
from config.schema import AppConfig
from modules.launcher.errors import LauncherPlatformError
from modules.launcher.steam_main_coords import SteamMainCoords, load_steam_main_coords
from modules.ui_nav import actions
from modules.ui_nav.errors import UiNavError
from modules.ui_nav.steam_window import (
    SteamWindowMatch,
    find_steam_promo_windows,
    logged_in_main_visible,
    login_window_open,
)
from modules.ui_nav.window import client_size, is_valid_hwnd

_log = logging.getLogger(__name__)

_MAX_PROMO_WINDOWS = 3
_DISMISS_RETRY_DELAY_SEC = 0.35


@dataclass(frozen=True)
class SteamPromoDismissResult:
    dismissed: int
    found: int
    detail: str
    skipped: bool = False


def _require_windows() -> None:
    if sys.platform != "win32":
        raise LauncherPlatformError("steam promo dismiss is Windows-only")


def _sim_result() -> SteamPromoDismissResult:
    return SteamPromoDismissResult(
        dismissed=0,
        found=0,
        detail="sim",
        skipped=True,
    )


def _save_fail_screenshot(login: str, hwnd: int, step: str) -> str:
    try:
        if not is_valid_hwnd(hwnd):
            return ""
    except Exception:
        return ""
    try:
        from modules.ui_nav.capture import capture_client

        img = capture_client(hwnd)
        log_dir = get_logs_dir() / "steam_login"
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_login = "".join(c if c.isalnum() or c in "-_" else "_" for c in login)
        path = log_dir / f"{safe_login}_{ts}_{step}.png"
        img.save(path)
        return str(path)
    except Exception:
        return ""


def _promo_still_open(hwnd: int) -> bool:
    return is_valid_hwnd(hwnd)


def _try_esc(promo_hwnd: int) -> bool:
    try:
        actions.press_escape(promo_hwnd)
    except UiNavError:
        return False
    time.sleep(_DISMISS_RETRY_DELAY_SEC)
    return not _promo_still_open(promo_hwnd)


def _try_wm_close(promo_hwnd: int) -> bool:
    try:
        actions.close_window(promo_hwnd)
    except UiNavError:
        return False
    time.sleep(_DISMISS_RETRY_DELAY_SEC)
    return not _promo_still_open(promo_hwnd)


def _try_click_close(
    promo_hwnd: int,
    coords: SteamMainCoords | None,
) -> bool:
    if coords is None:
        return False
    point = coords.click("promo_close")
    if point is None:
        return False
    try:
        actions.click_client(promo_hwnd, point)
    except UiNavError:
        return False
    time.sleep(_DISMISS_RETRY_DELAY_SEC)
    return not _promo_still_open(promo_hwnd)


def _load_main_coords(main: SteamWindowMatch) -> SteamMainCoords | None:
    try:
        w, h = client_size(main.hwnd)
        return load_steam_main_coords(w, h)
    except UiNavError:
        return None


def _close_promo_window(
    promo: SteamWindowMatch,
    *,
    main: SteamWindowMatch,
    coords: SteamMainCoords | None,
) -> bool:
    promo_hwnd = promo.hwnd
    for attempt_fn in (
        lambda: _try_esc(promo_hwnd),
        lambda: _try_wm_close(promo_hwnd),
        lambda: _try_click_close(promo_hwnd, coords),
    ):
        if attempt_fn():
            _log.info("steam promo dismissed: %r", promo.title)
            return True
    return False


def dismiss_steam_promo(login: str, config: AppConfig) -> SteamPromoDismissResult:
    """
    Best-effort promo dismiss after login OK.
    Soft-fail: never raises; pipeline continues to steam_ok / cs2.
    """
    login = login.strip()
    if os.environ.get("STEAM_GUI_LOGIN_SIM") == "1":
        return _sim_result()

    if not config.steam_dismiss_promo:
        return SteamPromoDismissResult(
            dismissed=0,
            found=0,
            detail="disabled",
            skipped=True,
        )

    if not login:
        return SteamPromoDismissResult(
            dismissed=0,
            found=0,
            detail="no login in context",
            skipped=True,
        )

    if sys.platform != "win32":
        return SteamPromoDismissResult(
            dismissed=0,
            found=0,
            detail="non-Windows skip",
            skipped=True,
        )

    _require_windows()

    if login_window_open():
        _log.warning("steam promo dismiss skipped: LOGIN window still open")
        return SteamPromoDismissResult(
            dismissed=0,
            found=0,
            detail="login window open — skip promo dismiss",
            skipped=True,
        )

    main = logged_in_main_visible(login)
    if main is None:
        return SteamPromoDismissResult(
            dismissed=0,
            found=0,
            detail="main not visible — skip promo dismiss",
            skipped=True,
        )

    deadline = time.monotonic() + max(3, int(config.steam_promo_dismiss_timeout_sec))
    dismissed = 0
    found = 0
    coords: SteamMainCoords | None = None

    while time.monotonic() < deadline:
        promos = find_steam_promo_windows()
        if not promos:
            if found == 0:
                return SteamPromoDismissResult(
                    dismissed=0,
                    found=0,
                    detail="main only — no promo",
                )
            break

        if coords is None:
            coords = _load_main_coords(main)

        promos = promos[:_MAX_PROMO_WINDOWS]
        found += len(promos)
        for promo in promos:
            if _close_promo_window(promo, main=main, coords=coords):
                dismissed += 1
            else:
                _log.warning(
                    "steam promo dismiss failed for %r (hwnd=%s)",
                    promo.title,
                    promo.hwnd,
                )
                if login:
                    shot = _save_fail_screenshot(login, promo.hwnd, "promo_fail")
                    if shot:
                        _log.warning("steam promo screenshot: %s", shot)
        time.sleep(0.3)

    if logged_in_main_visible(login) is None:
        return SteamPromoDismissResult(
            dismissed=dismissed,
            found=found,
            detail="main lost after promo dismiss",
        )

    remaining = find_steam_promo_windows()
    if remaining and dismissed == 0:
        return SteamPromoDismissResult(
            dismissed=0,
            found=found,
            detail=f"promo still visible ({len(remaining)} window(s))",
        )

    if dismissed:
        return SteamPromoDismissResult(
            dismissed=dismissed,
            found=found,
            detail=f"dismissed {dismissed} promo window(s)",
        )

    return SteamPromoDismissResult(
        dismissed=0,
        found=found,
        detail="main only — no promo",
    )
