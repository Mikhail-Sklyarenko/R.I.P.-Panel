"""Brief visual dropout debounce; never authorizes firing without a detection."""
from dataclasses import dataclass


@dataclass
class CombatContact:
    grace_sec: float = 0.10
    last_seen: float | None = None
    acquired_at: float | None = None
    shot_reported: bool = False

    def update(self, *, detected: bool, active: bool, now: float) -> bool:
        if not active:
            self.last_seen = self.acquired_at = None
            self.shot_reported = False
            return False
        continuing = self.last_seen is not None and 0 <= now - self.last_seen <= self.grace_sec
        if detected:
            if not continuing:
                self.acquired_at = now
                self.shot_reported = False
            self.last_seen = now
            return True
        if continuing:
            return True
        self.last_seen = self.acquired_at = None
        self.shot_reported = False
        return False
