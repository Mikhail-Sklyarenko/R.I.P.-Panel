"""Combat aim helpers: body fallback and smoothing selection."""

from __future__ import annotations

from typing import Callable, Optional

from aiming.target_selector import Target


def maybe_switch_to_body(
    target: Target,
    *,
    prioritize_heads: bool,
    dead_zone: float,
    body_fallback_sec: float,
    head_miss_since: Optional[float],
    now: float,
    select_body: Callable[[], Optional[Target]],
) -> tuple[Target, Optional[float], bool]:
    """
    If head aim fails to reach dead_zone for body_fallback_sec, switch to body.

    Returns (target, head_miss_since, switched).
    """
    if not prioritize_heads or not target.is_head:
        return target, None, False

    if target.distance <= dead_zone:
        return target, None, False

    if head_miss_since is None:
        return target, now, False

    if now - head_miss_since < body_fallback_sec:
        return target, head_miss_since, False

    body = select_body()
    if body is None:
        return target, head_miss_since, False

    return body, None, True
