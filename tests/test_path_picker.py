"""B-PATHS: path picker validation and controller integration."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from config.loader import ensure_config, load_config, save_config
from config.schema import AppConfig
from panel.controller import PanelController
from panel.path_picker import (
    CS2_EXE_NAMES,
    STEAM_EXE_NAMES,
    default_cs2_initialdir,
    default_steam_initialdir,
    pick_executable,
    truncate_path,
    validate_executable,
)


def test_truncate_path_empty() -> None:
    assert truncate_path("") == "(not set)"
    assert truncate_path("   ") == "(not set)"


def test_truncate_path_short() -> None:
    p = r"C:\Steam\steam.exe"
    assert truncate_path(p) == p


def test_truncate_path_long() -> None:
    p = r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\bin\win64\cs2.exe"
    out = truncate_path(p, max_len=48)
    assert len(out) == 48
    assert "..." in out


def test_validate_executable_steam() -> None:
    assert validate_executable("missing.exe", STEAM_EXE_NAMES) is not None


def test_validate_executable_wrong_name(tmp_path: Path) -> None:
    bad = tmp_path / "notsteam.exe"
    bad.write_bytes(b"MZ")
    err = validate_executable(str(bad), STEAM_EXE_NAMES)
    assert err is not None
    assert "steam.exe" in err


def test_validate_executable_ok(tmp_path: Path) -> None:
    exe = tmp_path / "steam.exe"
    exe.write_bytes(b"MZ")
    assert validate_executable(str(exe), STEAM_EXE_NAMES) is None


def test_validate_cs2_alias(tmp_path: Path) -> None:
    exe = tmp_path / "csgo.exe"
    exe.write_bytes(b"MZ")
    assert validate_executable(str(exe), CS2_EXE_NAMES) is None


def test_default_steam_initialdir_from_config(tmp_path: Path) -> None:
    steam = tmp_path / "steam.exe"
    steam.write_bytes(b"MZ")
    assert default_steam_initialdir(str(steam)) == str(tmp_path)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    ensure_config()
    return tmp_path


@pytest.fixture
def ctrl(data_dir):
    c = PanelController(None, test_mode=True)
    logs: list[str] = []
    c.append_log = lambda msg: logs.append(msg)  # type: ignore[method-assign]
    c._test_logs = logs  # type: ignore[attr-defined]
    return c


@pytest.mark.skipif(sys.platform != "win32", reason="filedialog tests Windows-only")
def test_pick_steam_path_updates_config(
    data_dir, ctrl: PanelController, tmp_path: Path, monkeypatch
) -> None:
    exe = tmp_path / "steam.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(
        "panel.controller.pick_executable",
        lambda **kw: str(exe.resolve()),
    )
    refreshed: list[int] = []

    def _refresh() -> None:
        refreshed.append(1)

    ctrl.on_config_paths_changed = _refresh
    ctrl.pick_steam_path()
    cfg = load_config()
    assert cfg.steam_path.replace("/", "\\") == str(exe.resolve()).replace("/", "\\")
    assert any("steam_path set:" in line for line in ctrl._test_logs)  # type: ignore[attr-defined]
    assert refreshed == [1]


@pytest.mark.skipif(sys.platform != "win32", reason="filedialog tests Windows-only")
def test_pick_cancel_does_not_change_config(
    data_dir, ctrl: PanelController, monkeypatch
) -> None:
    save_config(AppConfig(steam_path=r"C:\keep\steam.exe"))
    monkeypatch.setattr("panel.controller.pick_executable", lambda **kw: None)
    ctrl.pick_steam_path()
    assert load_config().steam_path == r"C:\keep\steam.exe"


@pytest.mark.skipif(sys.platform != "win32", reason="filedialog tests Windows-only")
def test_pick_invalid_basename_not_saved(
    data_dir, ctrl: PanelController, tmp_path: Path, monkeypatch
) -> None:
    save_config(AppConfig(steam_path=""))
    bad = tmp_path / "wrong.exe"
    bad.write_bytes(b"MZ")

    def _fake_pick(**kw):
        from panel.path_picker import validate_executable

        err = validate_executable(str(bad), STEAM_EXE_NAMES)
        assert err is not None
        return None

    monkeypatch.setattr("panel.controller.pick_executable", _fake_pick)
    ctrl.pick_steam_path()
    assert load_config().steam_path == ""


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows branch")
def test_pick_non_windows_logs_warn(ctrl: PanelController) -> None:
    ctrl.pick_steam_path()
    assert any("Windows-only" in line for line in ctrl._test_logs)  # type: ignore[attr-defined]


@pytest.mark.skipif(sys.platform != "win32", reason="filedialog Windows-only")
def test_pick_executable_module(tmp_path: Path, monkeypatch) -> None:
    exe = tmp_path / "cs2.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(
        "tkinter.filedialog.askopenfilename",
        lambda **kw: str(exe),
    )
    result = pick_executable(
        parent=None,
        title="CS2",
        initialdir=str(tmp_path),
        expected_basenames=CS2_EXE_NAMES,
    )
    assert result == str(exe.resolve())
