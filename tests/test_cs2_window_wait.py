"""CS2 window wait after Popen."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from config.schema import AppConfig
from core.events import EventType
from modules.ui_nav.errors import UiNavError
from modules.ui_nav.window import wait_for_cs2_hwnd


def test_wait_for_cs2_hwnd_retries_until_found(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    progress: list[str] = []
    with patch(
        "modules.ui_nav.window.find_cs2_hwnd",
        side_effect=[UiNavError("missing"), UiNavError("missing"), 4242],
    ):
        hwnd = wait_for_cs2_hwnd(
            timeout_sec=5.0,
            poll_sec=0.01,
            on_progress=progress.append,
        )
    assert hwnd == 4242
    assert progress[0] == "waiting for CS2 window…"


def test_wait_for_cs2_hwnd_timeout(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    with patch(
        "modules.ui_nav.window.find_cs2_hwnd",
        side_effect=UiNavError("missing"),
    ):
        with pytest.raises(UiNavError, match="within 1s"):
            wait_for_cs2_hwnd(timeout_sec=1.0, poll_sec=0.01)


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
def test_launcher_emits_cs2_ok_after_window_wait(
    _kill_all: MagicMock,
    _kill_cs2: MagicMock,
    mock_gui: MagicMock,
    mock_steam: MagicMock,
    mock_cs2: MagicMock,
    mock_wait: MagicMock,
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
    from modules.ui_nav.coords import load_nav_coords
    from modules.ui_nav.window import MainMenuWaitResult

    mock_gui.return_value = SteamGuiLoginResult(ok=True, login="u1", detail="ok")
    mock_dismiss.return_value = SteamPromoDismissResult(
        dismissed=0, found=0, detail="main only — no promo"
    )
    mock_load_coords.return_value = load_nav_coords("360x270")
    mock_wait_menu.return_value = MainMenuWaitResult(ok=True, attempts=1)
    mock_cs2.return_value = MagicMock(poll=MagicMock(return_value=None))
    monkeypatch.setattr("sys.platform", "win32")

    progress: list[str] = []
    emitted: list[tuple[EventType, str]] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        emitted.append((event, detail))

    cfg = AppConfig(
        steam_path=r"C:\Steam\steam.exe",
        cs2_path=r"C:\Steam\steamapps\common\Counter-Strike Global Offensive\game\bin\win64\cs2.exe",
        steam_login_mode="gui",
    )
    ctx: dict = {
        "login": "u1",
        "emit": emit,
        "config": cfg,
        "on_cs2_progress": progress.append,
    }
    assert run(ctx) is True
    mock_wait.assert_called_once()
    on_progress = mock_wait.call_args.kwargs["on_progress"]
    assert on_progress is not None
    on_progress("waiting for CS2 window…")
    assert progress == ["waiting for CS2 window…"]
    assert ctx.get("cs2_hwnd") == 9999
    assert ctx.get("cs2_menu_confirmed") is True
    assert EventType.CS2_OK in [e for e, _ in emitted]
    cs2_detail = next(d for e, d in emitted if e == EventType.CS2_OK)
    assert "menu ready" in cs2_detail
    assert "hwnd=9999" in cs2_detail


@patch("modules.dm_runner.DmNavigator")
def test_dm_runner_catches_navigator_init_error(mock_nav_cls: MagicMock) -> None:
    from modules.dm_runner import run

    mock_nav_cls.side_effect = UiNavError("CS2 window not found")
    emitted: list[tuple[EventType, str]] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        emitted.append((event, detail))

    ok = run({"login": "u1", "emit": emit, "hwnd": None})
    assert ok is False
    assert any(e == EventType.SESSION_FAILED for e, _ in emitted)
    assert "dm_runner init" in emitted[-1][1]
