"""B-STEAM-GUI: Steam client GUI auto-login."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.schema import AppConfig
from modules.launcher.errors import LauncherError, LauncherPlatformError
from modules.launcher.steam_coords import (
    load_steam_login_coords,
    resolve_steam_coords_profile,
)
from modules.vault.mafile import parse_mafile
from modules.launcher.steam_gui_login import (
    SteamGuiLoginResult,
    login_steam_gui,
)
from modules.launcher.totp import generate_steam_guard_code
from modules.ui_nav.errors import UiNavError
from modules.ui_nav.steam_window import (
    SteamWindowKind,
    SteamWindowMatch,
    classify_steam_title,
    title_indicates_logged_in_as,
)
from modules.vault.store import add_account

FIXTURE_MA = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "fsm_import"
    / "maFiles"
    / "acc_one.maFile"
)


def test_classify_steam_titles() -> None:
    assert classify_steam_title("Sign in to Steam") == SteamWindowKind.LOGIN
    assert classify_steam_title("Steam") == SteamWindowKind.MAIN
    assert title_indicates_logged_in_as("Steam - acc_one", "acc_one") is True


def test_resolve_profile_705() -> None:
    assert resolve_steam_coords_profile(705, 440) == "705x440"
    assert resolve_steam_coords_profile(700, 435) == "705x440"
    assert resolve_steam_coords_profile(960, 540) == "1920x1080"


def test_load_steam_coords_705_profile() -> None:
    coords = load_steam_login_coords(705, 440)
    assert coords.profile == "705x440"
    assert coords.scale_x == 1.0
    assert coords.scale_y == 1.0
    assert coords.click("password_field").y == 210
    assert coords.click("submit").y == 320
    assert coords.click("enter_code_instead").x == 352
    assert coords.click("enter_code_instead").y == 320
    assert coords.click("guard_field").x == 352
    assert coords.click("account_field").x == 200


def test_detect_push_guard() -> None:
    from modules.launcher import steam_gui_login as sg

    assert sg._detect_push_guard_from_text(
        "Use the Steam Mobile App to confirm your sign in"
    )
    assert sg._detect_push_guard_from_text(
        "Подтвердите вход в мобильном приложении Steam"
    )
    assert not sg._detect_push_guard_from_text(
        "Enter the code from your Steam Guard app"
    )


def test_detect_totp_entry_screen() -> None:
    from modules.launcher import steam_gui_login as sg

    assert sg._detect_totp_entry_from_text(
        "Enter the code from your Authenticator app"
    )
    assert not sg._detect_totp_entry_from_text(
        "Use the Steam Mobile App to confirm your sign in"
    )


@patch("modules.launcher.totp.node_modules_ready", return_value=True)
@patch("modules.launcher.totp.node_executable", return_value="node")
@patch("modules.launcher.totp._run_node_totp", return_value=(0, "MRP77", ""))
def test_totp_once_js_returns_six_digits(
    _mock_run: MagicMock,
    _node: MagicMock,
    _nm: MagicMock,
    monkeypatch,
) -> None:
    monkeypatch.delenv("STEAM_GUI_LOGIN_SIM", raising=False)
    code = generate_steam_guard_code("dGVzdF9zaGFyZWQ=")
    assert code == "MRP77"
    _mock_run.assert_called_once()


@patch("modules.launcher.steam_gui_login.generate_steam_guard_code", return_value="654321")
@patch("modules.launcher.steam_gui_login._switch_to_totp_entry")
@patch("modules.launcher.steam_gui_login._detect_totp_entry_screen", return_value=False)
@patch("modules.launcher.steam_gui_login._detect_push_guard", return_value=True)
@patch("modules.launcher.steam_gui_login._detect_email_guard", return_value=False)
@patch("modules.launcher.steam_gui_login._client_coords")
def test_enter_guard_clicks_enter_code_instead(
    mock_cc: MagicMock,
    _email: MagicMock,
    mock_push: MagicMock,
    _totp_screen: MagicMock,
    mock_switch: MagicMock,
    mock_totp: MagicMock,
    monkeypatch,
) -> None:
    from modules.launcher.steam_gui_login import _enter_guard_code

    monkeypatch.setattr("sys.platform", "win32")
    coords = load_steam_login_coords(705, 440)
    mock_cc.return_value = coords
    login_hwnd = 99
    main_match = SteamWindowMatch(login_hwnd, "Steam", SteamWindowKind.MAIN)

    with (
        patch("modules.launcher.steam_gui_login._type_field") as mock_type,
        patch("modules.launcher.steam_gui_login._guard_phase_complete", return_value=False),
        patch("modules.launcher.steam_gui_login.is_valid_hwnd", return_value=True),
        patch("modules.launcher.steam_gui_login.actions.focus_window"),
        patch("modules.launcher.steam_gui_login.actions.press_return"),
        patch(
            "modules.launcher.steam_gui_login.find_steam_hwnd",
            side_effect=lambda **kw: (
                main_match
                if kw.get("prefer") == SteamWindowKind.MAIN
                else SteamWindowMatch(
                    login_hwnd, "Sign in", SteamWindowKind.LOGIN
                )
            ),
        ),
    ):
        _enter_guard_code(login_hwnd, coords, "secret", login="u1")

    mock_switch.assert_called()
    mock_totp.assert_called_once()
    mock_type.assert_called_once()
    assert mock_type.call_args[0][3] == "654321"


def test_load_steam_coords_scales_1920_fallback() -> None:
    coords = load_steam_login_coords(960, 540)
    assert coords.profile == "1920x1080"
    p = coords.click("account_field")
    assert p.x > 0 and p.y > 0


def test_totp_sim(monkeypatch) -> None:
    monkeypatch.setenv("STEAM_GUI_LOGIN_SIM", "1")
    assert generate_steam_guard_code("abc") == "23456"


def test_totp_generate_from_fixture_mafile(monkeypatch) -> None:
    import shutil

    from modules.looter.runner import node_modules_ready

    monkeypatch.delenv("STEAM_GUI_LOGIN_SIM", raising=False)
    if shutil.which("node") is None or not node_modules_ready():
        pytest.skip("node + vendor/looter/node_modules required")
    _, shared, _ = parse_mafile(FIXTURE_MA)
    code = generate_steam_guard_code(shared)
    assert len(code) == 5
    assert code.isalnum()


def test_login_gui_sim(monkeypatch) -> None:
    monkeypatch.setenv("STEAM_GUI_LOGIN_SIM", "1")
    cfg = AppConfig(steam_auto_login=True, steam_login_mode="gui")
    result = login_steam_gui("acc_one", cfg)
    assert result.ok is True
    assert result.simulated is True


@pytest.mark.skipif(sys.platform != "win32", reason="GUI login Windows-only")
def test_login_gui_non_windows(monkeypatch) -> None:
    monkeypatch.delenv("STEAM_GUI_LOGIN_SIM", raising=False)
    monkeypatch.setattr("sys.platform", "darwin")
    cfg = AppConfig(steam_auto_login=True)
    with pytest.raises(LauncherPlatformError):
        login_steam_gui("x", cfg)


def test_logged_in_main_visible_requires_no_login_window() -> None:
    from modules.ui_nav import steam_window as sw

    main = SteamWindowMatch(1, "Steam", SteamWindowKind.MAIN)
    with (
        patch.object(sw, "find_main_steam_for_login", return_value=main),
        patch.object(sw, "login_window_open", return_value=False),
        patch("modules.ui_nav.window.is_valid_hwnd", return_value=True),
    ):
        assert sw.logged_in_main_visible("acc_one") is main
    with (
        patch.object(sw, "find_main_steam_for_login", return_value=main),
        patch.object(sw, "login_window_open", return_value=True),
        patch("modules.ui_nav.window.is_valid_hwnd", return_value=True),
    ):
        assert sw.logged_in_main_visible("acc_one") is None


@patch("modules.launcher.steam_gui_login._wait_main_for_login")
@patch("modules.launcher.steam_gui_login._enter_guard_code")
@patch("modules.launcher.steam_gui_login._enter_credentials")
@patch("modules.launcher.steam_gui_login.wait_for_login_or_main")
@patch("modules.launcher.steam_gui_login.find_main_steam_for_login", return_value=None)
@patch("modules.launcher.steam_gui_login.load_account")
def test_login_gui_flow_mock(
    mock_load: MagicMock,
    _main: MagicMock,
    mock_wait: MagicMock,
    mock_creds: MagicMock,
    mock_guard: MagicMock,
    mock_wait_main: MagicMock,
    monkeypatch,
) -> None:
    monkeypatch.delenv("STEAM_GUI_LOGIN_SIM", raising=False)
    monkeypatch.setattr("sys.platform", "win32")
    mock_load.return_value = {
        "login": "u1",
        "password": "p",
        "shared_secret": "s",
        "identity_secret": "i",
    }
    login_win = SteamWindowMatch(
        hwnd=12345, title="Sign in to Steam", kind=SteamWindowKind.LOGIN
    )
    mock_wait.return_value = (login_win, False)
    mock_wait_main.return_value = SteamWindowMatch(
        hwnd=12345, title="Steam - u1", kind=SteamWindowKind.MAIN
    )

    with patch("modules.launcher.steam_gui_login._client_coords") as mock_cc:
        mock_cc.return_value = load_steam_login_coords(705, 440)
        with (
            patch(
                "modules.launcher.steam_gui_login.find_steam_hwnd",
                return_value=login_win,
            ),
            patch(
                "modules.launcher.steam_gui_login.is_valid_hwnd",
                return_value=True,
            ),
            patch(
                "modules.launcher.steam_gui_login._guard_phase_complete",
                return_value=False,
            ),
            patch(
                "modules.launcher.steam_gui_login._resolve_login_hwnd",
                side_effect=lambda fb, **kw: fb,
            ),
            patch(
                "modules.launcher.steam_gui_login._detect_email_guard",
                return_value=False,
            ),
            patch(
                "modules.launcher.steam_gui_login._detect_push_guard",
                return_value=False,
            ),
            patch(
                "modules.launcher.steam_gui_login._detect_totp_entry_screen",
                return_value=True,
            ),
        ):
            cfg = AppConfig(steam_auto_login=True, steam_login_timeout_sec=60)
            result = login_steam_gui("u1", cfg)

    assert result.ok is True
    mock_creds.assert_called()
    mock_guard.assert_called()


@patch("modules.launcher.steam_gui_login.load_account")
@patch("modules.launcher.steam_gui_login.find_main_steam_for_login")
def test_already_logged_in(
    mock_main: MagicMock, mock_load: MagicMock, monkeypatch
) -> None:
    monkeypatch.delenv("STEAM_GUI_LOGIN_SIM", raising=False)
    monkeypatch.setattr("sys.platform", "win32")
    mock_load.return_value = {
        "login": "acc_one",
        "password": "p",
        "shared_secret": "s",
        "identity_secret": "i",
    }
    mock_main.return_value = SteamWindowMatch(
        hwnd=1, title="Steam - acc_one", kind=SteamWindowKind.MAIN
    )
    cfg = AppConfig(steam_auto_login=True)
    result = login_steam_gui("acc_one", cfg)
    assert result.ok is True
    assert result.already_logged_in is True


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    from config.loader import ensure_config

    ensure_config()
    return tmp_path


def test_login_requires_vault(data_dir, monkeypatch) -> None:
    monkeypatch.delenv("STEAM_GUI_LOGIN_SIM", raising=False)
    monkeypatch.setattr("sys.platform", "win32")
    cfg = AppConfig(steam_auto_login=True)
    with pytest.raises(LauncherError, match="not in vault"):
        login_steam_gui("missing", cfg)


def test_login_requires_shared_secret(data_dir, monkeypatch) -> None:
    monkeypatch.delenv("STEAM_GUI_LOGIN_SIM", raising=False)
    monkeypatch.setattr("sys.platform", "win32")
    cfg = AppConfig(steam_auto_login=True)

    def _fake(login: str) -> dict:
        return {
            "login": login,
            "password": "p",
            "shared_secret": "",
            "identity_secret": "i",
        }

    with patch("modules.launcher.steam_gui_login.load_account", _fake):
        with pytest.raises(LauncherError, match="shared_secret"):
            login_steam_gui("acc_one", cfg)


def test_recover_from_ui_error_when_main_visible() -> None:
    from modules.launcher import steam_gui_login as sg

    main = SteamWindowMatch(1, "Steam", SteamWindowKind.MAIN)
    with patch.object(sg, "logged_in_main_visible", return_value=main):
        result = sg._recover_from_ui_error(
            "u1",
            "705x440",
            UiNavError("window closed (hwnd=999)"),
            note="main after resolve login",
        )
    assert result is not None
    assert result.ok is True
    assert "main after resolve login" in result.detail


def test_login_succeeds_when_stale_hwnd_after_guard(monkeypatch) -> None:
    from modules.launcher import steam_gui_login as sg

    monkeypatch.delenv("STEAM_GUI_LOGIN_SIM", raising=False)
    monkeypatch.setattr("sys.platform", "win32")
    login_win = SteamWindowMatch(
        12345, "Sign in to Steam", SteamWindowKind.LOGIN
    )
    main = SteamWindowMatch(1, "Steam", SteamWindowKind.MAIN)
    coords = load_steam_login_coords(705, 440)

    with (
        patch.object(
            sg,
            "load_account",
            return_value={
                "login": "u1",
                "password": "p",
                "shared_secret": "s",
                "identity_secret": "i",
            },
        ),
        patch.object(sg, "find_main_steam_for_login", return_value=None),
        patch.object(sg, "wait_for_login_or_main", return_value=(login_win, False)),
        patch.object(sg, "_resolve_login_hwnd", return_value=12345),
        patch.object(sg, "_client_coords", return_value=coords),
        patch.object(sg, "_enter_credentials"),
        patch.object(sg, "_guard_phase_complete", return_value=False),
        patch.object(
            sg,
            "find_steam_hwnd",
            return_value=login_win,
        ),
        patch.object(sg, "_detect_email_guard", return_value=False),
        patch.object(sg, "_detect_push_guard", return_value=True),
        patch.object(sg, "_detect_totp_entry_screen", return_value=True),
        patch.object(
            sg,
            "_enter_guard_code",
            side_effect=UiNavError("window closed (hwnd=12345)"),
        ),
        patch.object(
            sg,
            "logged_in_main_visible",
            side_effect=[None, None, None, main],
        ),
    ):
        result = sg.login_steam_gui("u1", AppConfig(steam_auto_login=True))

    assert result.ok is True
    assert "main after guard entry" in result.detail


def test_invalid_hwnd_error_detection() -> None:
    from modules.ui_nav.window import is_invalid_hwnd_error

    class FakeWin32Error(Exception):
        winerror = 1400

    assert is_invalid_hwnd_error(FakeWin32Error("(1400, 'GetClientRect')"))
    assert is_invalid_hwnd_error(Exception("GetClientRect failed"))
    assert not is_invalid_hwnd_error(Exception("timeout"))
