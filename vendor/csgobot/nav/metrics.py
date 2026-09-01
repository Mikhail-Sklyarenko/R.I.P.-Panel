"""Navigation soak telemetry (PR-N3)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from nav.controller import NavState, NavTickResult
from nav.pose import PoseResult


@dataclass
class NavMetrics:
    """Accumulate nav session stats and emit periodic JSON summaries."""

    log_interval_sec: float = 30.0
    _session_start: float = 0.0
    _last_log_at: float = 0.0
    _last_pose: PoseResult | None = None
    _state_seconds: dict[str, float] = field(default_factory=dict)
    _stuck_events: int = 0
    _fallback_count: int = 0
    _entry_picks: int = 0
    _goal_switches: int = 0
    _micro_pauses: int = 0
    _look_yields: int = 0
    _forward_jitters: int = 0
    _pose_valid_ticks: int = 0
    _pose_total_ticks: int = 0
    _dist_sum: float = 0.0
    _dist_samples: int = 0
    _last_goal_id: str = ""
    _last_target_id: str = ""
    _pack_id: str = ""

    def set_pack_id(self, pack_id: str) -> None:
        self._pack_id = pack_id.strip()

    def start(self, now: float) -> None:
        self._session_start = now
        self._last_log_at = now

    def observe_tick(
        self,
        result: NavTickResult,
        pose: PoseResult,
        *,
        now: float,
        dt: float,
        goal_id: str,
        target_id: str,
    ) -> None:
        if self._session_start <= 0.0:
            self.start(now)

        state_key = result.state.value
        self._state_seconds[state_key] = (
            self._state_seconds.get(state_key, 0.0) + max(dt, 0.0)
        )

        self._pose_total_ticks += 1
        if pose.valid:
            self._pose_valid_ticks += 1

        if result.dist_to_goal > 0.0:
            self._dist_sum += result.dist_to_goal
            self._dist_samples += 1

        if result.stuck_event:
            self._stuck_events += 1
        if result.fallback_event:
            self._fallback_count += 1
        if result.entry_pick_event:
            self._entry_picks += 1
        if result.goal_switch_event:
            self._goal_switches += 1
        if result.humanize_micro_pause:
            self._micro_pauses += 1
        if result.humanize_look_yield:
            self._look_yields += 1
        if result.humanize_forward_jitter:
            self._forward_jitters += 1

        if goal_id:
            self._last_goal_id = goal_id
        if target_id:
            self._last_target_id = target_id
        self._last_pose = pose

    def summary(self, now: float) -> dict[str, Any]:
        uptime = max(0.0, now - self._session_start)
        at_goal_sec = self._state_seconds.get(NavState.AT_GOAL.value, 0.0)
        seek_sec = self._state_seconds.get(NavState.SEEK_GOAL.value, 0.0)
        seek_entry_sec = self._state_seconds.get(NavState.SEEK_ENTRY.value, 0.0)
        fallback_sec = self._state_seconds.get(NavState.MACRO_FALLBACK.value, 0.0)
        nav_active_sec = max(0.0, uptime - fallback_sec)
        pose_valid_pct = (
            100.0 * self._pose_valid_ticks / self._pose_total_ticks
            if self._pose_total_ticks
            else 0.0
        )
        avg_dist = (
            self._dist_sum / self._dist_samples if self._dist_samples else 0.0
        )
        time_at_goal_pct = (
            100.0 * at_goal_sec / nav_active_sec if nav_active_sec > 0.0 else 0.0
        )

        pose_xy = None
        if self._last_pose is not None and self._last_pose.valid:
            pose_xy = [round(self._last_pose.x_norm, 3), round(self._last_pose.y_norm, 3)]

        return {
            "uptime_sec": round(uptime, 1),
            "pack_id": self._pack_id or None,
            "state": self._last_target_id or self._last_goal_id or "?",
            "goal_id": self._last_goal_id,
            "target_id": self._last_target_id,
            "pose": pose_xy,
            "goal_dist": round(avg_dist, 3),
            "pose_valid_pct": round(pose_valid_pct, 1),
            "time_at_goal_pct": round(time_at_goal_pct, 1),
            "seek_sec": round(seek_sec + seek_entry_sec, 1),
            "fallback_sec": round(fallback_sec, 1),
            "stuck_events": self._stuck_events,
            "fallback_count": self._fallback_count,
            "entry_picks": self._entry_picks,
            "goal_switches": self._goal_switches,
            "micro_pauses": self._micro_pauses,
            "look_yields": self._look_yields,
            "forward_jitters": self._forward_jitters,
        }

    def maybe_log(
        self,
        now: float,
        logger: logging.Logger,
        *,
        force: bool = False,
    ) -> dict[str, Any] | None:
        if self._session_start <= 0.0:
            return None
        if not force and now - self._last_log_at < self.log_interval_sec:
            return None
        payload = self.summary(now)
        logger.info("nav_metrics: %s", json.dumps(payload, separators=(",", ":")))
        self._last_log_at = now
        return payload
