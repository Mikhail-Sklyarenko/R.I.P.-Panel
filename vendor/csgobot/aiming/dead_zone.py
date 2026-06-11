"""Hysteresis dead zones for aim movement vs shooting."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AimHysteresisConfig:
    high: float = 14.0
    low: float = 8.0


class AimHysteresis:
    """
    Aim mouse movement hysteresis.

    Start moving when dist > high; stop when dist < low; hold state between.
    """

    def __init__(self, config: AimHysteresisConfig | None = None) -> None:
        self.config = config or AimHysteresisConfig()
        self._moving = False

    def reset(self) -> None:
        self._moving = False

    def should_move(self, pixel_distance: float) -> bool:
        high = self.config.high
        low = min(self.config.low, high)

        if pixel_distance > high:
            self._moving = True
        elif pixel_distance < low:
            self._moving = False

        return self._moving
