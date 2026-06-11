"""EMA velocity tracking and lead prediction for moving targets."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import hypot


@dataclass
class LeadConfig:
    """Lead-aim parameters."""

    enabled: bool = True
    lead_ms: float = 80.0
    ema_alpha: float = 0.35
    max_lead_px: float = 120.0
    max_gap_sec: float = 0.5
    variance_gate: bool = True
    min_speed_px_s: float = 40.0
    max_speed_variance: float = 2500.0
    speed_window: int = 5


@dataclass
class LeadPredictResult:
    x: float
    y: float
    lead_applied: bool
    speed_px_s: float
    stable: bool


class VelocityLead:
    """
    Predict aim point ahead of a moving target using EMA-smoothed velocity.

    pos_lead = pos + velocity * (lead_ms / 1000)
    """

    def __init__(self, config: LeadConfig | None = None) -> None:
        self.config = config or LeadConfig()
        self._vx = 0.0
        self._vy = 0.0
        self._last_x: float | None = None
        self._last_y: float | None = None
        self._last_time: float | None = None
        window = max(2, self.config.speed_window)
        self._speeds: deque[float] = deque(maxlen=window)
        self._vx_hist: deque[float] = deque(maxlen=window)
        self._vy_hist: deque[float] = deque(maxlen=window)

    def reset(self) -> None:
        self._vx = 0.0
        self._vy = 0.0
        self._last_x = None
        self._last_y = None
        self._last_time = None
        self._speeds.clear()
        self._vx_hist.clear()
        self._vy_hist.clear()

    @staticmethod
    def _sign_flips(samples: deque[float]) -> int:
        vals = list(samples)
        flips = 0
        for a, b in zip(vals[:-1], vals[1:]):
            if a * b < 0:
                flips += 1
        return flips

    def _velocity_stable(self, speed: float) -> bool:
        if not self.config.variance_gate:
            return speed >= self.config.min_speed_px_s

        if speed < self.config.min_speed_px_s:
            return False

        if len(self._speeds) < 3:
            return False

        if self._sign_flips(self._vx_hist) >= 2 or self._sign_flips(self._vy_hist) >= 2:
            return False

        mean = sum(self._speeds) / len(self._speeds)
        var = sum((s - mean) ** 2 for s in self._speeds) / len(self._speeds)
        return var <= self.config.max_speed_variance

    def predict(self, x: float, y: float, now: float) -> LeadPredictResult:
        if not self.config.enabled:
            return LeadPredictResult(x, y, False, 0.0, False)

        if self._last_time is None or self._last_x is None or self._last_y is None:
            self._last_x, self._last_y, self._last_time = x, y, now
            return LeadPredictResult(x, y, False, 0.0, False)

        dt = now - self._last_time
        if dt < 1e-4 or dt > self.config.max_gap_sec:
            self._last_x, self._last_y, self._last_time = x, y, now
            self._vx = 0.0
            self._vy = 0.0
            self._speeds.clear()
            self._vx_hist.clear()
            self._vy_hist.clear()
            return LeadPredictResult(x, y, False, 0.0, False)

        raw_vx = (x - self._last_x) / dt
        raw_vy = (y - self._last_y) / dt
        alpha = self.config.ema_alpha
        self._vx = alpha * raw_vx + (1.0 - alpha) * self._vx
        self._vy = alpha * raw_vy + (1.0 - alpha) * self._vy

        speed = hypot(self._vx, self._vy)
        self._speeds.append(speed)
        self._vx_hist.append(self._vx)
        self._vy_hist.append(self._vy)
        stable = self._velocity_stable(speed)

        lead_x = 0.0
        lead_y = 0.0
        lead_applied = False
        if stable:
            lead_sec = max(0.0, self.config.lead_ms) / 1000.0
            lead_x = self._vx * lead_sec
            lead_y = self._vy * lead_sec
            lead_len = hypot(lead_x, lead_y)
            if lead_len > self.config.max_lead_px > 0:
                scale = self.config.max_lead_px / lead_len
                lead_x *= scale
                lead_y *= scale
            lead_applied = lead_len > 0.01

        self._last_x, self._last_y, self._last_time = x, y, now
        return LeadPredictResult(
            x + lead_x,
            y + lead_y,
            lead_applied,
            speed,
            stable,
        )
