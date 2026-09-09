"""Player pose on the HUD minimap / map frame."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# centered = CS2 HUD icon lock only (XY is radar center, not world GPS)
# world    = legacy place-label estimate; not accepted by measured navigation
# visual   = independently observed map XY/yaw with observed_at timestamp
# classic  = rare fixed-map radar where the icon moves across the image
# none     = no reliable player icon
RadarMode = str


@dataclass(frozen=True)
class PoseResult:
    """Pose for navigation.

    - ``centered``: x/y ≈ 0.5 (icon center). Do not chase as world GPS.
    - ``world``: x/y/yaw are map-normalized (0..1) for pack goals.
    - ``classic``: icon position on a fixed radar image.
    - ``place_id``: locked CS2 location-name landmark (discrete GPS).
    """

    x_norm: float
    y_norm: float
    yaw_deg: float
    confidence: float
    valid: bool
    blob_area_px: int = 0
    radar_mode: RadarMode = "classic"
    place_id: Optional[str] = None
    # Only independently measured map poses carry an observation timestamp.
    observed_at: Optional[float] = None

    @staticmethod
    def invalid() -> PoseResult:
        return PoseResult(0.5, 0.5, 0.0, 0.0, False, 0, "none", None)
