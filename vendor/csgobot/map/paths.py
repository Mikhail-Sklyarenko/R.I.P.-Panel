"""Resolve map-detect resource paths relative to farm-panel-prototype root."""

from __future__ import annotations

from pathlib import Path


def farm_panel_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_map_regions_path(explicit_path: str = "") -> Path:
    if explicit_path:
        return Path(explicit_path)
    return farm_panel_root() / "resources" / "csgobot" / "map_regions_1280x720.yaml"


def resolve_map_templates_dir(explicit_path: str = "") -> Path:
    if explicit_path:
        return Path(explicit_path)
    return farm_panel_root() / "resources" / "csgobot" / "map_templates"
