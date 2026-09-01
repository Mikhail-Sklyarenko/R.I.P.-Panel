"""Player pose on the HUD minimap (normalized radar coordinates)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PoseResult:
    """Pose in normalized minimap space (0..1, origin top-left of radar square)."""

    x_norm: float
    y_norm: float
    yaw_deg: float
    confidence: float
    valid: bool
    blob_area_px: int = 0

    @staticmethod
    def invalid() -> PoseResult:
        return PoseResult(0.5, 0.5, 0.0, 0.0, False, 0)
