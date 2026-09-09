"""Temporal smoothing for minimap pose reads."""

from __future__ import annotations

import time
from typing import Optional

from nav.calibration import PoseFilterConfig
from nav.coords import normalize_angle_deg
from nav.pose import PoseResult


class PoseFilter:
    """Smooth pose; preserve recent world place against centered flicker."""

    def __init__(
        self,
        config: PoseFilterConfig,
        *,
        world_hold_sec: float = 4.0,
    ) -> None:
        self._cfg = config
        self._world_hold_sec = max(0.5, float(world_hold_sec))
        self._x: Optional[float] = None
        self._y: Optional[float] = None
        self._yaw: Optional[float] = None
        self._place_id: Optional[str] = None
        self._last_valid_at: float = 0.0
        self._last_world_at: float = 0.0
        self._radar_mode: str = "centered"

    def reset(self) -> None:
        self._x = None
        self._y = None
        self._yaw = None
        self._place_id = None
        self._last_valid_at = 0.0
        self._last_world_at = 0.0
        self._radar_mode = "centered"

    def update(self, raw: PoseResult, *, now: Optional[float] = None) -> PoseResult:
        ts = time.monotonic() if now is None else now
        # Measured visual poses retain their timestamp and never turn into held
        # place coordinates. Smoothing/holding must not manufacture fresh data.
        if raw.radar_mode == "visual":
            self.reset()
            return raw
        if not raw.valid:
            if self._x is not None and (ts - self._last_valid_at) <= self._cfg.lost_timeout_sec:
                return PoseResult(
                    x_norm=self._x,
                    y_norm=self._y,
                    yaw_deg=self._yaw or 0.0,
                    confidence=raw.confidence * 0.5,
                    valid=True,
                    blob_area_px=raw.blob_area_px,
                    radar_mode=self._radar_mode,
                    place_id=self._place_id,
                )
            return PoseResult.invalid()

        # Do not let a centered icon frame erase a fresh world place lock.
        if (
            (raw.radar_mode or "centered") != "world"
            and self._radar_mode == "world"
            and self._x is not None
            and (ts - self._last_world_at) <= self._world_hold_sec
        ):
            if self._yaw is None:
                self._yaw = raw.yaw_deg
            else:
                yaw_delta = normalize_angle_deg(raw.yaw_deg - self._yaw)
                alpha = self._cfg.smooth_alpha
                self._yaw = normalize_angle_deg(self._yaw + alpha * yaw_delta)
            self._last_valid_at = ts
            return PoseResult(
                x_norm=self._x,
                y_norm=self._y,
                yaw_deg=self._yaw or 0.0,
                confidence=max(raw.confidence, 0.55),
                valid=True,
                blob_area_px=raw.blob_area_px,
                radar_mode="world",
                place_id=self._place_id,
            )

        self._radar_mode = raw.radar_mode or "centered"
        if raw.radar_mode == "world":
            self._x = raw.x_norm
            self._y = raw.y_norm
            self._place_id = raw.place_id or self._place_id
            if self._yaw is None:
                self._yaw = raw.yaw_deg
            else:
                yaw_delta = normalize_angle_deg(raw.yaw_deg - self._yaw)
                alpha = self._cfg.smooth_alpha
                self._yaw = normalize_angle_deg(self._yaw + alpha * yaw_delta)
            self._last_valid_at = ts
            self._last_world_at = ts
            return PoseResult(
                x_norm=self._x,
                y_norm=self._y,
                yaw_deg=self._yaw or 0.0,
                confidence=raw.confidence,
                valid=True,
                blob_area_px=raw.blob_area_px,
                radar_mode="world",
                place_id=self._place_id,
            )

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

        self._place_id = None
        self._last_valid_at = ts
        return PoseResult(
            x_norm=self._x,
            y_norm=self._y,
            yaw_deg=self._yaw or 0.0,
            confidence=raw.confidence,
            valid=True,
            blob_area_px=raw.blob_area_px,
            radar_mode=self._radar_mode,
            place_id=None,
        )
