"""Panorama DM nav: strict detectors, hwnd autoscale, launcher menu wait."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from config.schema import AppConfig
from core.events import EventType
from modules.ui_nav.coords import load_nav_coords, load_nav_coords_for_hwnd
from modules.ui_nav.detectors import ScreenState, detect_state


def test_strict_in_dm_rejects_black_image() -> None:
    coords = load_nav_coords("360x270")
    img = Image.new("RGB", (360, 270), (0, 0, 0))
    assert detect_state(img, ScreenState.IN_DM, coords) is False


def test_strict_main_menu_rejects_black_image() -> None:
    coords = load_nav_coords("360x270")
    img = Image.new("RGB", (360, 270), (0, 0, 0))
    assert detect_state(img, ScreenState.MAIN_MENU, coords) is False


def test_autoscale_client_375x308(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    with patch("modules.ui_nav.window.client_size", return_value=(375, 308)):
        coords = load_nav_coords_for_hwnd(12345, "360x270")
    pt = coords.click("main_menu_play")
    assert pt.x == pytest.approx(187, abs=1)
    assert pt.y == pytest.approx(32, abs=1)


def test_load_nav_coords_for_hwnd_warns_on_mismatch(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    warnings: list[str] = []
    with patch("modules.ui_nav.window.client_size", return_value=(375, 308)):
        load_nav_coords_for_hwnd(99, "360x270", on_warn=warnings.append)
    assert any("375x308" in w for w in warnings)


@patch("modules.launcher.ArtifactStore")
@patch("modules.launcher.proxy_check.check_proxy", return_value=(True, "ip ok"))
@patch("modules.launcher.steam_promo_dismiss.dismiss_steam_promo")
@patch("modules.ui_nav.window.wait_for_cs2_main_menu")
@patch("modules.ui_nav.coords.load_nav_coords_for_hwnd")
@patch("modules.ui_nav.window.wait_for_cs2_hwnd", return_value=9999)
@patch("modules.launcher.cs2.launch_cs2")
@patch("modules.launcher.steam.launch_steam")
@patch("modules.launcher.steam_gui_login.login_steam_gui")
@patch("modules.launcher.cleanup.kill_cs2")
@patch("modules.launcher.cleanup.kill_all")
def test_launcher_waits_main_menu_before_cs2_ok(
    _kill_all: MagicMock,
    _kill_cs2: MagicMock,
    mock_gui: MagicMock,
    mock_steam: MagicMock,
    mock_cs2: MagicMock,
    mock_wait_hwnd: MagicMock,
    mock_load_coords: MagicMock,
    mock_wait_menu: MagicMock,
    mock_dismiss: MagicMock,
    _proxy: MagicMock,
    _artifact_store: MagicMock,
    monkeypatch,
) -> None:
    from modules.launcher import run
    from modules.launcher.steam_gui_login import SteamGuiLoginResult
    from modules.launcher.steam_promo_dismiss import SteamPromoDismissResult

    mock_gui.return_value = SteamGuiLoginResult(ok=True, login="u1", detail="ok")
    mock_dismiss.return_value = SteamPromoDismissResult(
        dismissed=0, found=0, detail="main only — no promo"
    )
    mock_load_coords.return_value = load_nav_coords("360x270")
    monkeypatch.setattr("sys.platform", "win32")

    emitted: list[tuple[EventType, str]] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        emitted.append((event, detail))

    cfg = AppConfig(
        steam_path=r"C:\Steam\steam.exe",
        cs2_path=r"C:\CS2\cs2.exe",
        steam_login_mode="gui",
    )
    assert run({"login": "u1", "emit": emit, "config": cfg}) is True
    mock_wait_menu.assert_called_once()
    cs2_detail = next(d for e, d in emitted if e == EventType.CS2_OK)
    assert "menu ready" in cs2_detail


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DM_NAV_SIM", "1")
    return tmp_path


def test_dm_navigator_logs_clicks_via_callback(data_dir, monkeypatch) -> None:
    monkeypatch.setenv("DM_NAV_SIM", "1")
    from modules.dm_runner.navigate import DmNavigator

    progress: list[str] = []
    nav = DmNavigator(
        config=AppConfig(map_load_delay_sec=10, game_search_timeout_sec=10, search_retries=1),
        session_id="navlog",
        login="u1",
        on_nav_progress=progress.append,
    )
    nav.navigate_to_dm_with_retries()
    assert any("dm click main_menu_play" in line for line in progress)
    assert any("dm click mode_deathmatch" in line for line in progress)
    assert any("dm click start_search" in line for line in progress)
