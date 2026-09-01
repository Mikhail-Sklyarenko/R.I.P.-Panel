"""Temporal smoothing for minimap pose reads."""

from __future__ import annotations

import time
from typing import Optional

from nav.calibration import PoseFilterConfig
from nav.coords import normalize_angle_deg
from nav.pose import PoseResult


class PoseFilter:
    def __init__(self, config: PoseFilterConfig) -> None:
        self._cfg = config
        self._x: Optional[float] = None
        self._y: Optional[float] = None
        self._yaw: Optional[float] = None
        self._last_valid_at: float = 0.0

    def reset(self) -> None:
        self._x = None
        self._y = None
        self._yaw = None
        self._last_valid_at = 0.0

    def update(self, raw: PoseResult, *, now: Optional[float] = None) -> PoseResult:
        ts = time.monotonic() if now is None else now
        if not raw.valid:
            if self._x is not None and (ts - self._last_valid_at) <= self._cfg.lost_timeout_sec:
                return PoseResult(
                    x_norm=self._x,
                    y_norm=self._y,
                    yaw_deg=self._yaw or 0.0,
                    confidence=raw.confidence * 0.5,
                    valid=True,
                    blob_area_px=raw.blob_area_px,
                )
            return PoseResult.invalid()

        alpha = self._cfg.smooth_alpha
        if self._x is None:
            self._x = raw.x_norm
            self._y = raw.y_norm
            self._yaw = raw.yaw_deg
        else:
            self._x = alpha * raw.x_norm + (1.0 - alpha) * self._x
            self._y = alpha * raw.y_norm + (1.0 - alpha) * self._y
            yaw_delta = normalize_angle_deg(raw.yaw_deg - (self._yaw or 0.0))
            self._yaw = normalize_angle_deg((self._yaw or 0.0) + alpha * yaw_delta)

        self._last_valid_at = ts
        return PoseResult(
            x_norm=self._x,
            y_norm=self._y,
            yaw_deg=self._yaw or 0.0,
            confidence=raw.confidence,
            valid=True,
            blob_area_px=raw.blob_area_px,
        )
