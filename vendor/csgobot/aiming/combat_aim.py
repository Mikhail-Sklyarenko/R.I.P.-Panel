"""Combat aim helpers: body fallback and smoothing selection."""

from __future__ import annotations

from typing import Callable, Optional

from aiming.target_selector import Target


def maybe_switch_to_body(
    target: Target,
    *,
    prioritize_heads: bool,
    aim_dead_zone_high: float,
    body_fallback_sec: float,
    head_miss_since: Optional[float],
    now: float,
    select_body: Callable[[], Optional[Target]],
) -> tuple[Target, Optional[float], bool]:
    """
    If head aim fails to reach aim_dead_zone_high for body_fallback_sec, switch to body.

    Returns (target, head_miss_since, switched).
    """
    if not prioritize_heads or not target.is_head:
        return target, None, False

    if target.distance <= aim_dead_zone_high:
        return target, None, False

    if head_miss_since is None:
        return target, now, False

    if now - head_miss_since < body_fallback_sec:
        return target, head_miss_since, False

    body = select_body()
    if body is None:
        return target, head_miss_since, False

    return body, None, True


def observed_fire_distance(target, *, center_x, center_y, captured_at, now, project=None):
    """Use fresh measured geometry for firing; smoothing is mouse guidance only."""
    from math import hypot, inf
    if not 0 <= now - captured_at <= 0.25:
        return inf
    x, y = target.aim_x, target.aim_y
    if project is not None:
        x, y = project(x, y, captured_at)
    return hypot(x - center_x, y - center_y)


def precise_fire_distance(target, *, center_x, center_y, captured_at, now, project=None):
    """Wingman: require the crosshair in a size-bounded central aim region.

    A detection box is not a silhouette. This gate prevents the former 24px
    permission from accepting empty space beside a small target; it does not
    infer visibility behind cover or compensate unknown mouse calibration.
    """
    from math import hypot, inf, isfinite
    if not 0 <= now-captured_at <= .25:
        return inf
    values = (target.x1, target.y1, target.x2, target.y2, target.aim_x, target.aim_y)
    if not all(isfinite(v) for v in values) or target.width <= 0 or target.height <= 0:
        return inf
    x, y = target.aim_x, target.aim_y
    x1, y1, x2, y2 = target.xyxy
    if project is not None:
        x, y = project(x, y, captured_at)
        x1, y1 = project(x1, y1, captured_at)
        x2, y2 = project(x2, y2, captured_at)
    if not all(isfinite(v) for v in (x,y,x1,y1,x2,y2)) or x2 <= x1 or y2 <= y1:
        return inf
    # Small heads get a small gate; close bodies still cannot accept shoulders.
    cap = 5. if target.is_head else 8.
    rx = min(cap, (x2-x1)*.20)
    ry = min(cap, (y2-y1)*(.20 if target.is_head else .10))
    dx, dy = x-center_x, y-center_y
    if (dx/rx)**2 + (dy/ry)**2 > 1.:
        return inf
    return hypot(dx,dy)
