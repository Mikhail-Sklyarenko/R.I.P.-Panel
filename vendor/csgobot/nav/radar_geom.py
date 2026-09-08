"""Detect CS2 minimap circle in the live frame (HUD size varies by settings)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore


@dataclass(frozen=True)
class RadarCircle:
    cx: float
    cy: float
    radius: float

    @property
    def rect(self) -> tuple[int, int, int, int]:
        """Inclusive-ish crop box (x, y, w, h) around the disk."""
        pad = 4
        x = max(0, int(self.cx - self.radius - pad))
        y = max(0, int(self.cy - self.radius - pad))
        s = int(2 * self.radius + 2 * pad)
        return x, y, s, s


def detect_radar_circle(
    frame: np.ndarray,
    *,
    search: int = 300,
    min_radius: int = 70,
    max_radius: int = 125,
) -> Optional[RadarCircle]:
    """Hough-circle the gold radar ring in the top-left HUD."""
    if cv2 is None or frame is None or frame.size == 0:
        return None
    h, w = frame.shape[:2]
    roi = frame[0 : min(search, h), 0 : min(search, w)]
    if roi.size == 0:
        return None
    gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY) if roi.ndim == 3 else roi
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    circles = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=100,
        param1=100,
        param2=40,
        minRadius=min_radius,
        maxRadius=max_radius,
    )
    if circles is None:
        circles = cv2.HoughCircles(
            gray,
            cv2.HOUGH_GRADIENT,
            dp=1.5,
            minDist=80,
            param1=80,
            param2=28,
            minRadius=min_radius - 10,
            maxRadius=max_radius + 10,
        )
    if circles is None:
        return None
    c = circles[0][0]
    return RadarCircle(cx=float(c[0]), cy=float(c[1]), radius=float(c[2]))
