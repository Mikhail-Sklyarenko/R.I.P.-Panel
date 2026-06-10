"""Execute relative WASD patrol steps (hold key for N seconds)."""

from __future__ import annotations

from typing import Callable, Optional

from .schema import PatrolScript

KeyFn = Callable[[str], None]


class PatrolRunner:
    def __init__(
        self,
        script: PatrolScript,
        key_down: KeyFn,
        key_up: KeyFn,
    ) -> None:
        self._script = script
        self._key_down = key_down
        self._key_up = key_up
        self._step_index = 0
        self._step_started_at: Optional[float] = None
        self._current_key: Optional[str] = None
        self._paused = False

    @property
    def step_index(self) -> int:
        return self._step_index

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def current_key(self) -> Optional[str]:
        return self._current_key

    def release_all_keys(self) -> None:
        if self._current_key is not None:
            self._key_up(self._current_key)
            self._current_key = None
        self._step_started_at = None

    def pause(self) -> None:
        self._paused = True
        self.release_all_keys()

    def resume(self) -> None:
        self._paused = False
        self._step_started_at = None

    def reset(self) -> None:
        self.release_all_keys()
        self._step_index = 0
        self._paused = False

    def _start_step(self, now: float) -> None:
        if self._step_index >= len(self._script.steps):
            return
        step = self._script.steps[self._step_index]
        self._current_key = step.key
        self._step_started_at = now
        self._key_down(step.key)

    def _finish_step(self) -> None:
        if self._current_key is not None:
            self._key_up(self._current_key)
            self._current_key = None
        self._step_started_at = None
        self._step_index += 1
        if self._step_index >= len(self._script.steps):
            if self._script.loop:
                self._step_index = 0
            else:
                self._step_index = len(self._script.steps) - 1

    def tick(self, now: float) -> None:
        if self._paused or not self._script.steps:
            return
        if self._step_index >= len(self._script.steps) and not self._script.loop:
            return

        if self._step_started_at is None:
            self._start_step(now)
            return

        step = self._script.steps[self._step_index]
        if now - self._step_started_at >= step.sec:
            self._finish_step()
            if not self._paused and self._script.steps:
                if self._script.loop or self._step_index < len(self._script.steps):
                    self._start_step(now)
