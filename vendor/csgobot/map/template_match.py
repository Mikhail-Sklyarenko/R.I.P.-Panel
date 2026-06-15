"""Grayscale template matching for map name crops (no Tesseract required)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from map.parse import MapScriptId


class MapTemplateLoadError(ValueError):
    pass


@dataclass(frozen=True)
class MapTemplate:
    script: MapScriptId
    source: str
    image: np.ndarray


def _to_gray(arr: np.ndarray) -> np.ndarray:
    if arr.ndim == 2:
        return arr.astype(np.float32)
    if arr.shape[2] == 4:
        arr = arr[:, :, :3]
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    gray = 0.299 * r + 0.587 * g + 0.114 * b
    return gray.astype(np.float32)


def crop_gray(img: np.ndarray, rect_x: int, rect_y: int, rect_w: int, rect_h: int) -> np.ndarray:
    return _to_gray(img[rect_y : rect_y + rect_h, rect_x : rect_x + rect_w])


def max_ncc(haystack: np.ndarray, needle: np.ndarray) -> float:
    """Max normalized cross-correlation; returns -1 when needle larger than haystack."""
    h = haystack.astype(np.float32)
    n = needle.astype(np.float32)
    nh, nw = n.shape
    H, W = h.shape
    if nh > H or nw > W or nh == 0 or nw == 0:
        return -1.0

    n = n - n.mean()
    denom_n = float(np.sqrt(np.sum(n * n)) + 1e-6)

    try:
        import cv2

        result = cv2.matchTemplate(h, n, cv2.TM_CCOEFF_NORMED)
        return float(result.max())
    except ImportError:
        pass

    best = -1.0
    for y in range(H - nh + 1):
        for x in range(W - nw + 1):
            patch = h[y : y + nh, x : x + nw]
            p = patch - patch.mean()
            denom = denom_n * (float(np.sqrt(np.sum(p * p)) + 1e-6))
            score = float(np.sum(p * n) / denom)
            if score > best:
                best = score
    return best


def load_map_templates(directory: Path | str) -> tuple[MapTemplate, ...]:
    directory = Path(directory)
    if not directory.is_dir():
        raise MapTemplateLoadError(f"map templates dir not found: {directory}")

    templates: list[MapTemplate] = []
    for path in sorted(directory.glob("*.png")):
        stem = path.stem.lower()
        if stem.startswith("sb_"):
            script = stem[3:]
            source = "scoreboard"
        elif stem.startswith("ready_"):
            script = stem[6:]
            source = "match_ready"
        else:
            continue
        if script not in ("dust2", "mirage"):
            continue
        img = np.asarray(Image.open(path).convert("RGB"))
        templates.append(
            MapTemplate(script=script, source=source, image=_to_gray(img))
        )

    if not templates:
        raise MapTemplateLoadError(f"no map templates in {directory}")

    return tuple(templates)


def match_map_templates(
    crop: np.ndarray,
    templates: tuple[MapTemplate, ...],
    *,
    source: str,
    threshold: float,
) -> Optional[MapScriptId]:
    hay = _to_gray(crop) if crop.ndim == 3 else crop.astype(np.float32)
    best_script: Optional[MapScriptId] = None
    best_score = threshold

    for template in templates:
        if template.source != source:
            continue
        score = max_ncc(hay, template.image)
        if score >= best_score:
            best_score = score
            best_script = template.script

    return best_script
