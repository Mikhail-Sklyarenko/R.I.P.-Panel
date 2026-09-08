"""Minimap goal navigation — place-localized path follow (no seed GPS)."""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from aiming.fov_mouse import FOVMouseMovement
from nav.coords import bearing_deg, dist_norm
from nav.humanize import NavHumanizer
from nav.pack import NavGoal, NavPack
from nav.planner import NavWaypoint, plan_path
from nav.pose import PoseResult
from nav.world_pose import YawTracker

KeyDownFn = Callable[[str], None]
KeyUpFn = Callable[[str], None]
MoveFn = Callable[[int, int], None]


class NavState(str, Enum):
    SEEK_ENTRY = "seek_entry"
    SEEK_GOAL = "seek_goal"
    AT_GOAL = "at_goal"
    STUCK_ESCAPE = "stuck_escape"
    MACRO_FALLBACK = "macro_fallback"
    PAUSED = "paused"
    WAIT_PLACE = "wait_place"


class NavPhase(str, Enum):
    ENTRY = "entry"
    GOAL = "goal"


@dataclass(frozen=True)
class NavTickResult:
    state: NavState
    use_macro_patrol: bool = False
    dist_to_goal: float = 0.0
    yaw_error_deg: float = 0.0
    pose_valid: bool = False
    goal_id: str = ""
    target_id: str = ""
    phase: str = ""
    stuck_event: bool = False
    fallback_event: bool = False
    entry_pick_event: bool = False
    goal_switch_event: bool = False
    humanize_micro_pause: bool = False
    humanize_look_yield: bool = False
    humanize_forward_jitter: bool = False
    forward_held: bool = False
    forward_fail_open: bool = False
    pose_mode: str = ""
    path: str = ""


def _is_map_pose(pose: PoseResult) -> bool:
    return pose.radar_mode == "world"


