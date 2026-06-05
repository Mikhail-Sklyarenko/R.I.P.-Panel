"""Калибровка кликов Steam MAIN UI (promo dismiss)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from config.paths import get_app_root
from modules.ui_nav.coords import Point
from modules.ui_nav.errors import UiNavError

_log = logging.getLogger(__name__)


def _default_path() -> Path:
    return get_app_root() / "resources" / "ui_nav" / "steam_main_default.yaml"


@dataclass
class SteamMainCoords:
    base_width: int
    base_height: int
    clicks: dict[str, Point]
    client_width: int = 0
    client_height: int = 0
    scale_x: float = 1.0
    scale_y: float = 1.0

    def click(self, name: str) -> Point | None:
        if name not in self.clicks:
            return None
        p = self.clicks[name]
        return Point(int(p.x * self.scale_x), int(p.y * self.scale_y))


def load_steam_main_coords(
    client_width: int,
    client_height: int,
    path: Path | None = None,
) -> SteamMainCoords:
    src = path or _default_path()
    if not src.is_file():
        raise UiNavError(f"steam main coords file missing: {src}")
    data = yaml.safe_load(src.read_text(encoding="utf-8"))
    meta = data.get("meta", {})
    base_w = int(meta.get("base_width", 1024))
    base_h = int(meta.get("base_height", 768))
    clicks: dict[str, Point] = {}
    for name, pt in data.get("clicks", {}).items():
        clicks[name] = Point(int(pt["x"]), int(pt["y"]))
    coords = SteamMainCoords(
        base_width=base_w,
        base_height=base_h,
        clicks=clicks,
        client_width=client_width,
        client_height=client_height,
        scale_x=client_width / base_w if base_w else 1.0,
        scale_y=client_height / base_h if base_h else 1.0,
    )
    _log.info(
        "steam main coords client=%sx%s scale=%.2fx%.2f",
        client_width,
        client_height,
        coords.scale_x,
        coords.scale_y,
    )
    return coords
