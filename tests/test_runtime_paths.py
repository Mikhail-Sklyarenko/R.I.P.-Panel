"""B-PACKAGE: get_app_root / get_data_dir frozen vs dev."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from config.loader import ensure_config
from config.paths import get_app_root, get_data_dir, is_frozen


@pytest.fixture
def source_root() -> Path:
    return Path(__file__).resolve().parent.parent


def test_dev_app_root_is_source_tree(source_root, monkeypatch) -> None:
    monkeypatch.delenv("FARM_PANEL_APP_ROOT", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    get_app_root.cache_clear()
    assert get_app_root() == source_root
    assert is_frozen() is False


def test_frozen_app_root_next_to_executable(source_root, monkeypatch) -> None:
    fake_exe_dir = source_root / "dist" / "FarmPanel"
    fake_exe_dir.mkdir(parents=True, exist_ok=True)
    fake_exe = fake_exe_dir / "FarmPanel.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe), raising=False)
    monkeypatch.delenv("FARM_PANEL_APP_ROOT", raising=False)
    get_app_root.cache_clear()
    assert get_app_root() == fake_exe_dir.resolve()


def test_data_dir_beside_app_root(source_root, monkeypatch) -> None:
    monkeypatch.setenv("FARM_PANEL_APP_ROOT", str(source_root))
    monkeypatch.delenv("FARM_PANEL_DATA_DIR", raising=False)
    get_app_root.cache_clear()
    assert get_data_dir() == source_root / "data"


def test_ensure_config_under_data_dir(tmp_path, monkeypatch) -> None:
    app = tmp_path / "FarmPanel"
    app.mkdir()
    monkeypatch.setenv("FARM_PANEL_APP_ROOT", str(app))
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(app / "data"))
    get_app_root.cache_clear()
    cfg = ensure_config()
    assert (app / "data" / "config.yaml").is_file()
    assert cfg.test_mode is False or cfg.test_mode is True
