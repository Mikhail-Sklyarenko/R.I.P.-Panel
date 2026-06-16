"""Run commands in CS2 developer console (cfg exec, buy, …)."""

from __future__ import annotations

import time

from modules.ui_nav.actions import focus_window, paste_text, press_return
from modules.ui_nav.errors import UiNavError, UiNavPlatformError

# Default toggleconsole key (US layout `). Works on most RU layouts too.
_CONSOLE_VK = 0xC0


def _toggle_console(hwnd: int) -> None:
    import win32api
    import win32con

    focus_window(hwnd)
    win32api.keybd_event(_CONSOLE_VK, 0, 0, 0)
    win32api.keybd_event(_CONSOLE_VK, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.2)


def run_cs2_console_commands(hwnd: int, *commands: str) -> None:
    """Open console, run one or more commands, close console."""
    import sys

    if sys.platform != "win32":
        raise UiNavPlatformError("run_cs2_console_commands is Windows-only")

    lines = [c.strip() for c in commands if c and str(c).strip()]
    if not lines:
        raise UiNavError("empty console command list")

    _toggle_console(hwnd)
    try:
        for line in lines:
            paste_text(hwnd, line)
            press_return(hwnd)
            time.sleep(0.12)
    finally:
        _toggle_console(hwnd)
