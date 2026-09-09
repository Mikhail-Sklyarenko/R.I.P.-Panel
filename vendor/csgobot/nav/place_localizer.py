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
import time
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

# Vertical offsets under the radar ring — OBS/HUD scale variance.
_STRIP_Y_OFFSETS = (0, 2, 4, 6, 8, -2)


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


@dataclass(frozen=True)
class PlaceMatchDebug:
    """Top candidates even when below accept threshold (for dumps / soak)."""

    best: Optional[PlaceHit]
    accepted: bool
    top: tuple[tuple[str, float], ...]
    strip: Optional[np.ndarray] = None


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
    y_offset: int = 2,
) -> Optional[np.ndarray]:
    if cv2 is None or frame is None:
        return None
    h, w = frame.shape[:2]
    y1 = int(circle.cy + circle.radius + y_offset)
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
        min_score: float = 0.54,
        min_margin: float = 0.18,
        sticky_id: Optional[str] = None,
        sticky_slack: float = 0.04,
    ) -> None:
        self._map_id = map_id
        self._min_score = min_score
        self._min_margin = min_margin
        self._sticky_id = sticky_id
        self._sticky_slack = sticky_slack
        self._templates: list[PlaceTemplate] = []
        self._last_debug: Optional[PlaceMatchDebug] = None
        self._load()

    @property
    def ready(self) -> bool:
        return len(self._templates) > 0

    @property
    def template_count(self) -> int:
        return len(self._templates)

    @property
    def last_debug(self) -> Optional[PlaceMatchDebug]:
        return self._last_debug

    def set_sticky(self, place_id: Optional[str]) -> None:
        """Bias match toward the currently held place (anti-flicker)."""
        self._sticky_id = place_id

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

        meta_landmarks: dict = {}
        meta_path = resolve_map_meta_path(self._map_id)
        if meta_path.is_file():
            try:
                meta_landmarks = (
                    json.loads(meta_path.read_text(encoding="utf-8")).get("landmarks")
                    or {}
                )
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
            strip = extract_location_strip(rgb, circle, y_offset=2)
            if strip is None:
                continue
            lm = meta_landmarks.get(place_id) if isinstance(meta_landmarks, dict) else None
            if isinstance(lm, dict) and "x" in lm and "y" in lm:
                x, y = float(lm["x"]), float(lm["y"])
            else:
                x, y = float(item.get("x", 0.5)), float(item.get("y", 0.5))
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

    def _score_strip(self, strip: np.ndarray) -> list[tuple[float, PlaceTemplate]]:
        scored: list[tuple[float, PlaceTemplate]] = []
        for tmpl in self._templates:
            sc = _ncc(strip, tmpl.strip)
            if self._sticky_id and tmpl.place_id == self._sticky_id:
                sc += self._sticky_slack
            scored.append((sc, tmpl))
        scored.sort(key=lambda t: t[0], reverse=True)
        return scored

    def match_debug(
        self,
        frame: np.ndarray,
        circle: Optional[RadarCircle] = None,
    ) -> PlaceMatchDebug:
        """Best multi-offset match + top-3 (accepted or not)."""
        empty = PlaceMatchDebug(best=None, accepted=False, top=(), strip=None)
        if not self.ready or cv2 is None or frame is None:
            self._last_debug = empty
            return empty
        circ = circle or detect_radar_circle(frame)
        if circ is None:
            self._last_debug = empty
            return empty

        best_overall: Optional[tuple[float, float, PlaceTemplate, np.ndarray]] = None
        # (score, margin, tmpl, strip)
        for y_off in _STRIP_Y_OFFSETS:
            strip = extract_location_strip(frame, circ, y_offset=y_off)
            if strip is None:
                continue
            scored = self._score_strip(strip)
            if not scored:
                continue
            best_sc, best = scored[0]
            second_sc = scored[1][0] if len(scored) > 1 else -1.0
            margin = best_sc - second_sc
            if best_overall is None or best_sc > best_overall[0]:
                best_overall = (best_sc, margin, best, strip)

        if best_overall is None:
            self._last_debug = empty
            return empty

        best_sc, margin, best, strip = best_overall
        # Recompute top-3 on winning strip without sticky for honest log names.
        top_scored = self._score_strip(strip)[:3]
        top = tuple((t.place_id, float(sc)) for sc, t in top_scored)
        # Undo sticky boost for accept threshold on the sticky candidate.
        accept_score = best_sc
        if self._sticky_id and best.place_id == self._sticky_id:
            accept_score = best_sc - self._sticky_slack
        hit = PlaceHit(
            place_id=best.place_id,
            x=best.x,
            y=best.y,
            score=float(accept_score),
            margin=float(margin),
            team=best.team,
        )
        # Sticky: keep place with slightly softer gate.
        min_score = self._min_score
        min_margin = self._min_margin
        if self._sticky_id and best.place_id == self._sticky_id:
            min_score = max(0.48, self._min_score - 0.04)
            min_margin = max(0.12, self._min_margin - 0.04)
        accepted = accept_score >= min_score and margin >= min_margin
        dbg = PlaceMatchDebug(
            best=hit if accepted else hit,
            accepted=accepted,
            top=top,
            strip=strip,
        )
        if not accepted:
            dbg = PlaceMatchDebug(
                best=None, accepted=False, top=top, strip=strip
            )
        self._last_debug = dbg
        return dbg

    def localize(
        self,
        frame: np.ndarray,
        circle: Optional[RadarCircle] = None,
    ) -> Optional[PlaceHit]:
        dbg = self.match_debug(frame, circle)
        return dbg.best if dbg.accepted else None


def dump_place_fail(
    frame: np.ndarray,
    debug: PlaceMatchDebug,
    *,
    out_dir: Path,
    tag: str = "fail",
) -> Optional[Path]:
    """Write live frame + strip + top scores for FermK calibration."""
    if cv2 is None:
        return None
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        base = out_dir / f"place_{tag}_{ts}"
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        cv2.imwrite(str(base.with_suffix(".jpg")), bgr)
        if debug.strip is not None:
            cv2.imwrite(str(base.with_name(base.name + "_strip.png")), debug.strip)
        meta = {
            "accepted": debug.accepted,
            "top": [{"id": i, "score": s} for i, s in debug.top],
            "best": None
            if debug.best is None
            else {
                "id": debug.best.place_id,
                "score": debug.best.score,
                "margin": debug.best.margin,
            },
        }
        base.with_suffix(".json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
        return base.with_suffix(".jpg")
    except OSError as exc:
        logger.warning("nav: place dump failed: %s", exc)
        return None
