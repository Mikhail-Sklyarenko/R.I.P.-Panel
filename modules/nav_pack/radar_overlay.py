"""Radar overlay rendering for nav pack editor (PR-N9)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import yaml
from PIL import Image, ImageDraw

from config.paths import get_app_root
from modules.nav_pack.editor import NavPackEditorError, resolve_pack_path


@dataclass(frozen=True)
class RadarMarker:
    marker_id: str
    x: float
    y: float
    color: str
    radius: int = 6


@dataclass(frozen=True)
class RadarOverlayState:
    pack_id: str
    map_id: str
    radar_path: str
    image_size: tuple[int, int]
    markers: tuple[RadarMarker, ...]


def resolve_radar_path(map_id: str) -> Path:
    path = get_app_root() / "resources" / "nav" / "maps" / map_id / "radar.png"
    if not path.is_file():
        raise NavPackEditorError(f"radar missing for map {map_id}: {path}")
    return path


def resolve_map_meta_path(map_id: str) -> Path:
    return get_app_root() / "resources" / "nav" / "maps" / map_id / "meta.json"


def norm_to_pixel(x: float, y: float, width: int, height: int) -> tuple[int, int]:
    px = int(max(0.0, min(1.0, x)) * (width - 1))
    py = int(max(0.0, min(1.0, y)) * (height - 1))
    return px, py


def pixel_to_norm(px: int, py: int, width: int, height: int) -> tuple[float, float]:
    if width <= 1 or height <= 1:
        return 0.5, 0.5
    x = max(0.0, min(1.0, px / (width - 1)))
    y = max(0.0, min(1.0, py / (height - 1)))
    return round(x, 4), round(y, 4)


def _load_pack_data(pack_id: str) -> dict[str, Any]:
    path = resolve_pack_path(pack_id)
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise NavPackEditorError(f"invalid pack: {pack_id}")
    return data


def build_overlay_state(
    pack_id: str,
    *,
    goal_x: float | None = None,
    goal_y: float | None = None,
    goal2_x: float | None = None,
    goal2_y: float | None = None,
) -> RadarOverlayState:
    data = _load_pack_data(pack_id)
    meta = data.get("meta") or {}
    map_id = str(meta.get("map_id") or "")
    if not map_id:
        raise NavPackEditorError(f"pack {pack_id} has no map_id")

    radar_path = resolve_radar_path(map_id)
    with Image.open(radar_path) as img:
        width, height = img.size

    goal = data.get("goal") or {}
    goals = data.get("goals") or []
    goal2 = goals[1] if len(goals) > 1 else {}

    g1x = goal_x if goal_x is not None else float(goal.get("x", 0.5))
    g1y = goal_y if goal_y is not None else float(goal.get("y", 0.5))
    g1id = str(goal.get("id") or "goal")

    markers: list[RadarMarker] = [
        RadarMarker(g1id, g1x, g1y, "#22c55e", radius=7),
    ]
    if goal2 or goal2_x is not None:
        g2x = goal2_x if goal2_x is not None else float(goal2.get("x", 0.5))
        g2y = goal2_y if goal2_y is not None else float(goal2.get("y", 0.5))
        g2id = str(goal2.get("id") or "goal2")
        markers.append(RadarMarker(g2id, g2x, g2y, "#f97316", radius=7))

    for entry in data.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        markers.append(
            RadarMarker(
                str(entry.get("id") or "entry"),
                float(entry.get("x", 0.5)),
                float(entry.get("y", 0.5)),
                "#38bdf8",
                radius=5,
            )
        )

    meta_path = resolve_map_meta_path(map_id)
    if meta_path.is_file():
        try:
            landmarks = json.loads(meta_path.read_text(encoding="utf-8")).get("landmarks") or {}
            for name, pt in landmarks.items():
                if not isinstance(pt, dict):
                    continue
                markers.append(
                    RadarMarker(
                        str(name),
                        float(pt.get("x", 0.5)),
                        float(pt.get("y", 0.5)),
                        "#94a3b8",
                        radius=4,
                    )
                )
        except (OSError, json.JSONDecodeError):
            pass

    return RadarOverlayState(
        pack_id=pack_id,
        map_id=map_id,
        radar_path=str(radar_path),
        image_size=(width, height),
        markers=tuple(markers),
    )


def render_overlay_image(
    state: RadarOverlayState,
    *,
    display_size: int = 320,
) -> Image.Image:
    with Image.open(state.radar_path) as base:
        img = base.convert("RGBA").resize((display_size, display_size), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(img)
    src_w, src_h = state.image_size
    for marker in state.markers:
        px = int(marker.x * (display_size - 1))
        py = int(marker.y * (display_size - 1))
        r = marker.radius
        draw.ellipse((px - r, py - r, px + r, py + r), outline=marker.color, width=2)
        draw.ellipse((px - 2, py - 2, px + 2, py + 2), fill=marker.color)
        draw.text((px + r + 2, py - r), marker.marker_id, fill=marker.color)
    return img


def render_overlay_png_bytes(state: RadarOverlayState, *, display_size: int = 320) -> bytes:
    buf = BytesIO()
    render_overlay_image(state, display_size=display_size).save(buf, format="PNG")
    return buf.getvalue()
