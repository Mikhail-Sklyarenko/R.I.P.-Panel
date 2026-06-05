"""Создание data/config.yaml при первом обращении."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from config.paths import ensure_fsm_import_dirs, get_config_path, get_data_dir
from config.schema import AppConfig


def _ensure_data_dir() -> Path:
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    ensure_fsm_import_dirs()
    return data_dir


def default_config_dict() -> dict[str, Any]:
    return AppConfig().model_dump(mode="json")


def ensure_config() -> AppConfig:
    """Создать config.yaml с дефолтами, если файла нет."""
    _ensure_data_dir()
    path = get_config_path()
    if not path.exists():
        save_config(AppConfig())
    return load_config()


def load_config() -> AppConfig:
    _ensure_data_dir()
    path = get_config_path()
    if not path.exists():
        return AppConfig()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return AppConfig()
    return AppConfig.model_validate(raw)


def save_config(config: AppConfig) -> None:
    _ensure_data_dir()
    path = get_config_path()
    data = config.model_dump(mode="json")
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
