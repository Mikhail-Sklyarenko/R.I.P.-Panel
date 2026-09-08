"""Annular radar optical-flow / frame-diff for centered-radar progress."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class RadarFlowResult:
    motion: float
    progressing: bool


class RadarFlowSensor:
    """Measures map-texture motion in the minimap ring (player punched out).

    On a centered CS2 radar the player icon stays still while the map scrolls
    under it when the bot walks — that scroll is our only reliable progress
    signal (absolute blob XY is wrong in this HUD mode).
    """

    def __init__(
        self,
        *,
        progress_threshold: float = 2.8,
        ema_alpha: float = 0.35,
    ) -> None:
        self._prev: Optional[np.ndarray] = None
        self._ema = 0.0
        self._progress_threshold = progress_threshold
        self._ema_alpha = ema_alpha

    def reset(self) -> None:
        self._prev = None
        self._ema = 0.0

    def update(self, ring_gray: Optional[np.ndarray]) -> RadarFlowResult:
        if ring_gray is None or ring_gray.size == 0:
            return RadarFlowResult(motion=self._ema, progressing=False)

        cur = ring_gray.astype(np.float32)
        if self._prev is None or self._prev.shape != cur.shape:
            self._prev = cur
            return RadarFlowResult(motion=0.0, progressing=False)

        # Mean absolute difference on the ring (zeros outside mask already).
        active = (self._prev > 0) | (cur > 0)
        if not np.any(active):
            self._prev = cur
            return RadarFlowResult(motion=0.0, progressing=False)

        diff = np.abs(cur - self._prev)
        motion = float(diff[active].mean())
        self._ema = (
            self._ema_alpha * motion + (1.0 - self._ema_alpha) * self._ema
        )
        self._prev = cur
        return RadarFlowResult(
            motion=self._ema,
            progressing=self._ema >= self._progress_threshold,
        )
