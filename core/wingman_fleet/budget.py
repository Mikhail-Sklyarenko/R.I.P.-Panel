"""Bounded recovery: every automatic retry consumes a counted, windowed budget."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class WindowedCounter:
    limit: int
    window_sec: float
    events: deque = field(default_factory=deque)

    def _trim(self, now: float) -> None:
        while self.events and now - self.events[0] > self.window_sec:
            self.events.popleft()

    def remaining(self, now: float) -> int:
        self._trim(now)
        return max(0, self.limit - len(self.events))

    def try_consume(self, now: float) -> bool:
        if self.remaining(now) <= 0:
            return False
        self.events.append(now)
        return True

    def reset(self) -> None:
        self.events.clear()

    def snapshot(self) -> list[float]:
        return list(self.events)


class Budget:
    """Named counters; `reset_stage` clears per-stage attempts but keeps restart windows."""

    def __init__(self, limits: dict[str, tuple[int, float]]):
        self.counters = {name: WindowedCounter(limit, window) for name, (limit, window) in limits.items()}

    def try_consume(self, name: str, now: float) -> bool:
        return self.counters[name].try_consume(now)

    def remaining(self, name: str, now: float) -> int:
        return self.counters[name].remaining(now)

    def reset(self, *names: str) -> None:
        for name in names or tuple(self.counters):
            self.counters[name].reset()

    def to_state(self) -> dict[str, list[float]]:
        return {name: c.snapshot() for name, c in self.counters.items()}

    def load_state(self, state: dict[str, list[float]]) -> None:
        for name, values in (state or {}).items():
            if name in self.counters:
                self.counters[name].events = deque(float(v) for v in values)
