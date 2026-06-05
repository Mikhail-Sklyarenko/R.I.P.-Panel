"""B12: utils move/kill/recovery (UTILS_SIM on non-Windows)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from config.loader import ensure_config, load_config, save_config
from modules.utils import (
    kill_all_cs_and_steam,
    kill_all_with_confirm,
    list_cs_windows,
    move_all_cs_windows,
    recover_hang,
)
from modules.utils.errors import UtilsError, UtilsPlatformError


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("UTILS_SIM", "1")
    monkeypatch.setenv("UTILS_SKIP_CONFIRM", "1")
    ensure_config()
    return tmp_path


def test_list_and_move_cs_windows_sim() -> None:
    wins = list_cs_windows()
    assert len(wins) >= 2
    result = move_all_cs_windows()
    assert result.count == len(wins)
    assert result.width == 360
    assert result.height == 270
    assert result.simulated


def test_kill_all_sim() -> None:
    result = kill_all_cs_and_steam()
    assert "cs2.exe" in result.cs2
    assert "steam.exe" in result.steam
    assert result.simulated


def test_kill_with_confirm_cancelled(data_dir, monkeypatch) -> None:
    monkeypatch.delenv("UTILS_SKIP_CONFIRM", raising=False)
    cfg = load_config()
    cfg.utils_confirm_before_kill = True
    save_config(cfg)
    with patch("modules.utils.kill.confirm_kill", return_value=False):
        result = kill_all_with_confirm(config=cfg)
    assert result.cancelled
    assert result.summary() == "cancelled"


def test_kill_with_confirm_proceeds(data_dir) -> None:
    with patch("modules.utils.kill.confirm_kill", return_value=True):
        result = kill_all_with_confirm()
    assert not result.cancelled
    assert result.simulated


def test_recover_hang_calls_stop_callback(data_dir) -> None:
    stops: list[str] = []

    def on_stop() -> None:
        stops.append("stopped")

    with patch("modules.utils.kill.confirm_kill", return_value=True):
        result = recover_hang(on_before_kill=on_stop)
    assert stops == ["stopped"]
    assert result.ok


def test_move_no_windows(monkeypatch) -> None:
    monkeypatch.setenv("UTILS_SIM", "1")

    def empty() -> list:
        return []

    with patch("modules.utils.windows.list_cs_windows", empty):
        with pytest.raises(UtilsError, match="no CS2"):
            move_all_cs_windows()


def test_kill_platform_without_sim(monkeypatch) -> None:
    import sys

    monkeypatch.delenv("UTILS_SIM", raising=False)
    if sys.platform == "win32":
        pytest.skip("Windows uses real taskkill")
    with pytest.raises(UtilsPlatformError):
        kill_all_cs_and_steam()


def test_should_confirm_respects_config(data_dir) -> None:
    from modules.utils.confirm import should_confirm

    cfg = load_config()
    cfg.utils_confirm_before_kill = False
    save_config(cfg)
    assert should_confirm(cfg) is False
