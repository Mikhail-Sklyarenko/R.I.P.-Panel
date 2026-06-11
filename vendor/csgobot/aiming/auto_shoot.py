"""Auto-shoot decision logic (testable without GPU/game)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiming.target_selector import Target
    from config import AimConfig


def should_auto_shoot(
    *,
    auto_shoot: bool,
    pixel_distance: float,
    shoot_dead_zone: float,
    confidence: float,
    is_head: bool,
    head_confidence: float,
    body_confidence: float,
    now: float,
    last_shot_time: float,
    shoot_cooldown_sec: float,
) -> bool:
    """
    Fire when crosshair is on target (inside shoot_dead_zone), confidence OK, cooldown elapsed.
    """
    if not auto_shoot:
        return False
    if pixel_distance > shoot_dead_zone:
        return False
    min_conf = head_confidence if is_head else body_confidence
    if confidence < min_conf:
        return False
    if now - last_shot_time < shoot_cooldown_sec:
        return False
    return True


def should_auto_shoot_target(
    aim_config: AimConfig,
    target: Target,
    pixel_distance: float,
    now: float,
    last_shot_time: float,
) -> bool:
    """Convenience wrapper using AimConfig + Target."""
    zone = getattr(aim_config, "shoot_dead_zone", None)
    if zone is None:
        zone = aim_config.dead_zone
    return should_auto_shoot(
        auto_shoot=aim_config.auto_shoot,
        pixel_distance=pixel_distance,
        shoot_dead_zone=float(zone),
        confidence=target.confidence,
        is_head=target.is_head,
        head_confidence=aim_config.head_confidence,
        body_confidence=aim_config.body_confidence,
        now=now,
        last_shot_time=last_shot_time,
        shoot_cooldown_sec=aim_config.shoot_cooldown_sec,
    )
