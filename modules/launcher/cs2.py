"""Запуск CS2 + деплой resources/cs2/* в cfg игры."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from config.paths import get_resources_dir
from config.schema import AppConfig
from modules.launcher.errors import LauncherError, LauncherPlatformError
from modules.launcher.options import get_cs2_launch_argv
from modules.launcher.steam import resolve_steam_exe

FARM_PANEL_CFG = "farm_panel.cfg"


def _resources_cs2() -> Path:
    return get_resources_dir() / "cs2"


def _parse_resolution(resolution: str) -> tuple[int, int]:
    raw = resolution.lower().replace(" ", "")
    w, h = raw.split("x", 1)
    return int(w), int(h)


def _video_profile_path(resolution: str) -> Path:
    w, h = _parse_resolution(resolution)
    profile = f"{w}x{h}"
    profile_path = _resources_cs2() / "profiles" / profile / "cs2_video.txt"
    if profile_path.is_file():
        return profile_path
    default = _resources_cs2() / "cs2_video.txt"
    if not default.is_file():
        raise LauncherError(f"missing resource: {default}")
    return default


def _require_windows() -> None:
    if sys.platform != "win32":
        raise LauncherPlatformError("cs2 launch is Windows-only")


def resolve_cs2_exe(config: AppConfig) -> Path:
    raw = (config.cs2_path or "").strip().strip('"')
    if not raw:
        raise LauncherError("cs2_path is empty — set in Config #1")
    path = Path(raw)
    if path.is_dir():
        for name in ("cs2.exe", "csgo.exe"):
            candidate = path / name
            if candidate.is_file():
                return candidate.resolve()
        raise LauncherError(f"cs2.exe not found under: {path}")
    if not path.is_file():
        raise LauncherError(f"cs2 executable not found: {path}")
    return path.resolve()


def find_csgo_cfg_dir(cs2_exe: Path) -> Path:
    """game/csgo/cfg рядом с установкой CS2 (cs2.exe в game/bin/win64)."""
    game_root = cs2_exe.parent
    if game_root.name.lower() == "win64":
        game_root = game_root.parent
    if game_root.name.lower() == "bin":
        game_root = game_root.parent
    candidates = [
        game_root / "csgo" / "cfg",
        game_root / "game" / "csgo" / "cfg",
    ]
    csgo_parent = game_root / "csgo"
    for cfg in candidates:
        if cfg.is_dir():
            return cfg
    if csgo_parent.is_dir() or game_root.name.lower() == "game":
        target = game_root / "csgo" / "cfg"
        target.mkdir(parents=True, exist_ok=True)
        return target
    raise LauncherError(f"csgo/cfg not found near {cs2_exe}")


def deploy_cs2_configs(
    cs2_exe: Path,
    resolution: str = "360x270",
    *,
    vac_safe: bool = False,
) -> str:
    """Deploy farm cfg; return +exec target (relative cfg name when vac_safe)."""
    cfg_dir = find_csgo_cfg_dir(cs2_exe)
    cfg_dir.mkdir(parents=True, exist_ok=True)
    fsm_cfg = _resources_cs2() / "fsm.cfg"
    if not fsm_cfg.is_file():
        raise LauncherError(f"missing resource: {fsm_cfg}")
    farm_cfg_path = cfg_dir / FARM_PANEL_CFG
    shutil.copy2(fsm_cfg, farm_cfg_path)

    if vac_safe:
        return FARM_PANEL_CFG

    video_src = _video_profile_path(resolution)
    shutil.copy2(video_src, cfg_dir / "video.txt")
    convars_src = _resources_cs2() / "cs2_machine_convars.vcfg"
    if not convars_src.is_file():
        raise LauncherError(f"missing resource: {convars_src}")
    shutil.copy2(convars_src, cfg_dir / convars_src.name)
    return str(fsm_cfg.resolve())


def build_cs2_command(config: AppConfig) -> list[str]:
    """Deploy cfg, then start CS2 via steam -applaunch 730 (VAC-safe, same as manual Play)."""
    vac_safe = bool(config.cs2_vac_safe_launch)
    exe = resolve_cs2_exe(config)
    exec_target = deploy_cs2_configs(exe, config.cs_resolution, vac_safe=vac_safe)
    steam_exe = resolve_steam_exe(config)
    cs2_argv = [*get_cs2_launch_argv(vac_safe=vac_safe), "+exec", exec_target]
    return [str(steam_exe), "-applaunch", "730", *cs2_argv]


def format_cs2_launch_log(cmd: list[str]) -> str:
    return "cs2 launch: " + " ".join(cmd)


def launch_cs2(
    config: AppConfig,
    *,
    on_log: Callable[[str], None] | None = None,
) -> subprocess.Popen[str]:
    _require_windows()
    cmd = build_cs2_command(config)
    if on_log:
        on_log(format_cs2_launch_log(cmd))
    try:
        proc = subprocess.Popen(cmd)
    except OSError as exc:
        raise LauncherError(f"failed to start CS2: {exc}") from exc
    if proc.poll() is not None:
        raise LauncherError("CS2 process exited immediately")
    return proc
