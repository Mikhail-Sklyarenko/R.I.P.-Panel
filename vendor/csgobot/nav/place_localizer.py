"""Localize player on the map by reading CS2's location-name under the radar.

Objective product perception (Gate 0 = centered radar):
- Icon XY on a rotating radar is NOT world GPS.
- Matching live rings to radar.png is unreliable (domain gap).
- CS2 prints the area name under the minimap — that string *is* a place ID.

We match the live text strip to labeled ``hud_ref`` templates and return the
landmark coordinates from the manifest. No spawn-seed cosmetics.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore

from nav.paths import resolve_map_meta_path, resolve_nav_root
from nav.radar_geom import RadarCircle, detect_radar_circle

logger = logging.getLogger("CS2Bot.nav")


@dataclass(frozen=True)
class PlaceHit:
    place_id: str
    x: float
    y: float
    score: float
    margin: float
    team: str = "any"


@dataclass(frozen=True)
class PlaceTemplate:
    place_id: str
    x: float
    y: float
    team: str
    strip: np.ndarray
    source: str


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    aa = a.astype(np.float32).ravel()
    bb = b.astype(np.float32).ravel()
    if aa.size == 0 or bb.size == 0:
        return -1.0
    aa = (aa - aa.mean()) / (aa.std() + 1e-6)
    bb = (bb - bb.mean()) / (bb.std() + 1e-6)
    return float((aa * bb).mean())


def extract_location_strip(
    frame: np.ndarray,
    circle: RadarCircle,
    *,
    width: int = 180,
    height: int = 24,
) -> Optional[np.ndarray]:
    if cv2 is None or frame is None:
        return None
    h, w = frame.shape[:2]
    y1 = int(circle.cy + circle.radius + 2)
    y2 = min(h, y1 + 28)
    x1 = max(0, int(circle.cx - 110))
    x2 = min(w, int(circle.cx + 110))
    if y2 <= y1 + 8 or x2 <= x1 + 20:
        return None
    strip = frame[y1:y2, x1:x2]
    if strip.ndim == 3:
        gray = cv2.cvtColor(strip, cv2.COLOR_RGB2GRAY)
    else:
        gray = strip
    gray = cv2.createCLAHE(2.0, (4, 4)).apply(gray)
    return cv2.resize(gray, (width, height), interpolation=cv2.INTER_AREA)


def resolve_hud_ref_dir(map_id: str) -> Path:
    return resolve_nav_root() / "maps" / map_id / "hud_ref"


class PlaceLocalizer:
    """Match CS2 location-name strip → landmark (x, y)."""

    def __init__(
        self,
        map_id: str,
        *,
        min_score: float = 0.55,
        min_margin: float = 0.20,
    ) -> None:
        self._map_id = map_id
        self._min_score = min_score
        self._min_margin = min_margin
        self._templates: list[PlaceTemplate] = []
        self._load()

    @property
    def ready(self) -> bool:
        return len(self._templates) > 0

    @property
    def template_count(self) -> int:
        return len(self._templates)

    def _load(self) -> None:
        if cv2 is None:
            return
        ref_dir = resolve_hud_ref_dir(self._map_id)
        man_path = ref_dir / "manifest.json"
        if not man_path.is_file():
            logger.warning("nav: place localizer — no hud_ref manifest at %s", man_path)
            return
        try:
            data = json.loads(man_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("nav: place localizer manifest error: %s", exc)
            return

        # Optional landmark overrides from map meta
        meta_landmarks: dict = {}
        meta_path = resolve_map_meta_path(self._map_id)
        if meta_path.is_file():
            try:
                meta_landmarks = (json.loads(meta_path.read_text(encoding="utf-8")).get("landmarks") or {})
            except (OSError, json.JSONDecodeError):
                meta_landmarks = {}

        for item in data.get("refs") or []:
            frame_name = str(item.get("frame") or "")
            place_id = str(item.get("landmark") or item.get("id") or "").strip()
            if not frame_name or not place_id:
                continue
            frame_path = ref_dir / frame_name
            if not frame_path.is_file():
                continue
            bgr = cv2.imread(str(frame_path))
            if bgr is None:
                continue
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            circle = detect_radar_circle(rgb)
            if circle is None:
                continue
            strip = extract_location_strip(rgb, circle)
            if strip is None:
                continue
            lm = meta_landmarks.get(place_id) if isinstance(meta_landmarks, dict) else None
            if isinstance(lm, dict) and "x" in lm and "y" in lm:
                x, y = float(lm["x"]), float(lm["y"])
            else:
                x, y = float(item.get("x", 0.5)), float(item.get("y", 0.5))
            # Extra landmarks not in meta (tunnel/long/short) keep manifest coords.
            self._templates.append(
                PlaceTemplate(
                    place_id=place_id,
                    x=x,
                    y=y,
                    team=str(item.get("team") or "any"),
                    strip=strip,
                    source=frame_name,
                )
            )
        logger.info(
            "nav: place localizer loaded %d templates map=%s",
            len(self._templates),
            self._map_id,
        )

    def localize(
        self,
        frame: np.ndarray,
        circle: Optional[RadarCircle] = None,
    ) -> Optional[PlaceHit]:
        if not self.ready or cv2 is None or frame is None:
            return None
        circ = circle or detect_radar_circle(frame)
        if circ is None:
            return None
        strip = extract_location_strip(frame, circ)
        if strip is None:
            return None
        scored: list[tuple[float, PlaceTemplate]] = []
        for tmpl in self._templates:
            scored.append((_ncc(strip, tmpl.strip), tmpl))
        scored.sort(key=lambda t: t[0], reverse=True)
        if not scored:
            return None
        best_sc, best = scored[0]
        second_sc = scored[1][0] if len(scored) > 1 else -1.0
        margin = best_sc - second_sc
        if best_sc < self._min_score or margin < self._min_margin:
            return None
        return PlaceHit(
            place_id=best.place_id,
            x=best.x,
            y=best.y,
            score=best_sc,
            margin=margin,
            team=best.team,
        )
