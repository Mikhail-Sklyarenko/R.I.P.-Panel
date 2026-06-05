"""Загрузка и масштабирование coords_360x270.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from config.paths import get_app_root
from modules.ui_nav.errors import UiNavError


def _default_coords_path() -> Path:
    return get_app_root() / "resources" / "ui_nav" / "coords_360x270.yaml"


@dataclass(frozen=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True)
class ColorProbe:
    x: int
    y: int
    rgb: tuple[int, int, int]
    tolerance: int


@dataclass
class NavCoords:
    base_width: int
    base_height: int
    clicks: dict[str, Point]
    detectors: dict[str, list[ColorProbe]]
    scale_x: float = 1.0
    scale_y: float = 1.0

    def click(self, name: str) -> Point:
        p = self.clicks[name]
        return Point(int(p.x * self.scale_x), int(p.y * self.scale_y))

    def probes(self, state: str) -> list[ColorProbe]:
        out: list[ColorProbe] = []
        for probe in self.detectors.get(state, []):
            out.append(
                ColorProbe(
                    int(probe.x * self.scale_x),
                    int(probe.y * self.scale_y),
                    probe.rgb,
                    probe.tolerance,
                )
            )
        return out


def _parse_resolution(resolution: str) -> tuple[int, int]:
    raw = resolution.lower().replace(" ", "")
    if "x" not in raw:
        raise UiNavError(f"invalid cs_resolution: {resolution}")
    w, h = raw.split("x", 1)
    return int(w), int(h)


def load_nav_coords(
    resolution: str = "360x270",
    path: Path | None = None,
) -> NavCoords:
    src = path or _default_coords_path()
    data = yaml.safe_load(src.read_text(encoding="utf-8"))
    meta = data.get("meta", {})
    base_w = int(meta.get("base_width", 360))
    base_h = int(meta.get("base_height", 270))
    target_w, target_h = _parse_resolution(resolution)

    clicks: dict[str, Point] = {}
    for name, pt in data.get("clicks", {}).items():
        clicks[name] = Point(int(pt["x"]), int(pt["y"]))

    detectors: dict[str, list[ColorProbe]] = {}
    for state, probes in data.get("detectors", {}).items():
        detectors[state] = [
            ColorProbe(
                int(p["x"]),
                int(p["y"]),
                tuple(int(c) for c in p["rgb"]),
                int(p.get("tolerance", 40)),
            )
            for p in probes
        ]

    return NavCoords(
        base_width=base_w,
        base_height=base_h,
        clicks=clicks,
        detectors=detectors,
        scale_x=target_w / base_w,
        scale_y=target_h / base_h,
    )
