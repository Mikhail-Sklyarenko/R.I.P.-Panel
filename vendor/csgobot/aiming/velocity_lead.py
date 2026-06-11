"""EMA velocity tracking and lead prediction for moving targets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LeadConfig:
    """Lead-aim parameters."""

    enabled: bool = True
    lead_ms: float = 80.0
    ema_alpha: float = 0.35
    max_lead_px: float = 120.0
    max_gap_sec: float = 0.5


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

    def reset(self) -> None:
        self._vx = 0.0
        self._vy = 0.0
        self._last_x = None
        self._last_y = None
        self._last_time = None

    def predict(self, x: float, y: float, now: float) -> tuple[float, float]:
        if not self.config.enabled:
            return x, y

        if self._last_time is None or self._last_x is None or self._last_y is None:
            self._last_x, self._last_y, self._last_time = x, y, now
            return x, y

        dt = now - self._last_time
        if dt < 1e-4 or dt > self.config.max_gap_sec:
            self._last_x, self._last_y, self._last_time = x, y, now
            self._vx = 0.0
            self._vy = 0.0
            return x, y

        raw_vx = (x - self._last_x) / dt
        raw_vy = (y - self._last_y) / dt
        alpha = self.config.ema_alpha
        self._vx = alpha * raw_vx + (1.0 - alpha) * self._vx
        self._vy = alpha * raw_vy + (1.0 - alpha) * self._vy

        lead_sec = max(0.0, self.config.lead_ms) / 1000.0
        lead_x = self._vx * lead_sec
        lead_y = self._vy * lead_sec
        lead_len = (lead_x**2 + lead_y**2) ** 0.5
        if lead_len > self.config.max_lead_px > 0:
            scale = self.config.max_lead_px / lead_len
            lead_x *= scale
            lead_y *= scale

        self._last_x, self._last_y, self._last_time = x, y, now
        return x + lead_x, y + lead_y
