"""Panorama DM nav: strict detectors, hwnd autoscale, launcher menu wait."""

from __future__ import annotations

import json
from pathlib import Path

from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from config.schema import AppConfig
from core.events import EventType
from modules.ui_nav.coords import load_nav_coords, load_nav_coords_for_hwnd
from modules.ui_nav.detectors import ScreenState, detect_state
from modules.ui_nav.errors import UiNavTimeoutError
from modules.ui_nav.window import MainMenuWaitResult

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "armoryfarm" / "z3l9272eg3"
AI_PC_1280 = Path(__file__).resolve().parent / "fixtures" / "ai_pc" / "1280x720"


def test_1280_main_menu_play_fixture_detects_and_clicks_play_not_shop() -> None:
    coords = load_nav_coords("1280x720")
    img = Image.open(AI_PC_1280 / "main_menu_play.png").convert("RGB")
    img720 = img.resize((1280, 720), Image.Resampling.LANCZOS)
    assert detect_state(img720, ScreenState.MAIN_MENU, coords, min_match=2) is True
    play = coords.click("main_menu_play")
    shop_x = 736
    assert play.x < shop_x
    assert img720.getpixel((play.x, play.y))[0] > 200
    assert img720.getpixel((shop_x, 43))[2] < 120


def test_1280_play_dm_fixture_click_targets() -> None:
    coords = load_nav_coords("1280x720")
    dm = coords.click("mode_deathmatch")
    start = coords.click("start_search")
    assert dm.y < 130
    assert start.x > 1100 and start.y > 680


def test_armoryfarm_timeout_png_strict_main_menu() -> None:
    coords = load_nav_coords("360x270")
    img = Image.open(FIXTURES / "wait_main_menu_launch_timeout.png").convert("RGB")
    assert img.size == (360, 270)
    assert detect_state(img, ScreenState.MAIN_MENU, coords, min_match=2) is True
    assert detect_state(img, ScreenState.MAIN_MENU, coords, min_match=1) is True


def test_steps_jsonl_pattern_soft_peek_only_early() -> None:
    lines = (FIXTURES / "steps.jsonl").read_text(encoding="utf-8").strip().splitlines()
    probes = [json.loads(line) for line in lines if '"main_menu_probe"' in line]
    assert len(probes) == 223
    assert all(p.get("strict") == 0 for p in probes)
    soft_hits = [p for p in probes if p.get("matched") == 1]
    assert [p["attempt"] for p in soft_hits] == [10, 11, 12, 14]
    assert probes[-1]["attempt"] == 223
    assert probes[-1]["matched"] == 0


def test_dm_runner_fallback_after_menu_timeout(data_dir, monkeypatch) -> None:
    monkeypatch.setenv("DM_NAV_SIM", "1")
    from modules.dm_runner.navigate import DmNavigator

    coords = load_nav_coords("360x270")
    progress: list[str] = []
    nav = DmNavigator(
        config=AppConfig(
            map_load_delay_sec=10,
            game_search_timeout_sec=10,
            search_retries=1,
            cs2_main_menu_wait_timeout_sec=120,
        ),
        session_id="fallback1",
        login="u1",
        menu_probe_warn=True,
        on_nav_progress=progress.append,
    )

    with patch.object(nav, "wait_main_menu", side_effect=UiNavTimeoutError("timeout")):
        with patch.object(nav, "_click_target") as mock_click:
            assert nav._pre_click_main_menu_wait() is True
            mock_click.assert_called_once_with("main_menu_play")
    pt = coords.click("main_menu_play")
    assert pt.x == 217
    assert any("controlled click ИГРАТЬ @(217,14)" in line for line in progress)


def test_strict_in_dm_rejects_black_image() -> None:
    coords = load_nav_coords("360x270")
    img = Image.new("RGB", (360, 270), (0, 0, 0))
    assert detect_state(img, ScreenState.IN_DM, coords) is False


def test_strict_main_menu_rejects_black_image() -> None:
    coords = load_nav_coords("360x270")
    img = Image.new("RGB", (360, 270), (0, 0, 0))
    assert detect_state(img, ScreenState.MAIN_MENU, coords) is False


def test_main_menu_detects_synthetic_probe_colors() -> None:
    coords = load_nav_coords("360x270")
    img = Image.new("RGB", (360, 270), (0, 0, 0))
    for probe in coords.probes("main_menu"):
        img.putpixel((probe.x, probe.y), probe.rgb)
    assert detect_state(img, ScreenState.MAIN_MENU, coords) is True


def test_main_menu_probes_not_on_loadout_x168() -> None:
    coords = load_nav_coords("360x270")
    img = Image.new("RGB", (360, 270), (0, 0, 0))
    loadout_blue = (55, 110, 185)
    for probe in coords.probes("main_menu"):
        img.putpixel((168, probe.y), loadout_blue)
    assert detect_state(img, ScreenState.MAIN_MENU, coords) is False
    for probe in coords.probes("main_menu"):
        img.putpixel((probe.x, probe.y), probe.rgb)
    assert detect_state(img, ScreenState.MAIN_MENU, coords) is True


