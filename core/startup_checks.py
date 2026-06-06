"""Диагностика при старте панели (B-PACKAGE)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from config.loader import load_config
from config.paths import get_app_root, get_data_dir, get_fsm_import_dir, is_frozen
from config.schema import AppConfig

APP_VERSION = "0.1.0-prototype"


def format_startup_banner(config: AppConfig) -> list[str]:
    lines = [
        f"Farm Panel v{APP_VERSION}",
        f"app_root: {get_app_root()}",
        f"data_dir: {get_data_dir()}",
        f"frozen: {is_frozen()}",
        f"test_mode: {config.test_mode}",
        f"python: {sys.version.split()[0]}",
    ]
    return lines


def collect_startup_warnings(config: AppConfig | None = None) -> list[str]:
    cfg = config or load_config()
    warnings: list[str] = []
    root = get_app_root()

    if sys.platform != "win32":
        warnings.append("not Windows — real farm (Steam/CS2/win32) unavailable")
    else:
        steam_raw = cfg.steam_path.strip().strip('"')
        if not steam_raw:
            warnings.append("steam_path empty — set in Config #1")
        else:
            steam_p = Path(steam_raw)
            if not steam_p.is_file():
                warnings.append(f"steam_path file missing: {steam_p}")
        cs2_raw = cfg.cs2_path.strip().strip('"')
        if not cs2_raw:
            warnings.append("cs2_path empty — set in Config #1")
        else:
            cs2_p = Path(cs2_raw)
            if not cs2_p.is_file():
                warnings.append(f"cs2_path file missing: {cs2_p}")

    if cfg.test_mode:
        warnings.append("test_mode=true in config — using fake modules")

    if shutil.which("node") is None:
        warnings.append("Node.js not on PATH — looter will fail")
    else:
        looter_nm = root / "vendor" / "looter" / "node_modules"
        if not looter_nm.is_dir():
            warnings.append(
                "vendor/looter/node_modules missing — run: cd vendor\\looter && npm install"
            )

    if not (root / "vendor" / "looter" / "looter_core.js").is_file():
        warnings.append("vendor/looter/looter_core.js missing")
    steam_coords_705 = root / "resources" / "ui_nav" / "steam_login_705x440.yaml"
    steam_coords_1920 = root / "resources" / "ui_nav" / "steam_login_1920x1080.yaml"
    mode = getattr(cfg, "steam_login_mode", "gui")
    if cfg.steam_auto_login and sys.platform == "win32" and not cfg.test_mode:
        if mode in ("gui", "gui_then_api"):
            if not steam_coords_705.is_file():
                warnings.append(
                    "resources/ui_nav/steam_login_705x440.yaml missing — "
                    "GUI login (ArmoryFarm 705×440)"
                )
            if not (root / "vendor" / "looter" / "totp_once.js").is_file():
                warnings.append("vendor/looter/totp_once.js missing — Steam Guard TOTP")
        if mode in ("gui", "gui_then_api") and not steam_coords_1920.is_file():
            warnings.append(
                "resources/ui_nav/steam_login_1920x1080.yaml missing — GUI fallback coords"
            )
        if mode in ("api", "gui_then_api"):
            if not (root / "vendor" / "looter" / "steam_login.js").is_file():
                warnings.append("vendor/looter/steam_login.js missing")
            elif shutil.which("node") and not (
                root / "vendor" / "looter" / "node_modules"
            ).is_dir():
                warnings.append(
                    "steam api login needs vendor/looter/node_modules — npm install"
                )

    if not (root / "resources" / "cs2" / "fsm.cfg").is_file():
        warnings.append("resources/cs2/fsm.cfg missing")

    cs_res = (cfg.cs_resolution or "360x270").lower().replace(" ", "")
    if cs_res != "360x270":
        coords_path = root / "resources" / "ui_nav" / f"coords_{cs_res}.yaml"
        if not coords_path.is_file():
            warnings.append(
                f"coords_{cs_res}.yaml missing — set cs_resolution or add profile "
                f"(see docs/AI_PC_PROFILE.md)"
            )
        drop_path = root / "resources" / "ui_nav" / f"drop_slots_{cs_res}.yaml"
        if not drop_path.is_file():
            warnings.append(
                f"drop_slots_{cs_res}.yaml missing for cs_resolution={cs_res}"
            )
        video_profile = root / "resources" / "cs2" / "profiles" / cs_res / "cs2_video.txt"
        if not video_profile.is_file():
            warnings.append(
                f"cs2 video profile missing: profiles/{cs_res}/cs2_video.txt "
                f"(will fallback to 360x270 video.txt)"
            )

    from modules.combat import csgobot_ai

    bot = cfg.bot_mode.value if hasattr(cfg.bot_mode, "value") else str(cfg.bot_mode)
    if bot in ("auto", "ai"):
        if not csgobot_ai.is_installed():
            warnings.append("csgobot not installed — AI mode will use simple bot")
        elif csgobot_ai.python_executable() is None:
            warnings.append("csgobot venv missing — run setup in vendor/csgobot")

    if not get_data_dir().exists():
        warnings.append("data/ will be created on first config save")

    vault = get_data_dir() / "vault.enc"
    if not vault.is_file() and not cfg.test_mode:
        from modules.vault.fsm_import import is_import_staging_empty

        import_dir = get_fsm_import_dir()
        if is_import_staging_empty(cfg):
            warnings.append(
                f"no accounts in vault — put logpass.txt and maFiles/ in "
                f"{import_dir} → Utils: Import from logpass "
                f"(see docs/FSM_ACCOUNT_IMPORT.md)"
            )
        else:
            warnings.append(
                "vault empty but import folder has data — "
                "click Import from logpass in Utils #1"
            )

    return warnings
