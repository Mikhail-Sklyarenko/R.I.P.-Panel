"""EMA filter on aim point to reduce YOLO bbox jitter."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot


@dataclass
class AimSmoothConfig:
    enabled: bool = True
    alpha: float = 0.45
    jump_reset_px: float = 80.0


class AimPointSmoother:
    """Exponential moving average on (x, y) before lead / FOV math."""

    def __init__(self, config: AimSmoothConfig | None = None) -> None:
        self.config = config or AimSmoothConfig()
        self._x: float | None = None
        self._y: float | None = None

    def reset(self) -> None:
        self._x = None
        self._y = None

    def update(self, x: float, y: float, _now: float = 0.0) -> tuple[float, float]:
        if not self.config.enabled:
            return x, y

        if self._x is None or self._y is None:
            self._x, self._y = x, y
            return x, y

        jump = hypot(x - self._x, y - self._y)
        if jump > self.config.jump_reset_px:
            self._x, self._y = x, y
            return x, y

        alpha = max(0.05, min(1.0, self.config.alpha))
        self._x = alpha * x + (1.0 - alpha) * self._x
        self._y = alpha * y + (1.0 - alpha) * self._y
        return self._x, self._y
