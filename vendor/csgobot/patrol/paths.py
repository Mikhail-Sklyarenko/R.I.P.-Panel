"""Resolve patrol YAML paths relative to farm-panel-prototype root."""

from __future__ import annotations

from pathlib import Path


def farm_panel_root() -> Path:
    # vendor/csgobot/patrol/paths.py -> repo root
    return Path(__file__).resolve().parents[3]


def resolve_patrol_path(script_name: str, explicit_path: str = "") -> Path:
    if explicit_path:
        return Path(explicit_path)
    name = script_name.strip()
    if name.endswith(".yaml"):
        name = name[:-5]
    return farm_panel_root() / "resources" / "patrol" / f"{name}.yaml"
