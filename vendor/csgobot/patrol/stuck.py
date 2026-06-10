"""Detect patrol stuck via low frame motion in center ROI."""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

from .state import PatrolMode


def should_trigger_unstuck(
    *,
    anti_stuck_enabled: bool,
    activated: bool,
    patrol_mode: PatrolMode,
    in_combat: bool,
    is_moving: bool,
    stuck_since: Optional[float],
    now: float,
    stuck_sec: float,
    last_unstuck_time: float,
    unstuck_cooldown_sec: float,
) -> bool:
    if not anti_stuck_enabled or not activated:
        return False
    if patrol_mode != PatrolMode.PATROL or in_combat or not is_moving:
        return False
    if now - last_unstuck_time < unstuck_cooldown_sec:
        return False
    if stuck_since is None:
        return False
    return (now - stuck_since) >= stuck_sec


class StuckDetector:
    """Low mean abs diff between frames => likely stuck against geometry."""

    def __init__(
        self,
        motion_threshold: float = 2.0,
        sample_size: Tuple[int, int] = (64, 36),
    ) -> None:
        self.motion_threshold = motion_threshold
        self.sample_size = sample_size
        self._prev_sample: Optional[np.ndarray] = None
        self.last_motion: float = 0.0

    def _center_roi_gray(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        ch, cw = int(h * 0.5), int(w * 0.5)
        y0, x0 = (h - ch) // 2, (w - cw) // 2
        roi = frame[y0 : y0 + ch, x0 : x0 + cw]
        if roi.ndim == 3 and roi.shape[2] >= 3:
            gray = (
                0.299 * roi[:, :, 0]
                + 0.587 * roi[:, :, 1]
                + 0.114 * roi[:, :, 2]
            )
        else:
            gray = roi[:, :, 0] if roi.ndim == 3 else roi
        return self._downsample(gray.astype(np.float32))

    def _downsample(self, gray: np.ndarray) -> np.ndarray:
        tw, th = self.sample_size
        y_idx = np.linspace(0, gray.shape[0] - 1, th, dtype=int)
        x_idx = np.linspace(0, gray.shape[1] - 1, tw, dtype=int)
        return gray[np.ix_(y_idx, x_idx)]

    def update(self, frame: np.ndarray) -> float:
        if frame is None or frame.size == 0:
            return 0.0

        sample = self._center_roi_gray(frame)
        if self._prev_sample is None:
            self._prev_sample = sample
            self.last_motion = 0.0
            return 0.0

        diff = np.abs(sample - self._prev_sample)
        self.last_motion = float(np.mean(diff))
        self._prev_sample = sample
        return self.last_motion

    def is_low_motion(self) -> bool:
        return self.last_motion < self.motion_threshold

    def reset(self) -> None:
        self._prev_sample = None
        self.last_motion = 0.0
