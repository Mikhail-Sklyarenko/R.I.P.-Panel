"""Клики и клавиши в окне CS2 (Windows SendInput / win32api)."""

from __future__ import annotations

import sys
import time

from modules.ui_nav.coords import Point
from modules.ui_nav.errors import UiNavError, UiNavPlatformError
from modules.ui_nav.window import is_valid_hwnd


def _require_live_hwnd(hwnd: int) -> None:
    if not is_valid_hwnd(hwnd):
        raise UiNavError(f"window closed or invalid (hwnd={hwnd})")


def _win32_ui_call(hwnd: int, action: str, fn) -> None:
    _require_live_hwnd(hwnd)
    try:
        fn()
    except UiNavError:
        raise
    except Exception as exc:
        raise UiNavError(f"{action} failed: {exc}") from exc


def focus_window(hwnd: int) -> None:
    if sys.platform != "win32":
        raise UiNavPlatformError("focus_window is Windows-only")
    import win32api
    import win32con
    import win32gui
    import win32process

    def _do() -> None:
        if not is_valid_hwnd(hwnd):
            raise UiNavError(f"window closed or invalid (hwnd={hwnd})")
        foreground = win32gui.GetForegroundWindow()
        if foreground == hwnd:
            return
        foreground_thread = win32process.GetWindowThreadProcessId(foreground)[0]
        target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
        attached = False
        if foreground_thread and foreground_thread != target_thread:
            win32api.AttachThreadInput(foreground_thread, target_thread, True)
            attached = True
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        finally:
            if attached:
                win32api.AttachThreadInput(foreground_thread, target_thread, False)
        time.sleep(0.15)

    _win32_ui_call(hwnd, "focus_window", _do)


def click_client(hwnd: int, point: Point) -> None:
    if sys.platform != "win32":
        raise UiNavPlatformError("click is Windows-only")
    import win32api
    import win32con
    import win32gui

    def _do() -> None:
        focus_window(hwnd)
        sx, sy = win32gui.ClientToScreen(hwnd, (point.x, point.y))
        win32api.SetCursorPos((sx, sy))
        time.sleep(0.05)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
        time.sleep(0.1)

    _win32_ui_call(hwnd, "click_client", _do)


def select_all(hwnd: int) -> None:
    """Ctrl+A в активном окне (очистка поля перед paste)."""
    if sys.platform != "win32":
        raise UiNavPlatformError("select_all is Windows-only")
    import win32api
    import win32con

    def _do() -> None:
        focus_window(hwnd)
        VK_CONTROL = 0x11
        VK_A = 0x41
        win32api.keybd_event(VK_CONTROL, 0, 0, 0)
        win32api.keybd_event(VK_A, 0, 0, 0)
        win32api.keybd_event(VK_A, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.05)

    _win32_ui_call(hwnd, "select_all", _do)


def paste_text(hwnd: int, text: str) -> None:
    """Вставка через буфер обмена + Ctrl+V (без логирования text)."""
    if sys.platform != "win32":
        raise UiNavPlatformError("paste_text is Windows-only")
    import win32api
    import win32clipboard
    import win32con

    def _do() -> None:
        focus_window(hwnd)
        old_clip: str | None = None
        try:
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    old_clip = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            except Exception:
                old_clip = None
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()

        VK_CONTROL = 0x11
        VK_V = 0x56
        win32api.keybd_event(VK_CONTROL, 0, 0, 0)
        win32api.keybd_event(VK_V, 0, 0, 0)
        win32api.keybd_event(VK_V, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.12)

        if old_clip is not None:
            try:
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, old_clip)
            finally:
                win32clipboard.CloseClipboard()

    _win32_ui_call(hwnd, "paste_text", _do)


def press_return(hwnd: int) -> None:
    """Enter — отправка формы (Steam Sign in / Guard submit)."""
    if sys.platform != "win32":
        raise UiNavPlatformError("press_return is Windows-only")
    import win32api
    import win32con

    def _do() -> None:
        focus_window(hwnd)
        VK_RETURN = 0x0D
        win32api.keybd_event(VK_RETURN, 0, 0, 0)
        win32api.keybd_event(VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.15)

    _win32_ui_call(hwnd, "press_return", _do)


def press_escape(hwnd: int) -> None:
    """Escape — dismiss modal dialogs (Steam promo)."""
    if sys.platform != "win32":
        raise UiNavPlatformError("press_escape is Windows-only")
    import win32api
    import win32con

    def _do() -> None:
        focus_window(hwnd)
        VK_ESCAPE = 0x1B
        win32api.keybd_event(VK_ESCAPE, 0, 0, 0)
        win32api.keybd_event(VK_ESCAPE, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.15)

    _win32_ui_call(hwnd, "press_escape", _do)


def close_window(hwnd: int) -> None:
    """WM_CLOSE — close top-level window without killing process."""
    if sys.platform != "win32":
        raise UiNavPlatformError("close_window is Windows-only")
    import win32con
    import win32gui

    def _do() -> None:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        time.sleep(0.2)

    _win32_ui_call(hwnd, "close_window", _do)


def press_key(hwnd: int, key: str) -> None:
    """key: single char e.g. 'j' for disconnect bind."""
    if sys.platform != "win32":
        raise UiNavPlatformError("press_key is Windows-only")
    import win32api
    import win32con
    import win32gui

    focus_window(hwnd)
    vk = win32api.VkKeyScan(key)
    if vk == -1:
        return
    vk_code = vk & 0xFF
    win32api.keybd_event(vk_code, 0, 0, 0)
    win32api.keybd_event(vk_code, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.1)
