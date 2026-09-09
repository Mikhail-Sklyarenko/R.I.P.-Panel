"""Fuse icon lock + place label into a map-frame pose for goal seeking."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from nav.minimap_reader import MinimapReader
from nav.place_localizer import PlaceHit, PlaceLocalizer
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
    """Product perception: place-label → world pose, with short hold on flicker."""

    def __init__(
        self,
        reader: MinimapReader,
        localizer: PlaceLocalizer,
        yaw: Optional[YawTracker] = None,
        *,
        hold_sec: float = 4.0,
        log_interval_sec: float = 2.0,
    ) -> None:
        self.reader = reader
        self.localizer = localizer
        self.yaw = yaw or YawTracker()
        self._hold_sec = max(0.5, float(hold_sec))
        self._log_interval = max(0.5, float(log_interval_sec))
        self._last_hit: Optional[PlaceHit] = None
        self._last_hit_at: float = 0.0
        self._last_log_at: float = 0.0

    def reset(self) -> None:
        self.yaw.reset()
        self._last_hit = None
        self._last_hit_at = 0.0

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
        place = None
        if icon.valid and self.localizer.ready:
            place = self.localizer.localize(frame, self.reader.last_circle)

        if not icon.valid:
            return PerceptionResult(icon=icon, place=place, pose=PoseResult.invalid())

        if place is not None:
            self._last_hit = place
            self._last_hit_at = ts
            if ts - self._last_log_at >= self._log_interval:
                self._last_log_at = ts
                logger.info(
                    "nav: place=%s score=%.3f margin=%.3f map=(%.2f,%.2f)",
                    place.place_id,
                    place.score,
                    place.margin,
                    place.x,
                    place.y,
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

        return PerceptionResult(icon=icon, place=None, pose=icon, place_held=False)
