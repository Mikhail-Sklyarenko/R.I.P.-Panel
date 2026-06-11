"""Burst, hold, and tap fire control for DM auto-shoot."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from config import AimConfig

ShootMode = Literal["tap", "burst", "hold"]


@dataclass
class FireConfig:
    enabled: bool = True
    mode: ShootMode = "hold"
    shoot_dead_zone: float = 18.0
    head_confidence: float = 0.65
    body_confidence: float = 0.55
    shoot_cooldown_sec: float = 0.07
    burst_size: int = 5
    burst_shot_interval_sec: float = 0.07
    burst_gap_sec: float = 0.15
    hold_max_sec: float = 0.4
    hold_release_grace_sec: float = 0.1
    humanize_jitter_sec: float = 0.02


@dataclass
class FireAction:
    click: bool = False
    press: bool = False
    release: bool = False
    fired: bool = False
    holding: bool = False
    mode: str = ""


def target_in_shoot_zone(
    *,
    pixel_distance: float,
    shoot_dead_zone: float,
    confidence: float,
    is_head: bool,
    head_confidence: float,
    body_confidence: float,
) -> bool:
    if pixel_distance > shoot_dead_zone:
        return False
    min_conf = head_confidence if is_head else body_confidence
    return confidence >= min_conf


class FireController:
    """State machine for tap / burst / hold LMB."""

    def __init__(self, config: FireConfig) -> None:
        self.config = config
        self._holding = False
        self._last_shot_time = -1.0
        self._burst_shots = 0
        self._burst_active = False
        self._next_fire_allowed = 0.0
        self._hold_until = 0.0
        self._off_target_since: float | None = None

    @classmethod
    def from_aim_config(cls, aim: AimConfig) -> FireController:
        mode = getattr(aim, "shoot_mode", "hold")
        zone = getattr(aim, "shoot_dead_zone", aim.dead_zone)
        return cls(
            FireConfig(
                enabled=aim.auto_shoot,
                mode=mode,  # type: ignore[arg-type]
                shoot_dead_zone=float(zone),
                head_confidence=aim.head_confidence,
                body_confidence=aim.body_confidence,
                shoot_cooldown_sec=aim.shoot_cooldown_sec,
                burst_size=int(getattr(aim, "burst_size", 5)),
                burst_shot_interval_sec=float(
                    getattr(aim, "burst_shot_interval_sec", 0.07)
                ),
                burst_gap_sec=float(getattr(aim, "burst_gap_sec", 0.15)),
                hold_max_sec=float(getattr(aim, "hold_max_sec", 0.4)),
                hold_release_grace_sec=float(
                    getattr(aim, "hold_release_grace_sec", 0.1)
                ),
                humanize_jitter_sec=float(
                    getattr(aim, "shoot_humanize_jitter_sec", 0.02)
                ),
            )
        )

    @property
    def is_holding(self) -> bool:
        return self._holding

    def reset(self) -> FireAction:
        return self.force_release(0.0)

    def _jitter(self) -> float:
        j = self.config.humanize_jitter_sec
        if j <= 0:
            return 0.0
        return random.uniform(-j, j)

    def _schedule_gap(self, now: float, gap_sec: float) -> None:
        self._next_fire_allowed = now + max(0.0, gap_sec + self._jitter())

    def force_release(self, now: float) -> FireAction:
        self._burst_active = False
        self._burst_shots = 0
        self._off_target_since = None
        self._hold_until = 0.0
        if not self._holding:
            return FireAction(mode=self.config.mode)
        self._holding = False
        self._schedule_gap(now, self.config.burst_gap_sec)
        return FireAction(release=True, fired=True, holding=False, mode=self.config.mode)

    def tick(
        self,
        *,
        pixel_distance: float,
        confidence: float,
        is_head: bool,
        now: float,
    ) -> FireAction:
        if not self.config.enabled:
            return self.force_release(now)

        on_target = target_in_shoot_zone(
            pixel_distance=pixel_distance,
            shoot_dead_zone=self.config.shoot_dead_zone,
            confidence=confidence,
            is_head=is_head,
            head_confidence=self.config.head_confidence,
            body_confidence=self.config.body_confidence,
        )

        if not on_target:
            if self._holding:
                if self._off_target_since is None:
                    self._off_target_since = now
                elif now - self._off_target_since >= self.config.hold_release_grace_sec:
                    return self.force_release(now)
            else:
                self._off_target_since = None
            return self._tick_burst_off_target(now)

        self._off_target_since = None

        if self._holding:
            if now >= self._hold_until:
                return self.force_release(now)
            return FireAction(holding=True, mode="hold")

        mode = self.config.mode
        if mode == "hold":
            return self._start_hold(now)
        if mode == "burst":
            return self._tick_burst_on_target(now)
        return self._tick_tap(now)

    def _start_hold(self, now: float) -> FireAction:
        if now < self._next_fire_allowed:
            return FireAction(mode="hold")
        self._holding = True
        self._hold_until = now + self.config.hold_max_sec
        self._last_shot_time = now
        return FireAction(press=True, fired=True, holding=True, mode="hold")

    def _tick_tap(self, now: float) -> FireAction:
        if now < self._next_fire_allowed:
            return FireAction(mode="tap")
        if (
            self._last_shot_time >= 0
            and now - self._last_shot_time < self.config.shoot_cooldown_sec
        ):
            return FireAction(mode="tap")
        self._last_shot_time = now
        self._schedule_gap(now, self.config.shoot_cooldown_sec)
        return FireAction(click=True, fired=True, mode="tap")

    def _tick_burst_on_target(self, now: float) -> FireAction:
        if self._burst_active:
            if now - self._last_shot_time < self.config.burst_shot_interval_sec:
                return FireAction(mode="burst")
            self._last_shot_time = now
            self._burst_shots += 1
            if self._burst_shots >= self.config.burst_size:
                self._burst_active = False
                self._burst_shots = 0
                self._schedule_gap(now, self.config.burst_gap_sec)
            return FireAction(click=True, fired=True, mode="burst")

        if now < self._next_fire_allowed:
            return FireAction(mode="burst")

        self._burst_active = True
        self._burst_shots = 1
        self._last_shot_time = now
        return FireAction(click=True, fired=True, mode="burst")

    def _tick_burst_off_target(self, now: float) -> FireAction:
        if self._burst_active:
            self._burst_active = False
            self._burst_shots = 0
            self._schedule_gap(now, self.config.burst_gap_sec)
        return FireAction(mode=self.config.mode)
