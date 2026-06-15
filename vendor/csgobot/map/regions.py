"""Load map OCR regions and match-ready probes from YAML."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from team.probes import ColorProbe


class MapRegionLoadError(ValueError):
    pass


@dataclass(frozen=True)
class OcrRect:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class MapRegionSet:
    base_width: int
    base_height: int
    match_ready_probes: tuple[ColorProbe, ...]
    match_ready_min_votes: int
    match_ready_ocr: OcrRect
    scoreboard_ocr: OcrRect
    template_threshold: float


def _parse_color_probe(raw: Any, name: str, index: int) -> ColorProbe:
    if not isinstance(raw, dict):
        raise MapRegionLoadError(f"{name}[{index}] must be a mapping")
    try:
        x = int(raw["x"])
        y = int(raw["y"])
        rgb_raw = raw["rgb"]
        rgb = (int(rgb_raw[0]), int(rgb_raw[1]), int(rgb_raw[2]))
        tolerance = int(raw.get("tolerance", 50))
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise MapRegionLoadError(f"{name}[{index}] invalid probe fields") from exc
    return ColorProbe(x=x, y=y, rgb=rgb, tolerance=tolerance)


def _parse_rect(raw: Any, name: str) -> OcrRect:
    if not isinstance(raw, dict):
        raise MapRegionLoadError(f"{name} must be a mapping")
    try:
        return OcrRect(
            x=int(raw["x"]),
            y=int(raw["y"]),
            w=int(raw["w"]),
            h=int(raw["h"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise MapRegionLoadError(f"{name} invalid rect fields") from exc


def parse_map_region_data(data: dict[str, Any]) -> MapRegionSet:
    meta = data.get("meta") or {}
    base_width = int(meta.get("base_width", 1280))
    base_height = int(meta.get("base_height", 720))

    match_ready = data.get("match_ready") or {}
    probes_raw = match_ready.get("visible_probes") or []
    if not isinstance(probes_raw, list) or not probes_raw:
        raise MapRegionLoadError("match_ready.visible_probes must be a non-empty list")

    probes = tuple(
        _parse_color_probe(item, "match_ready.visible_probes", i)
        for i, item in enumerate(probes_raw)
    )
    min_votes = int(match_ready.get("min_probe_votes", 1))
    match_ready_ocr = _parse_rect(match_ready.get("ocr"), "match_ready.ocr")

    scoreboard = data.get("scoreboard") or {}
    scoreboard_ocr = _parse_rect(scoreboard.get("ocr"), "scoreboard.ocr")

    threshold = float(data.get("template_threshold", 0.55))

    return MapRegionSet(
        base_width=base_width,
        base_height=base_height,
        match_ready_probes=probes,
        match_ready_min_votes=min_votes,
        match_ready_ocr=match_ready_ocr,
        scoreboard_ocr=scoreboard_ocr,
        template_threshold=threshold,
    )


def load_map_regions(path: Path | str) -> MapRegionSet:
    path = Path(path)
    if not path.is_file():
        raise MapRegionLoadError(f"map regions file not found: {path}")

    try:
        import yaml
    except ImportError as exc:
        raise MapRegionLoadError(
            "PyYAML required for map regions (pip install pyyaml)"
        ) from exc

    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise MapRegionLoadError("map regions YAML root must be a mapping")

    return parse_map_region_data(data)
