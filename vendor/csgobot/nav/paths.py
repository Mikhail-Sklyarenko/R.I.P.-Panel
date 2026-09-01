"""Resolve navigation resource paths relative to farm-panel-prototype root."""

from __future__ import annotations

import os
from pathlib import Path


def farm_panel_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _data_dir() -> Path:
    override = os.environ.get("FARM_PANEL_DATA_DIR", "").strip()
    if override:
        return Path(override)
    return farm_panel_root() / "data"


def resolve_nav_root() -> Path:
    return farm_panel_root() / "resources" / "nav"


def resolve_calibration_path(explicit_path: str = "") -> Path:
    if explicit_path:
        return Path(explicit_path)
    return resolve_nav_root() / "calibration_1280x720.yaml"


def resolve_nav_pack_path(pack_id: str, explicit_path: str = "") -> Path:
    if explicit_path:
        return Path(explicit_path)
    pack_override = _data_dir() / "nav_packs" / f"{pack_id}.yaml"
    if pack_override.is_file():
        return pack_override
    return resolve_nav_root() / "packs" / f"{pack_id}.yaml"


def resolve_map_meta_path(map_id: str) -> Path:
    return resolve_nav_root() / "maps" / map_id / "meta.json"


def resolve_map_radar_path(map_id: str) -> Path:
    return resolve_nav_root() / "maps" / map_id / "radar.png"
