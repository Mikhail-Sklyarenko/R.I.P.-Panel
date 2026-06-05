"""Равномерный sleep по шагам сессии (по умолчанию 20 с)."""

from __future__ import annotations

import os
import time

_DEFAULT_SESSION_SECONDS = 20.0
_total_steps = 16


def session_seconds() -> float:
    return float(os.environ.get("FAKE_SESSION_SECONDS", str(_DEFAULT_SESSION_SECONDS)))


def reset_step_budget(total_steps: int = 16) -> None:
    global _total_steps
    _total_steps = max(1, total_steps)


def sleep_step() -> None:
    time.sleep(session_seconds() / _total_steps)


FAKE_SESSION_SECONDS = session_seconds()
