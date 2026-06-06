"""CS2 main menu wait: soft launcher probes, artifacts, timeout fallback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from config.schema import AppConfig
from core.events import EventType
from modules.ui_nav.coords import load_nav_coords
from modules.ui_nav.window import MainMenuWaitResult, wait_for_cs2_main_menu


def test_wait_for_cs2_main_menu_ok_soft_probe(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    coords = load_nav_coords("360x270")
    img = Image.new("RGB", (360, 270), color=(30, 30, 30))
    artifacts = MagicMock()
    call = {"n": 0}

    def fake_detect(_img, _state, _coords, *, min_match=None):
        call["n"] += 1
        return call["n"] >= 5

    def fake_probe_results(_img, _state, _coords):
        from modules.ui_nav.detectors import ProbeMatchResult

        call["n"] += 1
        hit = call["n"] >= 4
        return [
            ProbeMatchResult(
                matched=hit,
                x=217,
                y=26,
                actual_rgb=(30, 30, 30),
                expected_rgb=(238, 169, 41),
            )
        ]

    with patch("modules.ui_nav.capture.capture_client_with_black_retry", return_value=img):
        with patch("modules.ui_nav.detectors.detect_state", side_effect=fake_detect):
            with patch(
                "modules.ui_nav.detectors.probe_match_results",
                side_effect=fake_probe_results,
            ):
                result = wait_for_cs2_main_menu(
                    4242,
                    coords,
                    timeout_sec=2.0,
                    poll_sec=0.01,
                    artifacts=artifacts,
                    require_strict=False,
                    min_match=1,
                )
    assert result == MainMenuWaitResult(strict_ok=True, attempts=2, soft_peek=True)
    artifacts.save_image.assert_any_call("wait_main_menu_launch_1", img)
    artifacts.log_step.assert_any_call(
        "main_menu_detect_ok",
        attempt=2,
        strict=True,
    )


def test_wait_for_cs2_main_menu_timeout_returns_result(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    coords = load_nav_coords("360x270")
    img = Image.new("RGB", (360, 270), color=(0, 0, 0))
    artifacts = MagicMock()

    with patch("modules.ui_nav.capture.capture_client_with_black_retry", return_value=img):
        with patch("modules.ui_nav.detectors.detect_state", return_value=False):
            result = wait_for_cs2_main_menu(
                4242,
                coords,
                timeout_sec=0.15,
                poll_sec=0.05,
                artifacts=artifacts,
                min_match=1,
            )
    assert result.ok is False
    assert result.strict_ok is False
    assert result.timed_out is True
    assert result.attempts >= 1
    artifacts.save_image.assert_any_call("wait_main_menu_launch_timeout", img)
    artifacts.log_step.assert_any_call(
        "main_menu_detect_timeout",
        timeout_sec=pytest.approx(0.15),
        attempts=result.attempts,
    )


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
def test_launcher_sets_menu_confirmed_on_ok(
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
    mock_wait_menu.return_value = MainMenuWaitResult(strict_ok=True, attempts=1)
    monkeypatch.setattr("sys.platform", "win32")

    cfg = AppConfig(
        steam_path=r"C:\Steam\steam.exe",
        cs2_path=r"C:\CS2\cs2.exe",
        steam_login_mode="gui",
    )
    ctx: dict = {"login": "u1", "emit": lambda *a, **k: None, "config": cfg}
    assert run(ctx) is True
    assert ctx.get("cs2_menu_confirmed") is True
    assert ctx.get("cs2_menu_probe_warn") is not True


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
def test_launcher_menu_timeout_emits_cs2_ok_with_warn(
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
    mock_wait_menu.return_value = MainMenuWaitResult(strict_ok=False, timed_out=True, attempts=10)
    monkeypatch.setattr("sys.platform", "win32")

    emitted: list[tuple[EventType, str]] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        emitted.append((event, detail))

    cfg = AppConfig(
        steam_path=r"C:\Steam\steam.exe",
        cs2_path=r"C:\CS2\cs2.exe",
        steam_login_mode="gui",
        cs2_main_menu_wait_timeout_sec=120,
    )
    ctx: dict = {
        "login": "u1",
        "emit": emit,
        "config": cfg,
        "session_id": "sess-menu-warn",
    }
    assert run(ctx) is True
    assert ctx.get("cs2_menu_probe_warn") is True
    assert EventType.SESSION_FAILED not in [e for e, _ in emitted]
    cs2_detail = next(d for e, d in emitted if e == EventType.CS2_OK)
    assert "unconfirmed" in cs2_detail
    assert "trying dm nav" in cs2_detail
    assert mock_wait_menu.call_args.kwargs.get("require_strict") is True
    assert mock_wait_menu.call_args.kwargs.get("artifacts") is not None


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
def test_launcher_unconfirmed_when_not_strict(
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
    mock_wait_menu.return_value = MainMenuWaitResult(
        strict_ok=False, timed_out=True, attempts=5, soft_peek=True
    )
    monkeypatch.setattr("sys.platform", "win32")

    ctx: dict = {
        "login": "u1",
        "emit": lambda *a, **k: None,
        "config": AppConfig(
            steam_path=r"C:\Steam\steam.exe",
            cs2_path=r"C:\CS2\cs2.exe",
            steam_login_mode="gui",
        ),
    }
    assert run(ctx) is True
    assert ctx.get("cs2_menu_confirmed") is not True
    assert ctx.get("cs2_menu_probe_warn") is True
    assert ctx.get("cs2_menu_soft_peek") is True


def test_dm_runner_logs_menu_probe_warn(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DM_NAV_SIM", "1")
    from modules.dm_runner.navigate import DmNavigator

    progress: list[str] = []
    nav = DmNavigator(
        config=AppConfig(map_load_delay_sec=10, game_search_timeout_sec=10, search_retries=1),
        session_id="warn1",
        login="u1",
        menu_probe_warn=True,
        on_nav_progress=progress.append,
    )
    with patch.object(nav, "wait_main_menu"):
        nav._pre_click_main_menu_wait()
    assert any("soft probe wait" in line for line in progress)
