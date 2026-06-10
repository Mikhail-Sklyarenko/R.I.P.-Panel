"""Timed unstuck key sequence: jump, back, strafe."""

from __future__ import annotations

import random
from enum import Enum, auto
from typing import Callable, Optional

PressFn = Callable[[str], None]
KeyDownFn = Callable[[str], None]
KeyUpFn = Callable[[str], None]


class _Phase(Enum):
    IDLE = auto()
    JUMP = auto()
    BACK = auto()
    STRAFE = auto()


class UnstuckSequence:
    def __init__(
        self,
        press: PressFn,
        key_down: KeyDownFn,
        key_up: KeyUpFn,
        back_sec: float = 0.5,
        strafe_min_sec: float = 1.0,
        strafe_max_sec: float = 2.0,
    ) -> None:
        self._press = press
        self._key_down = key_down
        self._key_up = key_up
        self._back_sec = back_sec
        self._strafe_min_sec = strafe_min_sec
        self._strafe_max_sec = strafe_max_sec
        self._phase = _Phase.IDLE
        self._phase_started_at: float = 0.0
        self._strafe_key: Optional[str] = None
        self._strafe_duration: float = 0.0
        self._hold_key: Optional[str] = None

    @property
    def is_running(self) -> bool:
        return self._phase != _Phase.IDLE

    def _release_hold(self) -> None:
        if self._hold_key is not None:
            self._key_up(self._hold_key)
            self._hold_key = None

    def abort(self) -> None:
        self._release_hold()
        self._phase = _Phase.IDLE
        self._strafe_key = None

    def start(self, now: float) -> None:
        self.abort()
        self._phase = _Phase.JUMP
        self._phase_started_at = now
        self._press("space")

    def tick(self, now: float) -> bool:
        if self._phase == _Phase.IDLE:
            return False

        elapsed = now - self._phase_started_at

        if self._phase == _Phase.JUMP:
            self._phase = _Phase.BACK
            self._phase_started_at = now
            self._hold_key = "s"
            self._key_down("s")
            return True

        if self._phase == _Phase.BACK:
            if elapsed < self._back_sec:
                return True
            self._release_hold()
            self._phase = _Phase.STRAFE
            self._phase_started_at = now
            self._strafe_key = random.choice(["a", "d"])
            self._strafe_duration = random.uniform(
                self._strafe_min_sec, self._strafe_max_sec,
            )
            self._hold_key = self._strafe_key
            self._key_down(self._strafe_key)
            return True

        if self._phase == _Phase.STRAFE:
            if elapsed < self._strafe_duration:
                return True
            self._release_hold()
            self._phase = _Phase.IDLE
            self._strafe_key = None
            return False

        return False
