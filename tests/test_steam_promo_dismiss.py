"""B-STEAM-PROMO-DISMISS: Steam sale banner detect/close."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from config.schema import AppConfig
from modules.launcher.steam_promo_dismiss import dismiss_steam_promo
from modules.ui_nav.steam_window import (
    SteamWindowKind,
    SteamWindowMatch,
    title_indicates_promo,
)


def test_title_indicates_promo_rgg_sale() -> None:
    assert title_indicates_promo("RGG Studio Sale")
    assert title_indicates_promo("Steam Summer Sale")
    assert not title_indicates_promo("Sign in to Steam")
    assert not title_indicates_promo("Steam")
    assert title_indicates_promo("Special Discount Event")


def test_no_promo_main_only(monkeypatch) -> None:
    monkeypatch.delenv("STEAM_GUI_LOGIN_SIM", raising=False)
    monkeypatch.setattr("sys.platform", "win32")
    main = SteamWindowMatch(1, "Steam", SteamWindowKind.MAIN)
    with (
        patch(
            "modules.launcher.steam_promo_dismiss.logged_in_main_visible",
            return_value=main,
        ),
        patch(
            "modules.launcher.steam_promo_dismiss.login_window_open",
            return_value=False,
        ),
        patch(
            "modules.launcher.steam_promo_dismiss.find_steam_promo_windows",
            return_value=[],
        ),
    ):
        result = dismiss_steam_promo("u1", AppConfig())
    assert result.dismissed == 0
    assert result.found == 0
    assert "main only" in result.detail


def test_promo_detected_and_dismissed(monkeypatch) -> None:
    monkeypatch.delenv("STEAM_GUI_LOGIN_SIM", raising=False)
    monkeypatch.setattr("sys.platform", "win32")
    main = SteamWindowMatch(1, "Steam", SteamWindowKind.MAIN)
    promo = SteamWindowMatch(2, "RGG Studio Sale", SteamWindowKind.OTHER)

    with (
        patch(
            "modules.launcher.steam_promo_dismiss.logged_in_main_visible",
            return_value=main,
        ),
        patch(
            "modules.launcher.steam_promo_dismiss.login_window_open",
            return_value=False,
        ),
        patch(
            "modules.launcher.steam_promo_dismiss.find_steam_promo_windows",
            side_effect=[[promo], [], []],
        ),
        patch(
            "modules.launcher.steam_promo_dismiss._load_main_coords",
            return_value=None,
        ),
        patch(
            "modules.launcher.steam_promo_dismiss._close_promo_window",
            return_value=True,
        ) as mock_close,
    ):
        result = dismiss_steam_promo("u1", AppConfig())

    assert result.dismissed == 1
    assert result.found == 1
    mock_close.assert_called_once()


def test_skip_when_login_open(monkeypatch) -> None:
    monkeypatch.delenv("STEAM_GUI_LOGIN_SIM", raising=False)
    monkeypatch.setattr("sys.platform", "win32")
    with patch(
        "modules.launcher.steam_promo_dismiss.login_window_open",
        return_value=True,
    ):
        result = dismiss_steam_promo("u1", AppConfig())
    assert result.skipped is True
    assert "login window open" in result.detail


def test_disabled_in_config(monkeypatch) -> None:
    monkeypatch.delenv("STEAM_GUI_LOGIN_SIM", raising=False)
    result = dismiss_steam_promo(
        "u1",
        AppConfig(steam_dismiss_promo=False),
    )
    assert result.skipped is True
    assert result.detail == "disabled"


def test_sim_env(monkeypatch) -> None:
    monkeypatch.setenv("STEAM_GUI_LOGIN_SIM", "1")
    result = dismiss_steam_promo("u1", AppConfig())
    assert result.skipped is True
    assert result.detail == "sim"


def test_soft_fail_still_returns_detail(monkeypatch) -> None:
    monkeypatch.delenv("STEAM_GUI_LOGIN_SIM", raising=False)
    monkeypatch.setattr("sys.platform", "win32")
    main = SteamWindowMatch(1, "Steam", SteamWindowKind.MAIN)
    promo = SteamWindowMatch(2, "RGG Studio Sale", SteamWindowKind.OTHER)

    with (
        patch(
            "modules.launcher.steam_promo_dismiss.logged_in_main_visible",
            return_value=main,
        ),
        patch(
            "modules.launcher.steam_promo_dismiss.login_window_open",
            return_value=False,
        ),
        patch(
            "modules.launcher.steam_promo_dismiss.find_steam_promo_windows",
            return_value=[promo],
        ),
        patch(
            "modules.launcher.steam_promo_dismiss._close_promo_window",
            return_value=False,
        ),
        patch(
            "modules.launcher.steam_promo_dismiss._load_main_coords",
            return_value=None,
        ),
        patch("modules.launcher.steam_promo_dismiss.is_valid_hwnd", return_value=True),
    ):
        result = dismiss_steam_promo(
            "u1",
            AppConfig(steam_promo_dismiss_timeout_sec=3),
        )

    assert result.dismissed == 0
    assert result.found >= 1
    assert "promo still visible" in result.detail


@patch("modules.ui_nav.window.wait_for_cs2_hwnd", return_value=12345)
@patch("modules.launcher.proxy_check.check_proxy", return_value=(True, "ip ok"))
@patch("modules.launcher.steam_promo_dismiss.dismiss_steam_promo")
@patch("modules.launcher.cs2.launch_cs2")
@patch("modules.launcher.steam.launch_steam")
@patch("modules.launcher.steam_gui_login.login_steam_gui")
@patch("modules.launcher.cleanup.kill_cs2")
@patch("modules.launcher.cleanup.kill_all")
def test_launcher_calls_dismiss_between_login_ok_and_steam_ok(
    _kill_all: MagicMock,
    _kill_cs2: MagicMock,
    mock_gui: MagicMock,
    mock_steam: MagicMock,
    mock_cs2: MagicMock,
    mock_dismiss: MagicMock,
    _proxy: MagicMock,
    _wait_cs2: MagicMock,
    monkeypatch,
) -> None:
    from core.events import EventType
    from modules.launcher.steam_gui_login import SteamGuiLoginResult
    from modules.launcher.steam_promo_dismiss import SteamPromoDismissResult
    from modules.launcher import run

    mock_gui.return_value = SteamGuiLoginResult(ok=True, login="u1", detail="ok")
    mock_dismiss.return_value = SteamPromoDismissResult(
        dismissed=1,
        found=1,
        detail="dismissed 1 promo window(s)",
    )
    monkeypatch.setattr("sys.platform", "win32")
    emitted: list[tuple[EventType, str]] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        emitted.append((event, detail))

    cfg = AppConfig(
        steam_path=r"C:\Steam\steam.exe",
        cs2_path=r"C:\Steam\steamapps\common\Counter-Strike Global Offensive\game\bin\win64\cs2.exe",
        steam_login_mode="gui",
    )
    mock_steam.return_value = MagicMock(poll=MagicMock(return_value=None))

    assert run({"login": "u1", "emit": emit, "config": cfg}) is True
    mock_dismiss.assert_called_once_with("u1", cfg)

    events = [e for e, _ in emitted]
    assert EventType.STEAM_LOGIN_OK in events
    assert EventType.STEAM_OK in events
    login_ok_idx = events.index(EventType.STEAM_LOGIN_OK)
    steam_ok_idx = events.index(EventType.STEAM_OK)
    assert login_ok_idx < steam_ok_idx

    steam_ok_detail = next(d for e, d in emitted if e == EventType.STEAM_OK)
    assert "dismissed 1 promo" in steam_ok_detail


@patch("modules.ui_nav.window.wait_for_cs2_hwnd", return_value=12345)
@patch("modules.launcher.proxy_check.check_proxy", return_value=(True, "ip ok"))
@patch("modules.launcher.steam_promo_dismiss.dismiss_steam_promo")
@patch("modules.launcher.cs2.launch_cs2")
@patch("modules.launcher.steam.launch_steam")
@patch("modules.launcher.steam_gui_login.login_steam_gui")
@patch("modules.launcher.cleanup.kill_cs2")
@patch("modules.launcher.cleanup.kill_all")
def test_launcher_soft_fail_still_emits_steam_ok_and_cs2(
    _kill_all: MagicMock,
    _kill_cs2: MagicMock,
    mock_gui: MagicMock,
    mock_steam: MagicMock,
    mock_cs2: MagicMock,
    mock_dismiss: MagicMock,
    _proxy: MagicMock,
    _wait_cs2: MagicMock,
    monkeypatch,
) -> None:
    from core.events import EventType
    from modules.launcher.steam_gui_login import SteamGuiLoginResult
    from modules.launcher.steam_promo_dismiss import SteamPromoDismissResult
    from modules.launcher import run

    mock_gui.return_value = SteamGuiLoginResult(ok=True, login="u1", detail="ok")
    mock_dismiss.return_value = SteamPromoDismissResult(
        dismissed=0,
        found=1,
        detail="promo still visible (1 window(s))",
    )
    monkeypatch.setattr("sys.platform", "win32")
    emitted: list[EventType] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        emitted.append(event)

    cfg = AppConfig(
        steam_path=r"C:\Steam\steam.exe",
        cs2_path=r"C:\Steam\steamapps\common\Counter-Strike Global Offensive\game\bin\win64\cs2.exe",
        steam_login_mode="gui",
    )
    mock_steam.return_value = MagicMock(poll=MagicMock(return_value=None))

    assert run({"login": "u1", "emit": emit, "config": cfg}) is True
    assert EventType.STEAM_OK in emitted
    assert EventType.CS2_OK in emitted
    mock_cs2.assert_called_once()
