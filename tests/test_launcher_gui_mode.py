"""Launcher integration: steam_login_mode gui / gui_then_api."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from config.schema import AppConfig
from core.events import EventType
from modules.launcher import run as launcher_run
from modules.launcher.steam_auth import SteamAuthResult
from modules.launcher.steam_gui_login import SteamGuiLoginResult


@patch("modules.launcher.ArtifactStore")
@patch("modules.ui_nav.window.wait_for_cs2_main_menu")
@patch("modules.ui_nav.coords.load_nav_coords_for_hwnd")
@patch("modules.ui_nav.window.wait_for_cs2_hwnd", return_value=12345)
@patch("modules.launcher.steam_promo_dismiss.dismiss_steam_promo")
@patch("modules.launcher.cs2.launch_cs2")
@patch("modules.launcher.steam.launch_steam")
@patch("modules.launcher.steam_auth.login_steam_account")
@patch("modules.launcher.steam_gui_login.login_steam_gui")
@patch("modules.launcher.proxy_check.check_proxy", return_value=(True, "ok"))
@patch("modules.launcher.cleanup.kill_all")
def test_launcher_gui_mode(
    _kill: MagicMock,
    _proxy: MagicMock,
    mock_gui: MagicMock,
    mock_api: MagicMock,
    mock_steam: MagicMock,
    mock_cs2: MagicMock,
    mock_dismiss: MagicMock,
    mock_load_coords: MagicMock,
    _wait_menu: MagicMock,
    _wait_cs2: MagicMock,
    _artifact_store: MagicMock,
    monkeypatch,
) -> None:
    from modules.launcher.steam_promo_dismiss import SteamPromoDismissResult
    from modules.ui_nav.coords import load_nav_coords

    monkeypatch.setattr("sys.platform", "win32")
    mock_gui.return_value = SteamGuiLoginResult(ok=True, login="u1", detail="gui ok")
    mock_load_coords.return_value = load_nav_coords("360x270")
    mock_dismiss.return_value = SteamPromoDismissResult(
        dismissed=0, found=0, detail="main only — no promo"
    )
    mock_steam.return_value = MagicMock(poll=MagicMock(return_value=None))
    mock_cs2.return_value = MagicMock(poll=MagicMock(return_value=None))

    emitted: list[tuple[EventType, str]] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        emitted.append((event, detail))

    cfg = AppConfig(
        steam_path=r"C:\Steam\steam.exe",
        cs2_path=r"C:\CS2\cs2.exe",
        steam_auto_login=True,
        steam_login_mode="gui",
    )
    assert launcher_run({"login": "u1", "emit": emit, "config": cfg}) is True
    mock_gui.assert_called_once()
    mock_api.assert_not_called()
    assert EventType.STEAM_LOGIN_OK in [e for e, _ in emitted]


@patch("modules.launcher.ArtifactStore")
@patch("modules.ui_nav.window.wait_for_cs2_main_menu")
@patch("modules.ui_nav.coords.load_nav_coords_for_hwnd")
@patch("modules.ui_nav.window.wait_for_cs2_hwnd", return_value=12345)
@patch("modules.launcher.steam_promo_dismiss.dismiss_steam_promo")
@patch("modules.launcher.cs2.launch_cs2")
@patch("modules.launcher.steam.launch_steam")
@patch("modules.launcher.steam_auth.login_steam_account")
@patch("modules.launcher.steam_gui_login.login_steam_gui")
@patch("modules.launcher.proxy_check.check_proxy", return_value=(True, "ok"))
@patch("modules.launcher.cleanup.kill_all")
def test_launcher_gui_then_api_fallback(
    _kill: MagicMock,
    _proxy: MagicMock,
    mock_gui: MagicMock,
    mock_api: MagicMock,
    mock_steam: MagicMock,
    mock_cs2: MagicMock,
    mock_dismiss: MagicMock,
    mock_load_coords: MagicMock,
    _wait_menu: MagicMock,
    _wait_cs2: MagicMock,
    _artifact_store: MagicMock,
    monkeypatch,
) -> None:
    from modules.launcher.steam_promo_dismiss import SteamPromoDismissResult
    from modules.ui_nav.coords import load_nav_coords

    monkeypatch.setattr("sys.platform", "win32")
    mock_gui.return_value = SteamGuiLoginResult(
        ok=False, login="u1", detail="coords miss"
    )
    mock_load_coords.return_value = load_nav_coords("360x270")
    mock_dismiss.return_value = SteamPromoDismissResult(
        dismissed=0, found=0, detail="main only — no promo"
    )
    mock_api.return_value = SteamAuthResult(ok=True, login="u1", detail="api ok")
    mock_steam.return_value = MagicMock(poll=MagicMock(return_value=None))
    mock_cs2.return_value = MagicMock(poll=MagicMock(return_value=None))

    cfg = AppConfig(
        steam_path=r"C:\Steam\steam.exe",
        cs2_path=r"C:\CS2\cs2.exe",
        steam_auto_login=True,
        steam_login_mode="gui_then_api",
    )
    assert launcher_run({"login": "u1", "emit": lambda *a, **k: None, "config": cfg})
    mock_gui.assert_called_once()
    mock_api.assert_called_once()
