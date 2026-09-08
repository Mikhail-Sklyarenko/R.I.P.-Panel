"""Fuse icon lock + place label into a map-frame pose for goal seeking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from nav.minimap_reader import MinimapReader
from nav.place_localizer import PlaceHit, PlaceLocalizer
from nav.pose import PoseResult
from nav.world_pose import YawTracker


@dataclass(frozen=True)
class PerceptionResult:
    icon: PoseResult
    place: Optional[PlaceHit]
    pose: PoseResult  # world when place locked, else centered/invalid


class NavPerception:
    def __init__(
        self,
        reader: MinimapReader,
        localizer: PlaceLocalizer,
        yaw: Optional[YawTracker] = None,
    ) -> None:
        self.reader = reader
        self.localizer = localizer
        self.yaw = yaw or YawTracker()

    def reset(self) -> None:
        self.yaw.reset()

    def update(
        self,
        frame: np.ndarray,
        *,
        face_x: float,
        face_y: float,
    ) -> PerceptionResult:
        icon = self.reader.read(frame)
        place = None
        if icon.valid and self.localizer.ready:
            place = self.localizer.localize(frame, self.reader.last_circle)

        if not icon.valid:
            return PerceptionResult(icon=icon, place=place, pose=PoseResult.invalid())

        if place is None:
            # Honest: no world pose without place read — do not invent GPS.
            return PerceptionResult(icon=icon, place=None, pose=icon)

        self.yaw.on_place(place.place_id, place.x, place.y, face_x, face_y)
        world = self.yaw.to_world_pose(
            x=place.x,
            y=place.y,
            icon=icon,
            place_id=place.place_id,
            confidence=min(1.0, 0.5 * icon.confidence + 0.5 * place.score),
        )
        return PerceptionResult(icon=icon, place=place, pose=world)
