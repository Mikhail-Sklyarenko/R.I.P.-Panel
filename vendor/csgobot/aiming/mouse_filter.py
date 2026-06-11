"""Clamp and filter relative mouse deltas."""

from __future__ import annotations


def filter_mouse_delta(
    dx: int,
    dy: int,
    *,
    max_delta: int = 35,
    min_delta: int = 2,
) -> tuple[int, int]:
    """Drop micro-moves and cap per-frame mouse step."""
    if abs(dx) + abs(dy) < max(0, min_delta):
        return 0, 0

    cap = max(1, max_delta)

    def _clamp(v: int) -> int:
        if v > cap:
            return cap
        if v < -cap:
            return -cap
        return v

    return _clamp(dx), _clamp(dy)
