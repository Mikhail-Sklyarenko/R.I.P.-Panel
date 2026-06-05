"""Поиск окон Steam client (Windows)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum

from modules.ui_nav.errors import UiNavError, UiNavPlatformError


class SteamWindowKind(str, Enum):
    LOGIN = "login"
    MAIN = "main"
    UPDATE = "update"
    OTHER = "other"


_LOGIN_TITLE_MARKERS = (
    "sign in to steam",
    "войти в steam",
    "steam - sign in",
    "steam sign in",
)
_UPDATE_TITLE_MARKERS = (
    "updating steam",
    "steam update",
    "обновление steam",
)
_MAIN_EXACT = ("steam",)
_PROMO_TITLE_MARKERS = (
    "sale",
    "promo",
    "discount",
    "% off",
    "special",
    "studio sale",
    "rgg",
    "steam sale",
    "распродаж",
    "скидк",
    "акци",
    "распродажа",
    "специальн",
)


def _require_windows() -> None:
    if sys.platform != "win32":
        raise UiNavPlatformError("Steam window API is Windows-only")


def classify_steam_title(title: str) -> SteamWindowKind:
    low = (title or "").strip().lower()
    if any(m in low for m in _LOGIN_TITLE_MARKERS):
        return SteamWindowKind.LOGIN
    if any(m in low for m in _UPDATE_TITLE_MARKERS):
        return SteamWindowKind.UPDATE
    if low in _MAIN_EXACT or low.startswith("steam -"):
        return SteamWindowKind.MAIN
    if low == "steam":
        return SteamWindowKind.MAIN
    if "steam" in low:
        return SteamWindowKind.OTHER
    return SteamWindowKind.OTHER


@dataclass(frozen=True)
class SteamWindowMatch:
    hwnd: int
    title: str
    kind: SteamWindowKind


def _enum_steam_windows() -> list[SteamWindowMatch]:
    _require_windows()
    import win32gui

    matches: list[SteamWindowMatch] = []

    def _enum(hwnd: int, _ctx) -> None:
        if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd) or ""
        low = title.lower()
        if "steam" not in low:
            return
        kind = classify_steam_title(title)
        matches.append(SteamWindowMatch(hwnd=hwnd, title=title, kind=kind))

    win32gui.EnumWindows(_enum, None)
    return matches


def find_steam_hwnd(*, prefer: SteamWindowKind | None = None) -> SteamWindowMatch | None:
    """Первое подходящее окно Steam; None если не найдено."""
    windows = _enum_steam_windows()
    if not windows:
        return None
    if prefer is not None:
        for w in windows:
            if w.kind == prefer:
                return w
    priority = (
        SteamWindowKind.LOGIN,
        SteamWindowKind.MAIN,
        SteamWindowKind.UPDATE,
        SteamWindowKind.OTHER,
    )
    for kind in priority:
        for w in windows:
            if w.kind == kind:
                return w
    return windows[0]


def wait_for_steam_window(
    *,
    timeout_sec: float,
    prefer: SteamWindowKind | None = None,
    poll_sec: float = 0.4,
) -> SteamWindowMatch:
    import time

    deadline = time.monotonic() + timeout_sec
    last: SteamWindowMatch | None = None
    while time.monotonic() < deadline:
        last = find_steam_hwnd(prefer=prefer)
        if last is not None:
            if prefer is None or last.kind == prefer:
                return last
        time.sleep(poll_sec)
    raise UiNavError(
        f"Steam window not found within {timeout_sec:.0f}s"
        + (f" (want {prefer.value})" if prefer else "")
    )


def wait_for_login_or_main(
    *,
    timeout_sec: float,
    login: str = "",
    poll_sec: float = 0.4,
) -> tuple[SteamWindowMatch | None, bool]:
    """
    Wait for Steam LOGIN window or logged-in MAIN.
    Returns (login_window, already_logged_in).
    """
    import time

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        done = logged_in_main_visible(login) if login else None
        if done is not None:
            return None, True
        login_win = find_steam_hwnd(prefer=SteamWindowKind.LOGIN)
        if login_win is not None:
            from modules.ui_nav.window import is_valid_hwnd

            if is_valid_hwnd(login_win.hwnd):
                return login_win, False
        time.sleep(poll_sec)
    raise UiNavError(
        f"Steam login or main window not found within {timeout_sec:.0f}s"
    )


def title_indicates_logged_in_as(title: str, login: str) -> bool:
    """Эвристика: имя аккаунта в заголовке главного окна."""
    low = (title or "").lower()
    user = login.strip().lower()
    if not user:
        return False
    return user in low


def find_main_steam_for_login(login: str) -> SteamWindowMatch | None:
    for w in _enum_steam_windows():
        if w.kind == SteamWindowKind.MAIN and title_indicates_logged_in_as(
            w.title, login
        ):
            return w
    for w in _enum_steam_windows():
        if w.kind == SteamWindowKind.MAIN:
            return w
    return None


def login_window_open() -> bool:
    """True if a live Steam LOGIN window exists."""
    login = find_steam_hwnd(prefer=SteamWindowKind.LOGIN)
    if login is None:
        return False
    from modules.ui_nav.window import is_valid_hwnd

    return is_valid_hwnd(login.hwnd)


def logged_in_main_visible(login: str) -> SteamWindowMatch | None:
    """
    MAIN Steam client without an open LOGIN window — post-login state.
    """
    from modules.ui_nav.window import is_valid_hwnd

    main = find_main_steam_for_login(login)
    if main is None or not is_valid_hwnd(main.hwnd):
        return None
    if login_window_open():
        return None
    return main


def is_main_steam_window(match: SteamWindowMatch) -> bool:
    return match.kind == SteamWindowKind.MAIN


def title_indicates_promo(title: str) -> bool:
    """Heuristic: separate promo/sale modal (not LOGIN/MAIN/UPDATE)."""
    low = (title or "").strip().lower()
    if not low:
        return False
    kind = classify_steam_title(title)
    if kind in (SteamWindowKind.LOGIN, SteamWindowKind.MAIN, SteamWindowKind.UPDATE):
        return False
    return any(m in low for m in _PROMO_TITLE_MARKERS)


def find_steam_promo_windows() -> list[SteamWindowMatch]:
    """Top-level visible windows matching promo title heuristics."""
    _require_windows()
    import win32gui

    from modules.ui_nav.window import is_valid_hwnd

    promos: list[SteamWindowMatch] = []

    def _enum(hwnd: int, _ctx) -> None:
        if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
            return
        if not is_valid_hwnd(hwnd):
            return
        title = win32gui.GetWindowText(hwnd) or ""
        if not title_indicates_promo(title):
            return
        promos.append(
            SteamWindowMatch(
                hwnd=hwnd,
                title=title,
                kind=SteamWindowKind.OTHER,
            )
        )

    win32gui.EnumWindows(_enum, None)
    return promos
