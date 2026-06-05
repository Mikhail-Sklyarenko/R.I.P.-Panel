"""B-STEAM-AUTH: steam_login.js wrapper and launcher integration."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.loader import ensure_config, load_config
from config.schema import AppConfig
from core.events import EventType
from modules.launcher import run as launcher_run
from modules.launcher.errors import LauncherError, LauncherPlatformError
from modules.launcher.steam_auth import (
    SteamAuthResult,
    login_steam_account,
    stop_steam_auth,
)
from modules.vault.store import add_account

FIXTURE_MA = (
    Path(__file__).resolve().parent / "fixtures" / "fsm_import" / "maFiles" / "acc_one.maFile"
)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    ensure_config()
    return tmp_path


def _seed_account(data_dir: Path, login: str = "acc_one") -> None:
    add_account(login=login, password="secret_pass", mafile_path=FIXTURE_MA)


def test_login_sim_mode(data_dir, monkeypatch) -> None:
    monkeypatch.setenv("STEAM_LOGIN_SIM", "1")
    cfg = AppConfig(steam_auto_login=True)
    result = login_steam_account("acc_one", cfg)
    assert result.ok is True
    assert result.simulated is True


@pytest.mark.skipif(sys.platform != "win32", reason="steam auth Windows-only")
def test_login_requires_vault(data_dir, monkeypatch) -> None:
    monkeypatch.delenv("STEAM_LOGIN_SIM", raising=False)
    cfg = AppConfig(steam_auto_login=True)
    with pytest.raises(LauncherError, match="not in vault"):
        login_steam_account("missing_user", cfg)


@pytest.mark.skipif(sys.platform != "win32", reason="steam auth Windows-only")
def test_login_requires_shared_secret(data_dir, monkeypatch) -> None:
    monkeypatch.delenv("STEAM_LOGIN_SIM", raising=False)
    _seed_account(data_dir)
    cfg = AppConfig(steam_auto_login=True)

    def _fake_load(login: str) -> dict:
        return {
            "login": login,
            "password": "p",
            "shared_secret": "",
            "identity_secret": "x",
        }

    with patch("modules.launcher.steam_auth.load_account", _fake_load):
        with pytest.raises(LauncherError, match="shared_secret"):
            login_steam_account("acc_one", cfg)


@pytest.mark.skipif(sys.platform != "win32", reason="steam auth Windows-only")
@patch("modules.launcher.steam_auth.node_executable", return_value="node")
@patch("modules.launcher.steam_auth.is_ready", return_value=True)
@patch("modules.launcher.steam_auth.subprocess.Popen")
@patch("modules.launcher.steam_auth._wait_for_ready")
def test_login_success_mock_node(
    mock_wait: MagicMock,
    mock_popen: MagicMock,
    _is_ready: MagicMock,
    _node: MagicMock,
    data_dir,
    monkeypatch,
) -> None:
    monkeypatch.delenv("STEAM_LOGIN_SIM", raising=False)
    _seed_account(data_dir)
    proc = MagicMock()
    proc.stdout = MagicMock()
    proc.stderr = MagicMock()
    proc.poll.return_value = None
    mock_popen.return_value = proc
    mock_wait.return_value = SteamAuthResult(
        ok=True, login="acc_one", detail="steam login ok"
    )

    cfg = AppConfig(steam_auto_login=True, steam_login_timeout_sec=60)
    result = login_steam_account("acc_one", cfg)
    assert result.ok is True
    stop_steam_auth()


def test_wait_for_ready_parses_json_line() -> None:
    from modules.launcher import steam_auth as sa

    lines = [
        json.dumps({"event": "loggedOn"}) + "\n",
        json.dumps({"event": "ready", "status": "STEAM_AUTH_READY"}) + "\n",
    ]

    class FakeStdout:
        def __init__(self) -> None:
            self._lines = list(lines)

        def readline(self) -> str:
            if not self._lines:
                return ""
            return self._lines.pop(0)

    proc = MagicMock()
    proc.poll.return_value = None
    proc.stdout = FakeStdout()
    proc.stderr = MagicMock()
    result = sa._wait_for_ready(proc, timeout_sec=5, login="u1")
    assert result.ok is True


@patch("modules.launcher.cs2.launch_cs2")
@patch("modules.launcher.steam.launch_steam")
@patch("modules.launcher.steam_auth.login_steam_account")
@patch("modules.launcher.proxy_check.check_proxy", return_value=(True, "ok"))
@patch("modules.launcher.cleanup.kill_all")
def test_launcher_run_steam_auth_flow(
    _kill: MagicMock,
    _proxy: MagicMock,
    mock_auth: MagicMock,
    mock_steam: MagicMock,
    mock_cs2: MagicMock,
    monkeypatch,
) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    mock_auth.return_value = SteamAuthResult(ok=True, login="u1", detail="ok")
    mock_steam.return_value = MagicMock(poll=MagicMock(return_value=None))
    mock_cs2.return_value = MagicMock(poll=MagicMock(return_value=None))

    emitted: list[tuple[EventType, str]] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        emitted.append((event, detail))

    cfg = AppConfig(
        steam_path=r"C:\Steam\steam.exe",
        cs2_path=r"C:\CS2\cs2.exe",
        steam_auto_login=True,
        steam_login_mode="api",
    )
    assert launcher_run({"login": "u1", "emit": emit, "config": cfg}) is True
    events = [e for e, _ in emitted]
    assert EventType.STEAM_LOGIN_START in events
    assert EventType.STEAM_LOGIN_OK in events
    assert EventType.STEAM_OK in events
    assert EventType.CS2_OK in events
    mock_auth.assert_called_once()


@pytest.mark.skipif(sys.platform != "win32", reason="platform guard")
def test_login_non_windows_raises(data_dir, monkeypatch) -> None:
    monkeypatch.delenv("STEAM_LOGIN_SIM", raising=False)
    monkeypatch.setattr("sys.platform", "darwin")
    cfg = AppConfig(steam_auto_login=True)
    with pytest.raises(LauncherPlatformError):
        login_steam_account("acc_one", cfg)
