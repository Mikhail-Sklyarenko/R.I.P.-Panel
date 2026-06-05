"""Запуск Steam с опциями из resources/launch_options.txt."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from config.schema import AppConfig
from modules.launcher.errors import LauncherError, LauncherPlatformError
from modules.launcher.options import get_steam_launch_argv


def _require_windows() -> None:
    if sys.platform != "win32":
        raise LauncherPlatformError("steam launch is Windows-only")


def resolve_steam_exe(config: AppConfig) -> Path:
    raw = (config.steam_path or "").strip().strip('"')
    if not raw:
        raise LauncherError("steam_path is empty — set in Config #1")
    path = Path(raw)
    if path.is_dir():
        path = path / "steam.exe"
    if not path.is_file():
        raise LauncherError(f"steam.exe not found: {path}")
    return path.resolve()


def build_steam_command(config: AppConfig) -> list[str]:
    exe = resolve_steam_exe(config)
    return [
        str(exe),
        *get_steam_launch_argv(classic_ui=config.steam_classic_login_ui),
    ]


def launch_steam(config: AppConfig) -> subprocess.Popen[str]:
    """Старт Steam client (GUI); учётные данные — steam_auth.login_steam_account."""
    _require_windows()
    cmd = build_steam_command(config)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except OSError as exc:
        raise LauncherError(f"failed to start Steam: {exc}") from exc
    if proc.poll() is not None:
        raise LauncherError("Steam process exited immediately")
    return proc
