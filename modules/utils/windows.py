"""Перемещение всех окон CS2/CSGO (Windows)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from config.schema import AppConfig
from modules.utils.errors import UtilsError, UtilsPlatformError

_CS_TITLE_PARTS = ("counter-strike 2", "counter-strike", "cs2", "csgo")


@dataclass(frozen=True)
class CsWindow:
    hwnd: int
    title: str


@dataclass(frozen=True)
class MoveResult:
    moved: list[CsWindow]
    width: int
    height: int
    simulated: bool = False

    @property
    def count(self) -> int:
        return len(self.moved)


def _sim_enabled() -> bool:
    return os.environ.get("UTILS_SIM", "").lower() in ("1", "true", "yes")


def _require_windows() -> None:
    if sys.platform != "win32" and not _sim_enabled():
        raise UtilsPlatformError("move CS windows is Windows-only")


def parse_resolution(resolution: str) -> tuple[int, int]:
    parts = resolution.lower().split("x", 1)
    if len(parts) != 2:
        raise UtilsError(f"invalid cs_resolution: {resolution}")
    return int(parts[0]), int(parts[1])


def outer_size_for_client(hwnd: int, client_w: int, client_h: int) -> tuple[int, int]:
    """MoveWindow size so client rect matches client_w x client_h (not outer frame)."""
    _require_windows()
    import ctypes
    import win32con
    import win32gui
    from ctypes import wintypes

    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
    ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    rect = wintypes.RECT(0, 0, int(client_w), int(client_h))
    if not ctypes.windll.user32.AdjustWindowRectEx(
        ctypes.byref(rect), style, False, ex_style
    ):
        raise UtilsError("AdjustWindowRectEx failed")
    return rect.right - rect.left, rect.bottom - rect.top


def list_cs_windows() -> list[CsWindow]:
    """Все видимые окна CS2/CSGO (не только первое)."""
    if _sim_enabled():
        return [
            CsWindow(hwnd=101, title="Counter-Strike 2 (SIM #1)"),
            CsWindow(hwnd=102, title="Counter-Strike 2 (SIM #2)"),
        ]

    _require_windows()
    import win32gui

    found: list[CsWindow] = []

    def _enum(hwnd: int, _ctx) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd) or ""
        lower = title.lower()
        if any(part in lower for part in _CS_TITLE_PARTS):
            found.append(CsWindow(hwnd=hwnd, title=title))

    win32gui.EnumWindows(_enum, None)
    return found


def move_all_cs_windows(
    *,
    config: AppConfig | None = None,
    start_x: int = 0,
    start_y: int = 0,
    step_x: int = 40,
    step_y: int = 40,
) -> MoveResult:
    """
    Раскладка окон каскадом (recovery после наложения/зависания UI).
    cs_resolution = client area (совпадает с coords yaml base).
    """
    if config is None:
        from config.loader import load_config

        config = load_config()

    width, height = parse_resolution(config.cs_resolution)
    windows = list_cs_windows()
    if not windows:
        raise UtilsError("no CS2/CSGO windows found")

    if _sim_enabled():
        return MoveResult(
            moved=windows,
            width=width,
            height=height,
            simulated=True,
        )

    _require_windows()
    import win32con
    import win32gui

    moved: list[CsWindow] = []
    for idx, win in enumerate(windows):
        x = start_x + idx * step_x
        y = start_y + idx * step_y
        try:
            win32gui.ShowWindow(win.hwnd, win32con.SW_RESTORE)
            outer_w, outer_h = outer_size_for_client(win.hwnd, width, height)
            win32gui.MoveWindow(win.hwnd, x, y, outer_w, outer_h, True)
            moved.append(win)
        except Exception as exc:
            raise UtilsError(f"MoveWindow failed for {win.title!r}: {exc}") from exc

    return MoveResult(moved=moved, width=width, height=height)
