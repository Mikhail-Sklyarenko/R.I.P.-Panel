"""Application window icon (taskbar + title bar)."""

from __future__ import annotations

import sys
from pathlib import Path

from config.paths import get_resources_dir

_APP_ICON_NAMES = ("farm_panel.ico", "farm_panel.png")


def app_icon_path() -> Path | None:
    app_dir = get_resources_dir() / "app"
    for name in _APP_ICON_NAMES:
        path = app_dir / name
        if path.is_file():
            return path
    return None


def apply_window_icon(root) -> None:
    """Set CTk/Tk window icon from resources/app/farm_panel.ico."""
    icon = app_icon_path()
    if icon is None:
        return
    try:
        if sys.platform == "win32" and icon.suffix.lower() == ".ico":
            root.iconbitmap(str(icon))
            return
        if icon.suffix.lower() == ".png":
            from PIL import Image, ImageTk

            photo = ImageTk.PhotoImage(Image.open(icon))
            root.iconphoto(True, photo)
            root._farm_panel_icon_photo = photo  # prevent GC
    except Exception:
        pass
