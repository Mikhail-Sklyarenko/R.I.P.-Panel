"""Загрузка и масштабирование CS2 ui_nav coords по cs_resolution профилю."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

from config.paths import get_app_root
from modules.ui_nav.errors import UiNavError

_DEFAULT_RESOLUTION = "360x270"


def _parse_resolution(resolution: str) -> tuple[int, int]:
    raw = resolution.lower().replace(" ", "")
    if "x" not in raw:
        raise UiNavError(f"invalid cs_resolution: {resolution}")
    w, h = raw.split("x", 1)
    return int(w), int(h)


def _resolution_profile(resolution: str) -> str:
    w, h = _parse_resolution(resolution)
    return f"{w}x{h}"


def resolve_cs_coords_path(resolution: str = _DEFAULT_RESOLUTION) -> Path:
    """Path to coords_{w}x{h}.yaml for cs_resolution (explicit profile, no silent fallback)."""
    profile = _resolution_profile(resolution)
    path = get_app_root() / "resources" / "ui_nav" / f"coords_{profile}.yaml"
    if not path.is_file():
        raise UiNavError(
            f"CS2 coords profile missing: coords_{profile}.yaml "
            f"(cs_resolution={profile}). See docs/AI_PC_PROFILE.md"
        )
    return path


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
    profile: str = _DEFAULT_RESOLUTION

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


def _parse_coords_file(src: Path) -> tuple[int, int, dict[str, Point], dict[str, list[ColorProbe]]]:
    data = yaml.safe_load(src.read_text(encoding="utf-8"))
    meta = data.get("meta", {})
    base_w = int(meta.get("base_width", 360))
    base_h = int(meta.get("base_height", 270))

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
    return base_w, base_h, clicks, detectors


def load_nav_coords(
    resolution: str = _DEFAULT_RESOLUTION,
    path: Path | None = None,
) -> NavCoords:
    src = path or resolve_cs_coords_path(resolution)
    base_w, base_h, clicks, detectors = _parse_coords_file(src)
    target_w, target_h = _parse_resolution(resolution)
    profile = _resolution_profile(resolution)

    return NavCoords(
        base_width=base_w,
        base_height=base_h,
        clicks=clicks,
        detectors=detectors,
        scale_x=target_w / base_w if base_w else 1.0,
        scale_y=target_h / base_h if base_h else 1.0,
        profile=profile,
    )


def load_nav_coords_for_hwnd(
    hwnd: int | None,
    resolution: str = _DEFAULT_RESOLUTION,
    path: Path | None = None,
    *,
    on_warn: Callable[[str], None] | None = None,
) -> NavCoords:
    """Scale yaml base coords to actual CS2 client rect (preferred on Windows)."""
    src = path or resolve_cs_coords_path(resolution)
    base_w, base_h, clicks, detectors = _parse_coords_file(src)
    profile = _resolution_profile(resolution)

    if hwnd is None or sys.platform != "win32":
        return load_nav_coords(resolution, path)

    from modules.ui_nav.window import client_size

    client_w, client_h = client_size(hwnd)
    if on_warn and (abs(client_w - base_w) > 2 or abs(client_h - base_h) > 2):
        on_warn(
            f"CS2 client {client_w}x{client_h} differs from coords profile "
            f"{profile} base {base_w}x{base_h}; autoscaling coords to client"
        )

    return NavCoords(
        base_width=base_w,
        base_height=base_h,
        clicks=clicks,
        detectors=detectors,
        scale_x=client_w / base_w if base_w else 1.0,
        scale_y=client_h / base_h if base_h else 1.0,
        profile=profile,
    )
