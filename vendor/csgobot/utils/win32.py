from typing import Tuple, Optional


def get_window_rect(
    window_title: str,
    border_offsets: Tuple[int, int, int, int] = (0, 0, 0, 0),
) -> Tuple[int, int, int, int]:
    import win32gui

    if not window_title:
        raise ValueError("Window title cannot be empty")

    hwnd = win32gui.FindWindow(None, window_title)
    if not hwnd:
        raise ValueError(f"Window not found: {window_title}")

    rect = list(win32gui.GetWindowRect(hwnd))

    width = rect[2] - rect[0]
    height = rect[3] - rect[1]

    left = rect[0] + border_offsets[0]
    top = rect[1] + border_offsets[1]
    width -= border_offsets[0] + border_offsets[2]
    height -= border_offsets[1] + border_offsets[3]

    return (left, top, width, height)


def find_window(title: str) -> Optional[int]:
    import win32gui
    return win32gui.FindWindow(None, title) or None


def focus_window_hwnd(hwnd: int) -> bool:
    """Bring CS2 to foreground so buy binds receive SendInput."""
    if not hwnd:
        return False
    try:
        import time

        import win32con
        import win32gui
        import win32process

        if not win32gui.IsWindow(hwnd):
            return False
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        foreground = win32gui.GetForegroundWindow()
        fg_thread = win32process.GetWindowThreadProcessId(foreground)[0]
        target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
        attach_fn = getattr(win32process, "AttachThreadInput", None)
        attached = False
        if (
            attach_fn is not None
            and fg_thread
            and target_thread
            and fg_thread != target_thread
        ):
            attach_fn(fg_thread, target_thread, True)
            attached = True
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        finally:
            if attached and attach_fn is not None:
                attach_fn(fg_thread, target_thread, False)
        time.sleep(0.05)
        return win32gui.GetForegroundWindow() == hwnd
    except Exception:
        return False


def get_foreground_window_title() -> str:
    import win32gui
    hwnd = win32gui.GetForegroundWindow()
    return win32gui.GetWindowText(hwnd)
