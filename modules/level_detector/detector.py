"""UI-детекция rank-up / weekly level banner (color probes)."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from PIL import Image

from config.paths import get_app_root
from modules.ui_nav.coords import ColorProbe, load_nav_coords


def _level_coords_path() -> Path:
    return get_app_root() / "resources" / "ui_nav" / "level_probes.yaml"


def _load_level_probes(resolution: str) -> list[ColorProbe]:
    level_path = _level_coords_path()
    if level_path.is_file():
        data = yaml.safe_load(level_path.read_text(encoding="utf-8")) or {}
        base_w = int(data.get("meta", {}).get("base_width", 360))
        base_h = int(data.get("meta", {}).get("base_height", 270))
        tw, th = _parse_res(resolution)
        sx, sy = tw / base_w, th / base_h
        probes: list[ColorProbe] = []
        for p in data.get("level_up", []):
            probes.append(
                ColorProbe(
                    int(p["x"] * sx),
                    int(p["y"] * sy),
                    tuple(int(c) for c in p["rgb"]),
                    int(p.get("tolerance", 50)),
                )
            )
        return probes
    nav = load_nav_coords(resolution)
    return nav.probes("level_up") if "level_up" in nav.detectors else []


def _parse_res(resolution: str) -> tuple[int, int]:
    w, h = resolution.lower().split("x", 1)
    return int(w), int(h)


def _probe_match(img: Image.Image, probe: ColorProbe) -> bool:
    if probe.x >= img.width or probe.y >= img.height:
        return False
    r, g, b = img.getpixel((probe.x, probe.y))[:3]
    tr, tg, tb = probe.rgb
    tol = probe.tolerance
    return (
        abs(r - tr) <= tol and abs(g - tg) <= tol and abs(b - tb) <= tol
    )


def detect_level_up(
    image: Image.Image,
    *,
    resolution: str = "360x270",
) -> bool:
    probes = _load_level_probes(resolution)
    if not probes:
        return False
    matched = sum(1 for p in probes if _probe_match(image, p))
    return matched >= max(1, len(probes) - 1)


def sim_level_up_elapsed() -> bool:
    """Тест/CI: LEVEL_DETECT_SIM + LEVEL_DETECT_AFTER_SEC."""
    if os.environ.get("LEVEL_DETECT_SIM", "").lower() not in ("1", "true", "yes"):
        return False
    after = float(os.environ.get("LEVEL_DETECT_AFTER_SEC", "1"))
    import time

    start = float(os.environ.get("_LEVEL_DETECT_SIM_START", "0") or "0")
    if start <= 0:
        return False
    return time.monotonic() - start >= after
