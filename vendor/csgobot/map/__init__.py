"""HUD map auto-detect for patrol script selection."""

from map.hud_map_detect import (
    MapDetectState,
    detect_map_hud,
    match_ready_visible,
    update_map_hysteresis,
)
from map.parse import MapScriptId, normalize_map_text, parse_map_script
from map.paths import resolve_map_regions_path, resolve_map_templates_dir
from map.regions import MapRegionSet, load_map_regions
from map.template_match import MapTemplate, load_map_templates, max_ncc

__all__ = [
    "MapDetectState",
    "MapRegionSet",
    "MapScriptId",
    "MapTemplate",
    "detect_map_hud",
    "load_map_regions",
    "load_map_templates",
    "match_ready_visible",
    "max_ncc",
    "normalize_map_text",
    "parse_map_script",
    "resolve_map_regions_path",
    "resolve_map_templates_dir",
    "update_map_hysteresis",
]
