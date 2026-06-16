"""Launcher B4: options, DM cfg, only_launch_steam, proxy (no real Steam)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.loader import load_config, save_config
from config.paths import get_app_root
from config.schema import AppConfig
from core.events import EventType
from core.session_state import SessionState
from core.session_fsm import run_session
from modules.launcher import options, proxy_check
from modules.launcher.errors import LauncherPlatformError

FSM_CFG = get_app_root() / "resources" / "cs2" / "fsm.cfg"


def test_launch_options_match_fsm_defaults() -> None:
    steam = options.get_steam_launch_argv()
    cs2 = options.get_cs2_launch_argv()
    assert "-nofriendsui" in steam
    assert "-noreactlogin" in steam
    classic = options.get_steam_launch_argv(classic_ui=True)
    assert "-noreactlogin" not in classic
    assert "-language" in steam
    assert "english" in steam
    assert "-noverifyfiles" not in steam
    assert "-norepairfiles" not in steam
    assert "-windowed" in cs2
    assert "+violence_hblood" in cs2 or "0" in cs2


def test_build_cs2_command_uses_steam_applaunch_vac_safe(tmp_path) -> None:
    from modules.launcher.cs2 import FARM_PANEL_CFG, build_cs2_command

    win64 = tmp_path / "CS2" / "game" / "bin" / "win64"
    cfg_dir = tmp_path / "CS2" / "game" / "csgo" / "cfg"
    win64.mkdir(parents=True)
    cfg_dir.mkdir(parents=True)
    cs2_exe = win64 / "cs2.exe"
    cs2_exe.write_bytes(b"")
    steam_exe = tmp_path / "steam.exe"
    steam_exe.write_bytes(b"")
    cfg = AppConfig(
        steam_path=str(steam_exe),
        cs2_path=str(cs2_exe),
        cs_resolution="360x270",
        cs2_vac_safe_launch=True,
    )
    cmd = build_cs2_command(cfg)
    assert cmd[0] == str(steam_exe.resolve())
    assert cmd[1:3] == ["-applaunch", "730"]
    assert cmd[-1] == FARM_PANEL_CFG
    assert (cfg_dir / FARM_PANEL_CFG).is_file()
    assert "-console" in cmd
    assert not (cfg_dir / "video.txt").exists()


def test_build_cs2_command_legacy_deploy_when_vac_safe_off(tmp_path) -> None:
    from modules.launcher.cs2 import FARM_PANEL_CFG, build_cs2_command

    win64 = tmp_path / "CS2" / "game" / "bin" / "win64"
    cfg_dir = tmp_path / "CS2" / "game" / "csgo" / "cfg"
    win64.mkdir(parents=True)
    cfg_dir.mkdir(parents=True)
    cs2_exe = win64 / "cs2.exe"
    cs2_exe.write_bytes(b"")
    steam_exe = tmp_path / "steam.exe"
    steam_exe.write_bytes(b"")
    cfg = AppConfig(
        steam_path=str(steam_exe),
        cs2_path=str(cs2_exe),
        cs_resolution="360x270",
        cs2_vac_safe_launch=False,
    )
    cmd = build_cs2_command(cfg)
    assert cmd[-1] == FARM_PANEL_CFG
    assert (cfg_dir / "video.txt").is_file()


def test_fsm_cfg_deathmatch_adaptation() -> None:
    text = FSM_CFG.read_text(encoding="utf-8")
    active = "\n".join(
        ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("//")
    )
    assert "scrimcomp2v2" not in active
    assert "deathmatch" in text
    assert "game_type 1" in text
    assert "game_mode 2" in text
    assert "player_competitive_maplist_2v2" not in text


def test_proxy_check_skipped_when_empty() -> None:
    ok, msg = proxy_check.check_proxy("")
    assert ok is True
    assert "skipped" in msg


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    from config.loader import ensure_config

    ensure_config()
    return tmp_path


def test_only_launch_steam_session_done(data_dir, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_SESSION_SECONDS", "0.1")
    cfg = load_config()
    save_config(
        cfg.model_copy(
            update={
                "only_launch_steam": True,
                "test_mode": True,
                "steam_auto_login": True,
            }
        )
    )
    logs: list[str] = []
    final = run_session(
        "acc1",
        test_mode=True,
        on_main=logs.append,
    )
    assert final is SessionState.DONE
    joined = "\n".join(logs)
    assert "steam_ok" in joined
    assert "only_launch_steam" in joined
    assert "cs2_ok" not in joined
    assert "DONE" in joined


@patch("modules.launcher.proxy_check.check_proxy", return_value=(True, "ip ok"))
@patch("modules.launcher.steam_promo_dismiss.dismiss_steam_promo")
@patch("modules.launcher.cs2.launch_cs2")
@patch("modules.launcher.steam.launch_steam")
@patch("modules.launcher.steam_gui_login.login_steam_gui")
@patch("modules.launcher.cleanup.kill_cs2")
@patch("modules.launcher.cleanup.kill_all")
def test_launcher_only_steam_windows(
    _kill_all: MagicMock,
    _kill_cs2: MagicMock,
    mock_gui: MagicMock,
    mock_steam: MagicMock,
    mock_cs2: MagicMock,
    mock_dismiss: MagicMock,
    _proxy: MagicMock,
    monkeypatch,
) -> None:
    from modules.launcher.steam_gui_login import SteamGuiLoginResult
    from modules.launcher.steam_promo_dismiss import SteamPromoDismissResult

    mock_gui.return_value = SteamGuiLoginResult(ok=True, login="u1", detail="ok")
    mock_dismiss.return_value = SteamPromoDismissResult(
        dismissed=0, found=0, detail="main only — no promo"
    )
    monkeypatch.setattr("sys.platform", "win32")
    emitted: list[tuple[EventType, str]] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        emitted.append((event, detail))

    cfg = AppConfig(
        steam_path=r"C:\Steam\steam.exe",
        cs2_path=r"C:\Steam\steamapps\common\Counter-Strike Global Offensive\game\bin\win64\cs2.exe",
        only_launch_steam=True,
        steam_login_mode="gui",
    )
    mock_steam.return_value = MagicMock(poll=MagicMock(return_value=None))

    from modules.launcher import run

    ctx: dict = {"login": "u1", "emit": emit, "config": cfg}
    assert run(ctx) is True
    assert ctx.get("stop_after_steam") is True
    mock_steam.assert_called_once()
    mock_cs2.assert_not_called()
    assert any(e == EventType.STEAM_OK for e, _ in emitted)


def test_launcher_requires_windows_when_not_test(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    from modules.launcher import run

    ok = run(
        {
            "login": "x",
            "emit": lambda *a, **k: None,
            "config": AppConfig(steam_path=r"C:\Steam\steam.exe"),
        }
    )
    assert ok is False