class NavController:
    """Seek pack goals using map-frame pose from place localization + path graph."""

    def __init__(
        self,
        pack: NavPack,
        fov_mouse: FOVMouseMovement,
        key_down: KeyDownFn,
        key_up: KeyUpFn,
        move_relative: MoveFn,
        *,
        logger: Optional[logging.Logger] = None,
        pose_lost_sec: float = 2.5,
        team: str = "any",
        yaw_tracker: Optional[YawTracker] = None,
    ) -> None:
        self._pack = pack
        self._fov = fov_mouse
        self._key_down = key_down
        self._key_up = key_up
        self._move = move_relative
        self._log = logger or logging.getLogger("CS2Bot.nav")
        self._pose_lost_sec = pose_lost_sec
        self._team = team.strip().lower() or "any"
        self._yaw = yaw_tracker or YawTracker()
        self._state = NavState.SEEK_GOAL
        self._phase = NavPhase.GOAL
        self._route_index = 0
        self._route_goal = self._current_route_goal()
        self._target: NavGoal = self._route_goal
        self._path_ids: tuple[str, ...] = ()
        self._path_goals: tuple[NavGoal, ...] = ()
        self._path_index = 0
        self._held_key: Optional[str] = None
        self._last_tick_at: Optional[float] = None
        self._last_progress_at = 0.0
        self._pose_lost_since: Optional[float] = None
        self._fallback_until = 0.0
        self._escape_until = 0.0
        self._escape_turn_remaining = 0.0
        self._escape_index = 0
        self._wander_until = 0.0
        self._wander_forward = False
        self._humanizer = NavHumanizer(pack.humanize)
        self._look_sweeping = False
        self._at_goal_since: Optional[float] = None
        self._last_pose: Optional[PoseResult] = None
        self._planned = False
        self._session_started_at: Optional[float] = None
        self._stuck_grace_sec = 6.0
        self._last_fail_open_log_at = 0.0
        self._flow_progress_until = 0.0
        self._announced = False
        self._place_wait_since: Optional[float] = None
        self._wps = self._load_waypoints()

    def _load_waypoints(self) -> tuple[NavWaypoint, ...]:
        out: list[NavWaypoint] = []
        for raw in self._pack.waypoints:
            out.append(
                NavWaypoint(
                    id=str(raw.get("id", "")),
                    x=float(raw.get("x", 0.5)),
                    y=float(raw.get("y", 0.5)),
                    arrive_radius=float(raw.get("arrive_radius", 0.055)),
                )
            )
        return tuple(wp for wp in out if wp.id)

    @property
    def state(self) -> NavState:
        return self._state

    @property
    def is_locomoting(self) -> bool:
        return self._state in (
            NavState.SEEK_ENTRY,
            NavState.SEEK_GOAL,
            NavState.STUCK_ESCAPE,
        )

    @property
    def goal_id(self) -> str:
        return self._route_goal.id

    @property
    def target_id(self) -> str:
        return self._target.id

    @property
    def last_pose(self) -> Optional[PoseResult]:
        return self._last_pose

    @property
    def yaw_tracker(self) -> YawTracker:
        return self._yaw

    def face_target(self) -> tuple[float, float]:
        return self._target.x, self._target.y

    def release_keys(self) -> None:
        if self._held_key is not None:
            self._key_up(self._held_key)
            self._held_key = None

    def reload_pack(self, pack: NavPack) -> None:
        self.release_keys()
        self._pack = pack
        self._humanizer = NavHumanizer(pack.humanize)
        self._wps = self._load_waypoints()
        self._yaw.reset()
        self._state = NavState.SEEK_GOAL
        self._phase = NavPhase.GOAL
        self._route_index = 0
        self._route_goal = self._current_route_goal()
        self._target = self._route_goal
        self._path_ids = ()
        self._path_goals = ()
        self._path_index = 0
        self._last_progress_at = 0.0
        self._pose_lost_since = None
        self._fallback_until = 0.0
        self._escape_until = 0.0
        self._escape_turn_remaining = 0.0
        self._at_goal_since = None
        self._planned = False
        self._session_started_at = None
        self._announced = False
        self._place_wait_since = None

    def _set_move_key(self, key: Optional[str]) -> None:
        if key == self._held_key:
            return
        if self._held_key is not None:
            self._key_up(self._held_key)
            self._held_key = None
        if key:
            self._key_down(key)
            self._held_key = key

    def _current_route_goal(self) -> NavGoal:
        goals = self._pack.goals
        if not goals:
            return self._pack.goal
        return goals[self._route_index % len(goals)]

    def _advance_route_goal(self, *, now: float) -> bool:
        goals = self._pack.goals
        if len(goals) <= 1 or self._pack.strategy != "route_cycle":
            return False
        prev = self._route_goal.id
        self._route_index = (self._route_index + 1) % len(goals)
        self._route_goal = self._current_route_goal()
        self._log.info("nav: route cycle %s -> %s", prev, self._route_goal.id)
        return True

    def _rebuild_path(self, pose: PoseResult) -> None:
        plan = plan_path(
            pose.x_norm,
            pose.y_norm,
            self._route_goal,
            self._wps,
            self._pack.edges,
        )
        self._path_ids = plan.waypoint_ids
        self._path_goals = plan.goals
        self._path_index = 0
        self._target = self._path_goals[0] if self._path_goals else self._route_goal
        self._phase = NavPhase.GOAL
        self._state = NavState.SEEK_GOAL
        path_s = ">".join(self._path_ids) or self._route_goal.id
        self._log.info(
            "nav: path %s (from %.2f,%.2f -> %s)",
            path_s,
            pose.x_norm,
            pose.y_norm,
            self._route_goal.id,
        )
        # Face next hop
        self._yaw.on_place(
            f"path:{path_s}",
            pose.x_norm,
            pose.y_norm,
            self._target.x,
            self._target.y,
        )

    def _path_label(self) -> str:
        return ">".join(self._path_ids) if self._path_ids else self._route_goal.id

    def _make_result(
        self,
        *,
        state: NavState,
        pose: PoseResult,
        dist: float,
        yaw_error: float = 0.0,
        use_macro_patrol: bool = False,
        stuck_event: bool = False,
        fallback_event: bool = False,
        goal_switch_event: bool = False,
        humanize_micro_pause: bool = False,
        humanize_look_yield: bool = False,
        humanize_forward_jitter: bool = False,
        forward_held: bool = False,
        forward_fail_open: bool = False,
    ) -> NavTickResult:
        return NavTickResult(
            state=state,
            use_macro_patrol=use_macro_patrol,
            dist_to_goal=dist,
            yaw_error_deg=yaw_error,
            pose_valid=pose.valid,
            goal_id=self._route_goal.id,
            target_id=self._target.id,
            phase=self._phase.value,
            stuck_event=stuck_event,
            fallback_event=fallback_event,
            goal_switch_event=goal_switch_event,
            humanize_micro_pause=humanize_micro_pause,
            humanize_look_yield=humanize_look_yield,
            humanize_forward_jitter=humanize_forward_jitter,
            forward_held=forward_held,
            forward_fail_open=forward_fail_open,
            pose_mode=pose.radar_mode if pose.valid else "none",
            path=self._path_label(),
        )

    def _enter_fallback(self, now: float) -> None:
        self.release_keys()
        self._state = NavState.MACRO_FALLBACK
        self._fallback_until = now + self._pack.fallback.macro_sec
        self._log.warning(
            "nav: macro fallback for %.0fs (script=%s)",
            self._pack.fallback.macro_sec,
            self._pack.fallback.macro_script,
        )

    def _start_escape(self, now: float) -> None:
        angles = self._pack.stuck.escape_angles_deg
        angle = angles[self._escape_index % len(angles)]
        self._escape_index += 1
        self._escape_turn_remaining = angle
        self._escape_until = now + max(0.85, self._pack.stuck.escape_duration_sec)
        self._state = NavState.STUCK_ESCAPE
        self.release_keys()
        self._log.info("nav: stuck escape thrust+rotate %.0f° (no radar flow)", angle)

    def tick(
        self,
        pose: PoseResult,
        *,
        now: float,
        paused: bool,
        team: str | None = None,
        look_sweeping: bool = False,
        radar_progressing: bool = False,
    ) -> NavTickResult:
        if team:
            self._team = team.strip().lower() or "any"
        self._look_sweeping = look_sweeping
        if self._last_tick_at is None:
            dt = 1.0 / 60.0
        else:
            dt = max(1.0 / 240.0, min(0.1, now - self._last_tick_at))
        self._last_tick_at = now

        if self._session_started_at is None and not paused:
            self._session_started_at = now

        if paused:
            self.release_keys()
            self._state = NavState.PAUSED
            result = self._make_result(
                state=self._state,
                pose=pose,
                dist=dist_norm(pose.x_norm, pose.y_norm, self._route_goal.x, self._route_goal.y)
                if pose.valid and _is_map_pose(pose)
                else 0.0,
            )
            self._last_pose = pose
            return result

        if radar_progressing:
            self._last_progress_at = now
            self._flow_progress_until = now + 0.7
        flow_now = radar_progressing or now < self._flow_progress_until

        if self._state == NavState.MACRO_FALLBACK:
            if now >= self._fallback_until:
                self._state = NavState.SEEK_GOAL
                self._planned = False
                self._pose_lost_since = None
                self._humanizer.reset()
                self._log.info("nav: fallback ended, resuming seek")
            else:
                result = self._make_result(
                    state=self._state, pose=pose, dist=0.0, use_macro_patrol=True,
                )
                self._last_pose = pose
                return result

        if not pose.valid:
            if self._pose_lost_since is None:
                self._pose_lost_since = now
            elif now - self._pose_lost_since >= self._pose_lost_sec:
                self._enter_fallback(now)
                result = self._make_result(
                    state=NavState.MACRO_FALLBACK,
                    pose=pose,
                    dist=0.0,
                    use_macro_patrol=True,
                    fallback_event=True,
                )
                self._last_pose = pose
                return result
            self.release_keys()
            result = self._make_result(state=self._state, pose=pose, dist=0.0)
            self._last_pose = pose
            return result

        self._pose_lost_since = None

        # Honest gate: need world place pose — no seed cosmetics.
        if not _is_map_pose(pose):
            self._place_wait_since = self._place_wait_since or now
            self.release_keys()
            self._state = NavState.WAIT_PLACE
            if now - self._place_wait_since >= 8.0:
                self._enter_fallback(now)
                result = self._make_result(
                    state=NavState.MACRO_FALLBACK,
                    pose=pose,
                    dist=0.0,
                    use_macro_patrol=True,
                    fallback_event=True,
                )
                self._place_wait_since = None
                self._last_pose = pose
                return result
            result = self._make_result(state=NavState.WAIT_PLACE, pose=pose, dist=0.0)
            self._last_pose = pose
            return result

        self._place_wait_since = None
        if not self._announced:
            self._log.info(
                "nav: place-localized goal-seek (goal=%s) — reading map labels",
                self._route_goal.id,
            )
            self._announced = True

        if not self._planned:
            self._route_goal = self._current_route_goal()
            self._rebuild_path(pose)
            self._planned = True
            self._last_progress_at = now
            self._at_goal_since = None
            self._humanizer.reset()

        # Advance along path hops
        while (
            self._path_goals
            and self._path_index < len(self._path_goals) - 1
            and dist_norm(
                pose.x_norm, pose.y_norm,
                self._path_goals[self._path_index].x,
                self._path_goals[self._path_index].y,
            )
            <= self._path_goals[self._path_index].arrive_radius
        ):
            self._path_index += 1
            self._target = self._path_goals[self._path_index]
            self._log.info("nav: hop -> %s", self._target.id)
            self._yaw.on_place(
                f"hop:{self._target.id}",
                pose.x_norm,
                pose.y_norm,
                self._target.x,
                self._target.y,
            )
            self._last_progress_at = now

        dist_goal = dist_norm(
            pose.x_norm, pose.y_norm, self._route_goal.x, self._route_goal.y,
        )
        dist_target = dist_norm(
            pose.x_norm, pose.y_norm, self._target.x, self._target.y,
        )

        # Refresh live pose yaw from tracker after face snaps
        if self._yaw.yaw_deg is not None:
            pose = PoseResult(
                x_norm=pose.x_norm,
                y_norm=pose.y_norm,
                yaw_deg=self._yaw.yaw_deg,
                confidence=pose.confidence,
                valid=True,
                blob_area_px=pose.blob_area_px,
                radar_mode="world",
            )

        if self._state == NavState.STUCK_ESCAPE:
            result = self._tick_escape(pose, now=now, dt=dt, dist_goal=dist_goal, flow=flow_now)
            self._last_pose = pose
            return result

        # Honest stuck: holding W but radar not scrolling
        grace = (
            self._session_started_at is not None
            and now - self._session_started_at < self._stuck_grace_sec
        )
        if (
            not grace
            and self._held_key == "w"
            and not flow_now
            and now - self._last_progress_at >= self._pack.stuck.progress_timeout_sec
        ):
            self._start_escape(now)
            result = self._make_result(
                state=NavState.STUCK_ESCAPE, pose=pose, dist=dist_goal, stuck_event=True,
            )
            self._last_pose = pose
            return result

        at_goal = dist_goal <= self._route_goal.arrive_radius
        if at_goal:
            self._state = NavState.AT_GOAL
            if self._at_goal_since is None:
                self._at_goal_since = now
        elif self._state == NavState.AT_GOAL:
            self._state = NavState.SEEK_GOAL
            self._at_goal_since = None

        if self._state == NavState.AT_GOAL:
            result = self._tick_at_goal(pose, now=now, dt=dt, dist=dist_goal, flow=flow_now)
            if (
                self._at_goal_since is not None
                and now - self._at_goal_since >= self._pack.route.dwell_at_goal_sec
            ):
                if self._advance_route_goal(now=now):
                    self._planned = False
                    self._at_goal_since = None
            self._last_pose = pose
            return result

        result = self._drive_toward_target(
            pose, now=now, dt=dt, dist=dist_goal, flow=flow_now,
        )
        self._last_pose = pose
        return result

    def _tick_escape(
        self,
        pose: PoseResult,
        *,
        now: float,
        dt: float,
        dist_goal: float,
        flow: bool,
    ) -> NavTickResult:
        yaw_delta = 0.0
        if now < self._escape_until:
            step = max(
                -self._pack.humanize.turn_rate_deg_per_sec * dt,
                min(self._pack.humanize.turn_rate_deg_per_sec * dt, self._escape_turn_remaining),
            )
            if abs(self._escape_turn_remaining) > 0.5:
                mx, _ = self._fov.angle_to_mouse(step, 0.0)
                if mx:
                    self._move(mx, 0)
                self._escape_turn_remaining -= step
                yaw_delta = step
            self._set_move_key("w")
            self._yaw.integrate(yaw_delta)
            return self._make_result(
                state=self._state, pose=pose, dist=dist_goal,
                yaw_error=self._escape_turn_remaining, forward_held=True,
            )
        self._state = NavState.SEEK_GOAL
        self._last_progress_at = now
        self.release_keys()
        self._planned = False  # replan after escape
        return self._make_result(state=self._state, pose=pose, dist=dist_goal)

    def _drive_toward_target(
        self,
        pose: PoseResult,
        *,
        now: float,
        dt: float,
        dist: float,
        flow: bool,
    ) -> NavTickResult:
        stalled = max(0.0, now - self._last_progress_at) if self._last_progress_at else 0.0
        force_crawl = stalled >= self._pack.humanize.forward_fail_open_after_sec
        if force_crawl and now - self._last_fail_open_log_at >= 5.0:
            self._log.info("nav: forward crawl fail-open stall=%.1fs", stalled)
            self._last_fail_open_log_at = now

        motion = self._humanizer.compute(
            pose,
            self._target,
            self._fov,
            dt_sec=dt,
            now=now,
            look_sweeping=self._look_sweeping,
            force_crawl=force_crawl,
            force_walk=False,
        )
        self._state = NavState.SEEK_GOAL
        if motion.paused:
            self.release_keys()
            return self._make_result(
                state=self._state, pose=pose, dist=dist,
                yaw_error=motion.yaw_error_deg,
                humanize_micro_pause=motion.micro_pause,
                forward_fail_open=force_crawl,
            )
        if motion.mouse_dx or motion.mouse_dy:
            self._move(motion.mouse_dx, motion.mouse_dy)
        if motion.forward:
            self._set_move_key("w")
        else:
            self.release_keys()
        self._yaw.integrate(float(motion.turn_step_deg))
        return self._make_result(
            state=self._state,
            pose=pose,
            dist=motion.dist_to_goal or dist,
            yaw_error=motion.yaw_error_deg,
            humanize_look_yield=motion.look_yield,
            humanize_forward_jitter=motion.forward_jitter,
            forward_held=bool(motion.forward),
            forward_fail_open=force_crawl,
        )

    def _tick_at_goal(
        self,
        pose: PoseResult,
        *,
        now: float,
        dt: float,
        dist: float,
        flow: bool,
    ) -> NavTickResult:
        yaw_delta = 0.0
        forward = False
        if now >= self._wander_until:
            self._wander_forward = random.random() > 0.4
            span = self._pack.at_goal.wander_sec_max - self._pack.at_goal.wander_sec_min
            self._wander_until = (
                now + self._pack.at_goal.wander_sec_min + random.random() * span
            )
        if self._wander_forward:
            motion = self._humanizer.compute(
                pose, self._route_goal, self._fov, dt_sec=dt, now=now,
                look_sweeping=self._look_sweeping, allow_forward=True,
            )
            if not motion.look_yield and motion.mouse_dx:
                self._move(motion.mouse_dx, 0)
            yaw_delta = float(motion.turn_step_deg)
            if motion.forward and not motion.paused:
                self._set_move_key("w")
                forward = True
            else:
                self.release_keys()
        else:
            if not self._look_sweeping:
                turn = random.choice([-1, 1]) * self._pack.humanize.turn_rate_deg_per_sec * dt
                mx, _ = self._fov.angle_to_mouse(turn, 0.0)
                if mx:
                    self._move(mx, 0)
                yaw_delta = turn
            self.release_keys()
        self._yaw.integrate(yaw_delta)
        return self._make_result(state=NavState.AT_GOAL, pose=pose, dist=dist, forward_held=forward)
