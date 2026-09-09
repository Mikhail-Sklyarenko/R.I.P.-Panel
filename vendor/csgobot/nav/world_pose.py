"""Yaw tracking after a real place lock (not spawn-seed GPS).

Position comes from PlaceLocalizer (CS2 location-name under the radar).
Yaw is bootstrapped toward the next path hop, then integrated from commanded
mouse turns. We never invent map XY.
"""

from __future__ import annotations

import math
from typing import Optional

from nav.coords import bearing_deg, normalize_angle_deg
from nav.pose import PoseResult


class YawTracker:
    def __init__(self) -> None:
        self._yaw: Optional[float] = None
        self._place_id: Optional[str] = None

    def reset(self) -> None:
        self._yaw = None
        self._place_id = None

    @property
    def yaw_deg(self) -> Optional[float]:
        return self._yaw

    def on_place(
        self,
        place_id: str,
        x: float,
        y: float,
        face_x: float,
        face_y: float,
    ) -> None:
        """When place ID changes (or first lock), face the next hop."""
        if place_id != self._place_id or self._yaw is None:
            self._yaw = bearing_deg(x, y, face_x, face_y)
            self._place_id = place_id

    def integrate(self, yaw_delta_deg: float) -> None:
        if self._yaw is None:
            return
        self._yaw = normalize_angle_deg(self._yaw + float(yaw_delta_deg))

    def to_world_pose(
        self,
        *,
        x: float,
        y: float,
        icon: PoseResult,
        place_id: str,
        confidence: float,
    ) -> PoseResult:
        yaw = self._yaw if self._yaw is not None else -90.0
        return PoseResult(
            x_norm=float(x),
            y_norm=float(y),
            yaw_deg=float(yaw),
            confidence=max(float(confidence), 0.55),
            valid=True,
            blob_area_px=icon.blob_area_px,
            radar_mode="world",
            place_id=place_id,
        )


# Keep module import stable for any leftover references.
WorldPoseTracker = YawTracker  # type: ignore
WALK_SPEED_FLOW = 0.0
WALK_SPEED_BLIND = 0.0
