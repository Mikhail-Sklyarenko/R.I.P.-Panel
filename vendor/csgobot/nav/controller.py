"""Product locomotion: corridor scripts + Safe-W (no blind wall running).

Contract:
- Place label picks a corridor script (face landmark → short W burst).
- W only with radar flow, fresh place, or an armed walk burst — never fail-open
  crawl into walls.
- Hard wall-stop: no flow while W → release W and turn (no thrust into wall).
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from aiming.fov_mouse import FOVMouseMovement
from nav.coords import bearing_deg, dist_norm
from nav.corridor import (
    CorridorScript,
    CorridorStep,
    build_edge_neighbors,
    pick_corridor,
)
from nav.humanize import NavHumanizer
from nav.pack import NavGoal, NavPack
from nav.planner import NavWaypoint, plan_path
from nav.pose import PoseResult
from nav.world_pose import YawTracker

KeyDownFn = Callable[[str], None]
KeyUpFn = Callable[[str], None]
MoveFn = Callable[[int, int], None]

# Product Safe-W / wall-stop (FermK: blind W = run into wall).
_WALK_BURST_SEC = 1.35
_WALL_NO_FLOW_SEC = 1.15
_WALL_COOLDOWN_SEC = 0.85
_WALL_TURN_DEG = 95.0


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
    """Corridor-script seek with Safe-W — standing > running into walls."""

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
        place_wait_sec: float = 12.0,
        allow_macro_fallback: bool = True,
    ) -> None:
        self._pack = pack
        self._fov = fov_mouse
        self._key_down = key_down
        self._key_up = key_up
        self._move = move_relative
        self._log = logger or logging.getLogger("CS2Bot.nav")
        self._pose_lost_sec = pose_lost_sec
        self._place_wait_sec = max(2.0, float(place_wait_sec))
        self._allow_macro = bool(allow_macro_fallback)
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
        self._stuck_grace_sec = 4.0
        self._last_fail_open_log_at = 0.0
        self._flow_progress_until = 0.0
        self._announced = False
        self._place_wait_since: Optional[float] = None
        self._locked_place_id: Optional[str] = None
        self._place_unchanged_since: Optional[float] = None
        self._script: Optional[CorridorScript] = None
        self._step_index = 0
        self._step_started_at = 0.0
        self._walk_burst_until = 0.0
        self._wall_cooldown_until = 0.0
        self._no_flow_while_w_since: Optional[float] = None
        self._step_saw_flow = False
        self._last_safe_log_at = 0.0
        self._wps = self._load_waypoints()
        self._wp_by_id = {wp.id: wp for wp in self._wps}
        self._neighbors = build_edge_neighbors(tuple(pack.edges))

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
    def suppresses_look(self) -> bool:
        return self._state in (
            NavState.SEEK_ENTRY,
            NavState.SEEK_GOAL,
            NavState.STUCK_ESCAPE,
            NavState.WAIT_PLACE,
            NavState.PAUSED,
            NavState.AT_GOAL,
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

    @property
    def edge_neighbors(self) -> dict[str, set[str]]:
        return self._neighbors

    def face_target(self) -> tuple[float, float]:
        return self._target.x, self._target.y

    @property
    def path_label(self) -> str:
        return self._path_label()

    def release_keys(self) -> None:
        if self._held_key is not None:
            self._key_up(self._held_key)
            self._held_key = None

    def reload_pack(self, pack: NavPack) -> None:
        self.release_keys()
        self._pack = pack
        self._humanizer = NavHumanizer(pack.humanize)
        self._wps = self._load_waypoints()
        self._wp_by_id = {wp.id: wp for wp in self._wps}
        self._neighbors = build_edge_neighbors(tuple(pack.edges))
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
        self._locked_place_id = None
        self._place_unchanged_since = None
        self._script = None
        self._step_index = 0
        self._step_started_at = 0.0
        self._walk_burst_until = 0.0
        self._wall_cooldown_until = 0.0
        self._no_flow_while_w_since = None
        self._step_saw_flow = False

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
        self._script = None
        self._planned = False
        self._log.info("nav: route cycle %s -> %s", prev, self._route_goal.id)
        return True

    def _goal_from_wp(self, wp_id: str) -> NavGoal:
        wp = self._wp_by_id.get(wp_id)
        if wp is None:
            return self._route_goal
        return NavGoal(wp.id, wp.x, wp.y, wp.arrive_radius)

    def _path_label(self) -> str:
        if self._script is not None:
            faces = [s.face_id for s in self._script.steps]
            return f"{self._script.id}:{'/'.join(faces)}"
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
            pose_mode=pose.radar_mode if pose.valid else "",
            path=self._path_label(),
        )

    def _enter_fallback(self, now: float) -> bool:
        if not self._allow_macro:
            self._state = NavState.WAIT_PLACE
            self.release_keys()
            return False
        self._state = NavState.MACRO_FALLBACK
        self._fallback_until = now + max(2.0, float(self._pack.fallback.macro_sec))
        self.release_keys()
        self._log.info(
            "nav: macro_fallback %s for %.1fs",
            self._pack.fallback.macro_script,
            self._fallback_until - now,
        )
        return True

    def _abort_fallback_for_world(self, now: float) -> None:
        self._state = NavState.SEEK_GOAL
        self._fallback_until = 0.0
        self._planned = False
        self._place_wait_since = None
        self._log.info("nav: world pose — abort macro, resume corridor seek")

    def _arm_walk_burst(self, now: float) -> None:
        self._walk_burst_until = now + _WALK_BURST_SEC

    def _safe_w_allowed(self, *, now: float, flow: bool) -> bool:
        """Product Safe-W: never hold W without evidence of motion or a short burst."""
        if now < self._wall_cooldown_until:
            return False
        if flow:
            return True
        if now < self._walk_burst_until:
            return True
        return False

    def _start_wall_stop(self, now: float) -> None:
        """Hard wall-stop: release W, turn, cooldown — do not thrust into wall."""
        self.release_keys()
        self._no_flow_while_w_since = None
        self._walk_burst_until = 0.0
        self._wall_cooldown_until = now + _WALL_COOLDOWN_SEC
        self._state = NavState.STUCK_ESCAPE
        self._escape_until = now + max(0.55, _WALL_COOLDOWN_SEC * 0.7)
        sign = -1.0 if self._escape_index % 2 else 1.0
        self._escape_index += 1
        self._escape_turn_remaining = sign * _WALL_TURN_DEG
        self._log.info(
            "nav: wall-stop turn %.0f° (no radar flow while W)",
            self._escape_turn_remaining,
        )

    def _current_step(self) -> Optional[CorridorStep]:
        if self._script is None:
            return None
        if self._step_index >= len(self._script.steps):
            return None
        return self._script.steps[self._step_index]

    def _start_script(self, script: CorridorScript, place_id: str, now: float) -> None:
        self._script = script
        self._step_index = 0
        self._step_started_at = now
        self._step_saw_flow = False
        self._planned = True
        self._arm_walk_burst(now)
        step = script.steps[0]
        self._target = self._goal_from_wp(step.face_id)
        self._path_ids = tuple(s.face_id for s in script.steps) + (script.goal_id,)
        self._log.info(
            "nav: corridor %s place=%s → %s (steps=%d)",
            script.id,
            place_id,
            script.goal_id,
            len(script.steps),
        )
        self._yaw.on_place(
            f"corridor:{script.id}",
            self._last_pose.x_norm if self._last_pose else 0.5,
            self._last_pose.y_norm if self._last_pose else 0.5,
            self._target.x,
            self._target.y,
        )

    def _sync_corridor(self, pose: PoseResult, *, now: float) -> None:
        pid = (pose.place_id or "").strip() or None
        place_changed = pid != self._locked_place_id
        if place_changed:
            self._locked_place_id = pid
            self._place_unchanged_since = now
            if pid:
                self._last_progress_at = now
                self._arm_walk_burst(now)
        elif self._place_unchanged_since is None:
            self._place_unchanged_since = now

        if not pid:
            return

        if pid == self._route_goal.id:
            return

        script = pick_corridor(pid, self._route_goal.id)
        if script is None:
            return

        if self._script is None or self._script.id != script.id:
            self._start_script(script, pid, now)
            return

        step = self._current_step()
        if step is None:
            return
        if pid in step.advance_places:
            if self._step_index < len(self._script.steps) - 1:
                self._step_index += 1
                self._step_started_at = now
                self._step_saw_flow = False
                self._arm_walk_burst(now)
                nxt = self._script.steps[self._step_index]
                self._target = self._goal_from_wp(nxt.face_id)
                self._log.info(
                    "nav: corridor hop -> %s (place=%s)",
                    nxt.face_id,
                    pid,
                )
                self._yaw.on_place(
                    f"hop:{nxt.face_id}",
                    pose.x_norm,
                    pose.y_norm,
                    self._target.x,
                    self._target.y,
                )
            else:
                # Last step place reached toward goal
                if pid == self._script.goal_id or pid in step.advance_places:
                    pass

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
            self._step_saw_flow = True
            self._no_flow_while_w_since = None
        flow_now = radar_progressing or now < self._flow_progress_until

        if self._state == NavState.MACRO_FALLBACK:
            if pose.valid and _is_map_pose(pose):
                self._abort_fallback_for_world(now)
            elif now >= self._fallback_until:
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
                entered = self._enter_fallback(now)
                result = self._make_result(
                    state=self._state,
                    pose=pose,
                    dist=0.0,
                    use_macro_patrol=entered,
                    fallback_event=entered,
                )
                self._last_pose = pose
                return result
            self.release_keys()
            result = self._make_result(state=self._state, pose=pose, dist=0.0)
            self._last_pose = pose
            return result

        self._pose_lost_since = None

        if not _is_map_pose(pose):
            self._place_wait_since = self._place_wait_since or now
            self.release_keys()
            self._state = NavState.WAIT_PLACE
            if now - self._place_wait_since >= self._place_wait_sec:
                entered = self._enter_fallback(now)
                if entered:
                    self._place_wait_since = None
                result = self._make_result(
                    state=self._state,
                    pose=pose,
                    dist=0.0,
                    use_macro_patrol=entered,
                    fallback_event=entered,
                )
                self._last_pose = pose
                return result
            result = self._make_result(state=NavState.WAIT_PLACE, pose=pose, dist=0.0)
            self._last_pose = pose
            return result

        self._place_wait_since = None
        if not self._announced:
            self._log.info(
                "nav: place-localized corridor seek (goal=%s)",
                self._route_goal.id,
            )
            self._announced = True

        self._last_pose = pose
        self._sync_corridor(pose, now=now)

        if self._script is None:
            # Fallback geometric plan only for face target; Safe-W still applies.
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
            self._planned = True
            self._arm_walk_burst(now)
            self._log.info(
                "nav: corridor miss — face path %s",
                ">".join(self._path_ids) or self._route_goal.id,
            )

        dist_goal = dist_norm(
            pose.x_norm, pose.y_norm, self._route_goal.x, self._route_goal.y,
        )

        if self._yaw.yaw_deg is not None:
            pose = PoseResult(
                x_norm=pose.x_norm,
                y_norm=pose.y_norm,
                yaw_deg=self._yaw.yaw_deg,
                confidence=pose.confidence,
                valid=True,
                blob_area_px=pose.blob_area_px,
                radar_mode="world",
                place_id=pose.place_id,
            )

        # Hard wall-stop while holding W without flow
        if self._held_key == "w" and not flow_now:
            if self._no_flow_while_w_since is None:
                self._no_flow_while_w_since = now
            elif now - self._no_flow_while_w_since >= _WALL_NO_FLOW_SEC:
                self._start_wall_stop(now)
        elif flow_now or self._held_key != "w":
            if flow_now:
                self._no_flow_while_w_since = None

        if self._state == NavState.STUCK_ESCAPE:
            result = self._tick_escape(pose, now=now, dt=dt, dist_goal=dist_goal)
            self._last_pose = pose
            return result

        # Step timeout advance (only if we saw some flow this step — real motion)
        step = self._current_step()
        if (
            self._script is not None
            and step is not None
            and now - self._step_started_at >= step.walk_sec
        ):
            if self._step_saw_flow and self._step_index < len(self._script.steps) - 1:
                self._step_index += 1
                self._step_started_at = now
                self._step_saw_flow = False
                self._arm_walk_burst(now)
                nxt = self._script.steps[self._step_index]
                self._target = self._goal_from_wp(nxt.face_id)
                self._log.info("nav: corridor hop -> %s (timeout+flow)", nxt.face_id)
            elif not self._step_saw_flow and now - self._step_started_at >= step.walk_sec:
                # Walked with no flow — wall-stop rather than push harder
                if self._held_key == "w" or now >= self._walk_burst_until:
                    self._start_wall_stop(now)
                    result = self._make_result(
                        state=NavState.STUCK_ESCAPE,
                        pose=pose,
                        dist=dist_goal,
                        stuck_event=True,
                    )
                    self._last_pose = pose
                    return result

        at_goal = (
            (pose.place_id and pose.place_id == self._route_goal.id)
            or dist_goal <= self._route_goal.arrive_radius
        )
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
                    self._at_goal_since = None
            self._last_pose = pose
            return result

        result = self._drive_corridor(pose, now=now, dt=dt, dist=dist_goal, flow=flow_now)
        self._last_pose = pose
        return result

    def _tick_escape(
        self,
        pose: PoseResult,
        *,
        now: float,
        dt: float,
        dist_goal: float,
    ) -> NavTickResult:
        """Wall-stop escape: rotate only — never W into the same wall."""
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
            self.release_keys()
            self._yaw.integrate(yaw_delta)
            return self._make_result(
                state=self._state,
                pose=pose,
                dist=dist_goal,
                yaw_error=self._escape_turn_remaining,
                forward_held=False,
                stuck_event=False,
            )
        self._state = NavState.SEEK_GOAL
        self._last_progress_at = now
        self._arm_walk_burst(now)
        self.release_keys()
        return self._make_result(state=self._state, pose=pose, dist=dist_goal)

    def _drive_corridor(
        self,
        pose: PoseResult,
        *,
        now: float,
        dt: float,
        dist: float,
        flow: bool,
    ) -> NavTickResult:
        step = self._current_step()
        if step is not None:
            self._target = self._goal_from_wp(step.face_id)

        # Turn toward face landmark — never force_crawl W without Safe-W.
        motion = self._humanizer.compute(
            pose,
            self._target,
            self._fov,
            dt_sec=dt,
            now=now,
            look_sweeping=self._look_sweeping,
            force_crawl=False,
            force_walk=False,
        )
        self._state = NavState.SEEK_GOAL
        if motion.paused:
            self.release_keys()
            return self._make_result(
                state=self._state,
                pose=pose,
                dist=dist,
                yaw_error=motion.yaw_error_deg,
                humanize_micro_pause=motion.micro_pause,
            )
        if motion.mouse_dx or motion.mouse_dy:
            self._move(motion.mouse_dx, motion.mouse_dy)

        want_forward = bool(motion.forward)
        allowed = self._safe_w_allowed(now=now, flow=flow)
        if want_forward and allowed:
            self._set_move_key("w")
            forward = True
        else:
            self.release_keys()
            forward = False
            if want_forward and not allowed and now - self._last_safe_log_at >= 3.0:
                self._last_safe_log_at = now
                self._log.info(
                    "nav: Safe-W hold (no flow/burst) face=%s place=%s",
                    self._target.id,
                    pose.place_id or "?",
                )

        self._yaw.integrate(float(motion.turn_step_deg))
        return self._make_result(
            state=self._state,
            pose=pose,
            dist=dist,
            yaw_error=motion.yaw_error_deg,
            humanize_look_yield=motion.look_yield,
            humanize_forward_jitter=motion.forward_jitter,
            forward_held=forward,
            forward_fail_open=False,
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
            self._wander_forward = random.random() > 0.55
            span = self._pack.at_goal.wander_sec_max - self._pack.at_goal.wander_sec_min
            self._wander_until = (
                now + self._pack.at_goal.wander_sec_min + random.random() * span
            )
        if self._wander_forward and self._safe_w_allowed(now=now, flow=flow):
            motion = self._humanizer.compute(
                pose, self._route_goal, self._fov, dt_sec=dt, now=now,
                look_sweeping=self._look_sweeping, allow_forward=True,
            )
            if not motion.look_yield and motion.mouse_dx:
                self._move(motion.mouse_dx, 0)
            yaw_delta = float(motion.turn_step_deg)
            if motion.forward and not motion.paused and flow:
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
        return self._make_result(
            state=NavState.AT_GOAL, pose=pose, dist=dist, forward_held=forward,
        )