def test_autoscale_client_375x308(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    with patch("modules.ui_nav.window.client_size", return_value=(375, 308)):
        coords = load_nav_coords_for_hwnd(12345, "360x270")
    pt = coords.click("main_menu_play")
    assert pt.x == pytest.approx(226, abs=1)
    assert pt.y == pytest.approx(16, abs=1)


def test_load_nav_coords_for_hwnd_warns_on_mismatch(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    warnings: list[str] = []
    with patch("modules.ui_nav.window.client_size", return_value=(375, 308)):
        load_nav_coords_for_hwnd(99, "360x270", on_warn=warnings.append)
    assert any("375x308" in w for w in warnings)


@patch("modules.launcher.ArtifactStore")
@patch("modules.launcher.proxy_check.check_proxy", return_value=(True, "ip ok"))
@patch("modules.launcher.steam_promo_dismiss.dismiss_steam_promo")
@patch("modules.utils.windows.move_all_cs_windows")
@patch("modules.ui_nav.window.wait_for_cs2_main_menu")
@patch("modules.ui_nav.coords.load_nav_coords_for_hwnd")
@patch("modules.ui_nav.window.wait_for_cs2_hwnd", return_value=9999)
@patch("modules.launcher.cs2.launch_cs2")
@patch("modules.launcher.steam.launch_steam")
@patch("modules.launcher.steam_gui_login.login_steam_gui")
@patch("modules.launcher.cleanup.kill_cs2")
@patch("modules.launcher.cleanup.kill_all")
def test_launcher_moves_windows_before_menu_wait(
    _kill_all: MagicMock,
    _kill_cs2: MagicMock,
    mock_gui: MagicMock,
    mock_steam: MagicMock,
    mock_cs2: MagicMock,
    mock_wait_hwnd: MagicMock,
    mock_load_coords: MagicMock,
    mock_wait_menu: MagicMock,
    mock_move: MagicMock,
    mock_dismiss: MagicMock,
    _proxy: MagicMock,
    _artifact_store: MagicMock,
    monkeypatch,
) -> None:
    from modules.launcher import run
    from modules.launcher.steam_gui_login import SteamGuiLoginResult
    from modules.launcher.steam_promo_dismiss import SteamPromoDismissResult
    from modules.utils.windows import MoveResult

    mock_gui.return_value = SteamGuiLoginResult(ok=True, login="u1", detail="ok")
    mock_dismiss.return_value = SteamPromoDismissResult(
        dismissed=0, found=0, detail="main only — no promo"
    )
    mock_load_coords.return_value = load_nav_coords("360x270")
    mock_wait_menu.return_value = MainMenuWaitResult(strict_ok=True, attempts=1)
    mock_move.return_value = MoveResult(moved=[], width=360, height=270)
    monkeypatch.setattr("sys.platform", "win32")

    cfg = AppConfig(
        steam_path=r"C:\Steam\steam.exe",
        cs2_path=r"C:\CS2\cs2.exe",
        steam_login_mode="gui",
    )
    assert run({"login": "u1", "emit": lambda *a, **k: None, "config": cfg}) is True
    mock_move.assert_called_once()
    mock_wait_menu.assert_called_once()


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
    mock_wait_menu.return_value = MainMenuWaitResult(strict_ok=True, attempts=1)
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


def test_menu_confirmed_waits_strict_before_clicks(data_dir, monkeypatch) -> None:
    monkeypatch.setenv("DM_NAV_SIM", "1")
    from modules.dm_runner.navigate import DmNavigator

    nav = DmNavigator(
        config=AppConfig(
            map_load_delay_sec=10,
            game_search_timeout_sec=10,
            search_retries=1,
            cs2_main_menu_wait_timeout_sec=120,
        ),
        session_id="confirmed1",
        login="u1",
        menu_confirmed=True,
    )

    with patch.object(nav, "wait_main_menu") as mock_wait:
        with patch.object(nav, "click_sequence_deathmatch"):
            nav._pre_click_main_menu_wait()
            mock_wait.assert_called_once()
            assert mock_wait.call_args.kwargs.get("timeout") == 120.0
            assert mock_wait.call_args.kwargs.get("min_match") == 2

    nav2 = DmNavigator(
        config=AppConfig(
            map_load_delay_sec=10,
            game_search_timeout_sec=10,
            search_retries=1,
        ),
        session_id="warn1",
        login="u1",
        menu_probe_warn=True,
    )
    with patch.object(nav2, "wait_main_menu") as mock_wait:
        with patch.object(nav2, "click_sequence_deathmatch"):
            nav2._pre_click_main_menu_wait()
            mock_wait.assert_called_once()
            assert mock_wait.call_args.kwargs.get("min_match") == 1


def test_dm_retry_aborts_on_invalid_hwnd(data_dir, monkeypatch) -> None:
    monkeypatch.setenv("DM_NAV_SIM", "0")
    monkeypatch.setattr("sys.platform", "win32")
    from modules.dm_runner.errors import DmNavStopped
    from modules.dm_runner.navigate import DmNavigator

    from modules.ui_nav.coords import load_nav_coords

    coords = load_nav_coords("360x270")
    with patch(
        "modules.dm_runner.navigate.load_nav_coords_for_hwnd",
        return_value=coords,
    ):
        nav = DmNavigator(
            config=AppConfig(
                map_load_delay_sec=10,
                game_search_timeout_sec=10,
                search_retries=3,
            ),
            session_id="hwnd1",
            login="u1",
            hwnd=99999,
        )
    with patch.object(nav, "_prepare_cs2_window"):
        with patch("modules.ui_nav.window.is_valid_hwnd", return_value=False):
            with pytest.raises(DmNavStopped, match="window closed"):
                nav.navigate_to_dm_with_retries()


def test_dm_run_stops_gracefully(data_dir, monkeypatch) -> None:
    monkeypatch.setenv("DM_NAV_SIM", "1")
    from modules.dm_runner import run
    from modules.dm_runner.errors import DmNavStopped

    ctx: dict = {
        "login": "u1",
        "session_id": "stop1",
        "stop_requested": True,
    }
    with patch(
        "modules.dm_runner.navigate.DmNavigator.navigate_to_dm_with_retries",
        side_effect=DmNavStopped("stopped"),
    ):
        assert run(ctx) is False


def test_dm_retry_skips_menu_wait_after_clicks(data_dir, monkeypatch) -> None:
    monkeypatch.setenv("DM_NAV_SIM", "1")
    from modules.ui_nav.errors import UiNavTimeoutError
    from modules.dm_runner.navigate import DmNavigator

    nav = DmNavigator(
        config=AppConfig(
            map_load_delay_sec=10,
            game_search_timeout_sec=10,
            search_retries=2,
        ),
        session_id="retry1",
        login="u1",
    )
    nav._menu_nav_done = True

    with patch.object(nav, "_wait_search_and_in_dm", side_effect=UiNavTimeoutError("in_dm")) as mock_in_dm:
        with patch.object(nav, "_run_menu_and_clicks") as mock_menu:
            with patch.object(nav, "_prepare_cs2_window"):
                with pytest.raises(UiNavTimeoutError):
                    nav.navigate_to_dm_with_retries()
    assert mock_menu.call_count == 0
    assert mock_in_dm.call_count == 2


def test_searching_dm_not_emitted_when_search_unconfirmed(data_dir, monkeypatch) -> None:
    monkeypatch.setenv("DM_NAV_SIM", "1")
    from modules.dm_runner.navigate import DmNavigator

    emitted: list[EventType] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        emitted.append(event)

    nav = DmNavigator(
        config=AppConfig(
            map_load_delay_sec=10,
            game_search_timeout_sec=10,
            search_retries=1,
        ),
        session_id="search1",
        login="u1",
        emit=emit,
    )

    with patch(
        "modules.dm_runner.navigate.wait_for_state",
        side_effect=UiNavTimeoutError("timeout waiting for searching"),
    ):
        with patch(
            "modules.dm_runner.navigate.detect_state",
            return_value=False,
        ):
            with pytest.raises(UiNavTimeoutError, match="start_search not confirmed"):
                nav._confirm_search_started()

    assert EventType.SEARCHING_DM not in emitted


def test_searching_dm_emitted_after_searching_probe(data_dir, monkeypatch) -> None:
    monkeypatch.setenv("DM_NAV_SIM", "1")
    from modules.dm_runner.navigate import DmNavigator

    emitted: list[EventType] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        emitted.append(event)

    nav = DmNavigator(
        config=AppConfig(
            map_load_delay_sec=10,
            game_search_timeout_sec=10,
            search_retries=1,
        ),
        session_id="search2",
        login="u1",
        emit=emit,
    )

    with patch("modules.dm_runner.navigate.wait_for_state") as mock_wait:
        nav._confirm_search_started()
        mock_wait.assert_called_once()
        assert mock_wait.call_args.args[1] == ScreenState.SEARCHING

    assert EventType.SEARCHING_DM in emitted


def test_searching_dm_fast_path_when_in_dm_before_searching_probe(
    data_dir, monkeypatch
) -> None:
    monkeypatch.setenv("DM_NAV_SIM", "1")
    from modules.dm_runner.navigate import DmNavigator

    emitted: list[EventType] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        emitted.append(event)

    nav = DmNavigator(
        config=AppConfig(
            map_load_delay_sec=10,
            game_search_timeout_sec=10,
            search_retries=1,
        ),
        session_id="search3",
        login="u1",
        emit=emit,
    )

    def detect_side_effect(img, state, coords, *, min_match=None):
        return state == ScreenState.IN_DM

    with patch(
        "modules.dm_runner.navigate.wait_for_state",
        side_effect=UiNavTimeoutError("timeout waiting for searching"),
    ):
        with patch(
            "modules.dm_runner.navigate.detect_state",
            side_effect=detect_side_effect,
        ):
            nav._confirm_search_started()

    assert EventType.SEARCHING_DM in emitted


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
