"""Fake modules для test_mode: sleep + emit, ~20s до DONE."""

from modules._fakes.timing import (
    FAKE_SESSION_SECONDS,
    reset_step_budget,
    session_seconds,
    sleep_step,
)

__all__ = [
    "FAKE_SESSION_SECONDS",
    "reset_step_budget",
    "session_seconds",
    "sleep_step",
]
