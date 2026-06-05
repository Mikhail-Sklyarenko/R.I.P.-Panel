"""config.yaml создаётся при первом ensure_config."""

from __future__ import annotations

import os

import yaml

from config.loader import ensure_config, load_config
from config.paths import get_config_path
from config.schema import AppConfig


def test_ensure_config_creates_yaml(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    cfg = ensure_config()
    assert isinstance(cfg, AppConfig)
    assert cfg.steam_path == ""
    assert cfg.cs2_path == ""

    path = get_config_path()
    assert path.exists()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["bot_mode"] == "auto"
    assert raw["start_farm_when_launched"] is True


def test_load_config_respects_test_mode_flag(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("test_mode: true\n", encoding="utf-8")
    cfg = load_config()
    assert cfg.test_mode is True
