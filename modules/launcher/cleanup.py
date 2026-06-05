"""Завершение процессов CS2 / Steam (Windows)."""

from __future__ import annotations

import subprocess
import sys
from typing import Iterable

from modules.launcher.errors import LauncherError, LauncherPlatformError


def _require_windows() -> None:
    if sys.platform != "win32":
        raise LauncherPlatformError("cleanup is Windows-only")


def _taskkill(image_names: Iterable[str], *, tree: bool = False) -> list[str]:
    _require_windows()
    killed: list[str] = []
    for name in image_names:
        args = ["taskkill", "/IM", name, "/F"]
        if tree:
            args.insert(1, "/T")
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        if result.returncode == 0:
            killed.append(name)
    return killed


def kill_cs2() -> list[str]:
    return _taskkill(["cs2.exe", "csgo.exe"])


def kill_steam() -> list[str]:
    return _taskkill(["steam.exe", "steamwebhelper.exe"], tree=True)


def kill_all() -> dict[str, list[str]]:
    return {"cs2": kill_cs2(), "steam": kill_steam()}


def cleanup_session(*, steam: bool = True, cs2: bool = True) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if cs2:
        out["cs2"] = kill_cs2()
    if steam:
        out["steam"] = kill_steam()
    if not out:
        return out
    return out
