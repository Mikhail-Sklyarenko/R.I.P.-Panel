"""Fuse icon lock + place label into a map-frame pose for goal seeking."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from nav.minimap_reader import MinimapReader
from nav.place_localizer import (
    PlaceHit,
    PlaceLocalizer,
    dump_place_fail,
)
from nav.pose import PoseResult
from nav.world_pose import YawTracker

logger = logging.getLogger("CS2Bot.nav")


@dataclass(frozen=True)
class PerceptionResult:
    icon: PoseResult
    place: Optional[PlaceHit]
    pose: PoseResult  # world when place locked/held, else centered/invalid
    place_held: bool = False


class NavPerception:
    """Product perception: place-label → world pose, hold + switch hysteresis."""

    def __init__(
        self,
        reader: MinimapReader,
        localizer: PlaceLocalizer,
        yaw: Optional[YawTracker] = None,
        *,
        hold_sec: float = 4.0,
        log_interval_sec: float = 2.0,
        switch_confirm: int = 2,
        dump_dir: Optional[Path] = None,
        dump_interval_sec: float = 8.0,
    ) -> None:
        self.reader = reader
        self.localizer = localizer
        self.yaw = yaw or YawTracker()
        self._hold_sec = max(0.5, float(hold_sec))
        self._log_interval = max(0.5, float(log_interval_sec))
        self._switch_confirm = max(1, int(switch_confirm))
        self._dump_dir = dump_dir
        self._dump_interval = max(3.0, float(dump_interval_sec))
        self._last_hit: Optional[PlaceHit] = None
        self._last_hit_at: float = 0.0
        self._last_log_at: float = 0.0
        self._last_dump_at: float = 0.0
        self._pending_id: Optional[str] = None
        self._pending_count: int = 0

    def reset(self) -> None:
        self.yaw.reset()
        self._last_hit = None
        self._last_hit_at = 0.0
        self._pending_id = None
        self._pending_count = 0
        self.localizer.set_sticky(None)

    def _resolve_place(self, raw: Optional[PlaceHit]) -> Optional[PlaceHit]:
        """Hysteresis: require N consecutive reads to switch place_id."""
        if raw is None:
            self._pending_id = None
            self._pending_count = 0
            return None
        if self._last_hit is None or raw.place_id == self._last_hit.place_id:
            self._pending_id = None
            self._pending_count = 0
            return raw
        # Candidate switch
        if raw.place_id == self._pending_id:
            self._pending_count += 1
        else:
            self._pending_id = raw.place_id
            self._pending_count = 1
        if self._pending_count >= self._switch_confirm:
            self._pending_id = None
            self._pending_count = 0
            return raw
        # Keep previous place id coords until confirmed
        return self._last_hit

    def update(
        self,
        frame: np.ndarray,
        *,
        face_x: float,
        face_y: float,
        now: Optional[float] = None,
    ) -> PerceptionResult:
        ts = time.monotonic() if now is None else now
        icon = self.reader.read(frame)
        raw_place = None
        if icon.valid and self.localizer.ready:
            if self._last_hit is not None:
                self.localizer.set_sticky(self._last_hit.place_id)
            raw_place = self.localizer.localize(frame, self.reader.last_circle)

        if not icon.valid:
            return PerceptionResult(icon=icon, place=raw_place, pose=PoseResult.invalid())

        place = self._resolve_place(raw_place)

        if place is not None and raw_place is not None:
            # Only refresh hold clock on a fresh accepted localize (not hysteresis echo).
            if raw_place.place_id == place.place_id:
                self._last_hit = place
                self._last_hit_at = ts
            if ts - self._last_log_at >= self._log_interval:
                self._last_log_at = ts
                logger.info(
                    "nav: place=%s score=%.3f margin=%.3f map=(%.2f,%.2f)%s",
                    place.place_id,
                    place.score,
                    place.margin,
                    place.x,
                    place.y,
                    " (held-id)" if place is self._last_hit and raw_place.place_id != place.place_id else "",
                )
            self.yaw.on_place(place.place_id, place.x, place.y, face_x, face_y)
            world = self.yaw.to_world_pose(
                x=place.x,
                y=place.y,
                icon=icon,
                place_id=place.place_id,
                confidence=min(1.0, 0.5 * icon.confidence + 0.5 * place.score),
            )
            return PerceptionResult(icon=icon, place=place, pose=world, place_held=False)

        # Product hold: brief label flicker must not drop to centered cosmetics.
        if (
            self._last_hit is not None
            and (ts - self._last_hit_at) <= self._hold_sec
        ):
            hit = self._last_hit
            self.yaw.on_place(hit.place_id, hit.x, hit.y, face_x, face_y)
            world = self.yaw.to_world_pose(
                x=hit.x,
                y=hit.y,
                icon=icon,
                place_id=hit.place_id,
                confidence=min(1.0, 0.35 * icon.confidence + 0.35 * hit.score),
            )
            return PerceptionResult(
                icon=icon, place=hit, pose=world, place_held=True
            )

        # Fail dump for FermK calibration (rate-limited).
        if (
            self._dump_dir is not None
            and ts - self._last_dump_at >= self._dump_interval
        ):
            dbg = self.localizer.last_debug or self.localizer.match_debug(
                frame, self.reader.last_circle
            )
            path = dump_place_fail(frame, dbg, out_dir=self._dump_dir, tag="miss")
            self._last_dump_at = ts
            if path is not None:
                top_s = ", ".join(f"{i}:{s:.2f}" for i, s in dbg.top[:3])
                logger.info("nav: place miss dump=%s top=[%s]", path.name, top_s)

        return PerceptionResult(icon=icon, place=None, pose=icon, place_held=False)


def resolve_place_dump_dir() -> Optional[Path]:
    """CSGOBOT_NAV_DUMP_PLACE=1 → vendor/csgobot/data/nav_place_dumps (gitignored)."""
    raw = os.environ.get("CSGOBOT_NAV_DUMP_PLACE", "").strip().lower()
    if raw not in ("1", "true", "yes", "on"):
        return None
    custom = os.environ.get("CSGOBOT_NAV_DUMP_DIR", "").strip()
    if custom:
        return Path(custom)
    # nav/perception.py → vendor/csgobot/
    root = Path(__file__).resolve().parents[1]
    return root / "data" / "nav_place_dumps"
