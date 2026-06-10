"""UI-детекция rank-up / weekly level banner (color probes)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from PIL import Image

from config.paths import get_app_root
from modules.ui_nav.coords import ColorProbe, load_nav_coords


@dataclass(frozen=True)
class LevelProbeConfig:
    probes: list[ColorProbe]
    min_matches: int


def _parse_res(resolution: str) -> tuple[int, int]:
    w, h = resolution.lower().replace(" ", "").split("x", 1)
    return int(w), int(h)


def _level_coords_path(resolution: str = "360x270") -> Path | None:
    w, h = _parse_res(resolution)
    profile = f"{w}x{h}"
    specific = get_app_root() / "resources" / "ui_nav" / f"level_probes_{profile}.yaml"
    if specific.is_file():
        return specific
    default = get_app_root() / "resources" / "ui_nav" / "level_probes.yaml"
    if default.is_file():
        return default
    return None


def load_level_probe_config(resolution: str) -> LevelProbeConfig:
    level_path = _level_coords_path(resolution)
    if level_path is not None:
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
        meta_min = data.get("meta", {}).get("min_matches")
        min_matches = int(meta_min) if meta_min is not None else len(probes)
        return LevelProbeConfig(
            probes=probes,
            min_matches=max(1, min(min_matches, len(probes))) if probes else 0,
        )

    nav = load_nav_coords(resolution)
    probes = nav.probes("level_up") if "level_up" in nav.detectors else []
    return LevelProbeConfig(probes=probes, min_matches=len(probes))


def _probe_match(img: Image.Image, probe: ColorProbe) -> bool:
    if probe.x >= img.width or probe.y >= img.height:
        return False
    r, g, b = img.getpixel((probe.x, probe.y))[:3]
    tr, tg, tb = probe.rgb
    tol = probe.tolerance
    return (
        abs(r - tr) <= tol and abs(g - tg) <= tol and abs(b - tb) <= tol
    )


def count_level_up_matches(
    image: Image.Image,
    *,
    resolution: str = "360x270",
) -> tuple[int, int, int]:
    """Return (matched, required, total_probes)."""
    cfg = load_level_probe_config(resolution)
    if not cfg.probes:
        return 0, 0, 0
    matched = sum(1 for p in cfg.probes if _probe_match(image, p))
    return matched, cfg.min_matches, len(cfg.probes)


def detect_level_up(
    image: Image.Image,
    *,
    resolution: str = "360x270",
    min_matches: int | None = None,
) -> bool:
    matched, required, total = count_level_up_matches(image, resolution=resolution)
    if total == 0:
        return False
    need = required if min_matches is None else max(1, min(min_matches, total))
    return matched >= need


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
