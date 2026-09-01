"""Minimap goal navigation state machine (PR-N2/N3)."""



from __future__ import annotations



import logging

import random

from dataclasses import dataclass

from enum import Enum

from typing import Callable, Optional



from aiming.fov_mouse import FOVMouseMovement

from nav.coords import dist_norm

from nav.entry_picker import (

    entry_as_goal,

    pick_nearest_entry,

    should_use_entry,

)

from nav.humanize import NavHumanizer

from nav.pack import NavGoal, NavPack

from nav.pose import PoseResult



KeyDownFn = Callable[[str], None]

KeyUpFn = Callable[[str], None]

MoveFn = Callable[[int, int], None]



RESPAWN_JUMP_NORM = 0.22





class NavState(str, Enum):

    SEEK_ENTRY = "seek_entry"

    SEEK_GOAL = "seek_goal"

    AT_GOAL = "at_goal"

    STUCK_ESCAPE = "stuck_escape"

    MACRO_FALLBACK = "macro_fallback"

    PAUSED = "paused"





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





class NavController:

    """Drive WASD + mouse toward pack goals using minimap pose."""



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

    ) -> None:

        self._pack = pack

        self._fov = fov_mouse

        self._key_down = key_down

        self._key_up = key_up

        self._move = move_relative

        self._log = logger or logging.getLogger("CS2Bot.nav")

        self._pose_lost_sec = pose_lost_sec

        self._team = team.strip().lower() or "any"



        self._state = NavState.SEEK_GOAL

        self._phase = NavPhase.GOAL

        self._route_index = 0

        self._route_goal = self._current_route_goal()

        self._target: NavGoal = self._route_goal

        self._active_entry_id: Optional[str] = None

        self._held_key: Optional[str] = None

        self._last_tick_at: Optional[float] = None

        self._best_dist = 999.0

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



    @property

    def state(self) -> NavState:

        return self._state



    @property

    def goal_id(self) -> str:

        return self._route_goal.id



    @property

    def target_id(self) -> str:

        return self._target.id



    def release_keys(self) -> None:

        if self._held_key is not None:

            self._key_up(self._held_key)

            self._held_key = None



    def reload_pack(self, pack: NavPack) -> None:

        """Hot-swap nav pack when map_detect confirms a new script (PR-N6)."""

        self.release_keys()

        self._pack = pack

        self._humanizer = NavHumanizer(pack.humanize)

        self._state = NavState.SEEK_GOAL

        self._phase = NavPhase.GOAL

        self._route_index = 0

        self._route_goal = self._current_route_goal()

        self._target = self._route_goal

        self._active_entry_id = None

        self._best_dist = 999.0

        self._last_progress_at = 0.0

        self._pose_lost_since = None

        self._fallback_until = 0.0

        self._escape_until = 0.0

        self._escape_turn_remaining = 0.0

        self._escape_index = 0

        self._wander_until = 0.0

        self._wander_forward = False

        self._at_goal_since = None

        self._planned = False

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

        if len(goals) <= 1:

            return False

        if self._pack.strategy != "route_cycle":

            return False

        prev = self._route_goal.id

        self._route_index = (self._route_index + 1) % len(goals)

        self._route_goal = self._current_route_goal()

        self._log.info(

            "nav: route cycle %s -> %s",

            prev,

            self._route_goal.id,

        )

        return True



    def _plan_route(self, pose: PoseResult, *, now: float) -> tuple[bool, bool]:

        """Pick entry waypoint or go direct to route goal. Returns event flags."""

        entry_event = False

        goal_event = False

        self._route_goal = self._current_route_goal()

        self._active_entry_id = None

        self._phase = NavPhase.GOAL

        self._target = self._route_goal



        if should_use_entry(

            pose,

            self._route_goal,

            self._pack.entries,

            direct_goal_dist=self._pack.route.direct_goal_dist,

        ):

            entry = pick_nearest_entry(

                pose,

                self._pack.entries,

                team=self._team,

            )

            if entry is not None:

                self._phase = NavPhase.ENTRY

                self._target = entry_as_goal(entry)

                self._active_entry_id = entry.id

                self._state = NavState.SEEK_ENTRY

                entry_event = True

                self._log.info(

                    "nav: entry %s -> goal %s",

                    entry.id,

                    self._route_goal.id,

                )

                return entry_event, goal_event



        self._state = NavState.SEEK_GOAL

        goal_event = True

        return entry_event, goal_event



    def _reset_progress(self, now: float) -> None:

        self._best_dist = 999.0

        self._last_progress_at = now



    def _maybe_detect_respawn(self, pose: PoseResult) -> bool:

        if self._last_pose is None or not pose.valid or not self._last_pose.valid:

            return False

        jump = dist_norm(

            pose.x_norm,

            pose.y_norm,

            self._last_pose.x_norm,

            self._last_pose.y_norm,

        )

        return jump >= RESPAWN_JUMP_NORM



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

        self._escape_until = now + self._pack.stuck.escape_duration_sec

        self._state = NavState.STUCK_ESCAPE

        self.release_keys()

        self._log.info("nav: stuck escape rotate %.0f°", angle)



    def _complete_entry(self, now: float) -> None:

        self._phase = NavPhase.GOAL

        self._target = self._route_goal

        self._state = NavState.SEEK_GOAL

        self._reset_progress(now)

        self._log.info("nav: entry reached, seeking %s", self._route_goal.id)



    def _dist_to_target(self, pose: PoseResult) -> float:

        return dist_norm(

            pose.x_norm,

            pose.y_norm,

            self._target.x,

            self._target.y,

        )



    def _dist_to_route_goal(self, pose: PoseResult) -> float:

        return dist_norm(

            pose.x_norm,

            pose.y_norm,

            self._route_goal.x,

            self._route_goal.y,

        )



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

        entry_pick_event: bool = False,

        goal_switch_event: bool = False,

        humanize_micro_pause: bool = False,

        humanize_look_yield: bool = False,

        humanize_forward_jitter: bool = False,

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

            entry_pick_event=entry_pick_event,

            goal_switch_event=goal_switch_event,

            humanize_micro_pause=humanize_micro_pause,

            humanize_look_yield=humanize_look_yield,

            humanize_forward_jitter=humanize_forward_jitter,

        )



    def _maybe_stuck(
        self,
        *,
        now: float,
        dist_target: float,
        dist_goal: float,
        pose: PoseResult,
    ) -> NavTickResult | None:
        if dist_target < self._best_dist - self._pack.stuck.min_progress_norm:
            self._best_dist = dist_target
            self._last_progress_at = now
            return None
        if now - self._last_progress_at >= self._pack.stuck.progress_timeout_sec:
            self._start_escape(now)
            return self._make_result(
                state=NavState.STUCK_ESCAPE,
                pose=pose,
                dist=dist_goal,
                stuck_event=True,
            )
        return None

    def tick(

        self,

        pose: PoseResult,

        *,

        now: float,

        paused: bool,

        team: str | None = None,

        look_sweeping: bool = False,

    ) -> NavTickResult:

        if team:

            self._team = team.strip().lower() or "any"

        self._look_sweeping = look_sweeping

        if self._last_tick_at is None:

            dt = 1.0 / 60.0

        else:

            dt = max(1.0 / 240.0, min(0.1, now - self._last_tick_at))

        self._last_tick_at = now



        if paused:

            self.release_keys()

            self._state = NavState.PAUSED

            result = self._make_result(

                state=self._state,

                pose=pose,

                dist=self._dist_to_route_goal(pose) if pose.valid else 0.0,

            )

            self._last_pose = pose

            return result



        if self._state == NavState.MACRO_FALLBACK:

            if now >= self._fallback_until:

                self._state = NavState.SEEK_GOAL

                self._reset_progress(now)

                self._pose_lost_since = None

                self._planned = False

                self._at_goal_since = None

                self._humanizer.reset()

                self._log.info("nav: fallback ended, resuming seek")

            else:

                result = self._make_result(

                    state=self._state,

                    pose=pose,

                    dist=0.0,

                    use_macro_patrol=True,

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

            result = self._make_result(

                state=self._state,

                pose=pose,

                dist=0.0,

            )

            self._last_pose = pose

            return result



        self._pose_lost_since = None



        if not self._planned or self._maybe_detect_respawn(pose):

            entry_event, goal_event = self._plan_route(pose, now=now)

            self._planned = True

            self._reset_progress(now)

            self._at_goal_since = None

            self._humanizer.reset()

        else:

            entry_event = False

            goal_event = False



        dist_target = self._dist_to_target(pose)

        dist_goal = self._dist_to_route_goal(pose)



        if self._state == NavState.STUCK_ESCAPE:

            if now < self._escape_until:

                step = max(

                    -self._pack.humanize.turn_rate_deg_per_sec * dt,

                    min(

                        self._pack.humanize.turn_rate_deg_per_sec * dt,

                        self._escape_turn_remaining,

                    ),

                )

                if abs(self._escape_turn_remaining) > 0.5:

                    mx, _ = self._fov.angle_to_mouse(step, 0.0)

                    if mx:

                        self._move(mx, 0)

                    self._escape_turn_remaining -= step

                strafe = "d" if self._escape_turn_remaining >= 0 else "a"

                self._set_move_key(strafe)

            else:

                self._state = (

                    NavState.SEEK_ENTRY

                    if self._phase == NavPhase.ENTRY

                    else NavState.SEEK_GOAL

                )

                self._reset_progress(now)

                self.release_keys()

            result = self._make_result(

                state=self._state,

                pose=pose,

                dist=dist_goal,

            )

            self._last_pose = pose

            return result



        if self._phase == NavPhase.ENTRY:

            if dist_target <= self._target.arrive_radius:

                self._complete_entry(now)

                dist_target = self._dist_to_target(pose)

            else:

                stuck = self._maybe_stuck(
                    now=now,
                    dist_target=dist_target,
                    dist_goal=dist_goal,
                    pose=pose,
                )

                if stuck is not None:

                    self._last_pose = pose

                    return stuck

                result = self._drive_toward_target(

                    pose,

                    now=now,

                    dt=dt,

                    dist=dist_goal,

                    dist_target=dist_target,

                    entry_pick_event=entry_event,

                    goal_switch_event=goal_event,

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

            result = self._tick_at_goal(

                pose,

                now=now,

                dt=dt,

                dist=dist_goal,

            )

            if (

                self._at_goal_since is not None

                and now - self._at_goal_since >= self._pack.route.dwell_at_goal_sec

            ):

                if self._advance_route_goal(now=now):

                    self._planned = False

                    self._at_goal_since = None

                    entry_event, goal_event = self._plan_route(pose, now=now)

                    self._planned = True

                    self._reset_progress(now)

                    result = self._make_result(

                        state=self._state,

                        pose=pose,

                        dist=self._dist_to_route_goal(pose),

                        goal_switch_event=True,

                    )

                    self._last_pose = pose

                    return result

            self._last_pose = pose

            return result



        stuck = self._maybe_stuck(
            now=now,
            dist_target=dist_target,
            dist_goal=dist_goal,
            pose=pose,
        )
        if stuck is not None:
            self._last_pose = pose
            return stuck

        result = self._drive_toward_target(

            pose,

            now=now,

            dt=dt,

            dist=dist_goal,

            dist_target=dist_target,

            entry_pick_event=entry_event,

            goal_switch_event=goal_event,

        )

        self._last_pose = pose

        return result



    def _drive_toward_target(

        self,

        pose: PoseResult,

        *,

        now: float,

        dt: float,

        dist: float,

        dist_target: float,

        entry_pick_event: bool,

        goal_switch_event: bool,

    ) -> NavTickResult:

        motion = self._humanizer.compute(
            pose,
            self._target,
            self._fov,
            dt_sec=dt,
            now=now,
            look_sweeping=self._look_sweeping,
        )

        state = (
            NavState.SEEK_ENTRY
            if self._phase == NavPhase.ENTRY
            else NavState.SEEK_GOAL
        )

        if motion.paused:
            self.release_keys()
            return self._make_result(
                state=state,
                pose=pose,
                dist=dist,
                yaw_error=motion.yaw_error_deg,
                entry_pick_event=entry_pick_event,
                goal_switch_event=goal_switch_event,
                humanize_micro_pause=motion.micro_pause,
            )

        if motion.mouse_dx or motion.mouse_dy:
            self._move(motion.mouse_dx, motion.mouse_dy)
        if motion.forward:
            self._set_move_key("w")
        else:
            self.release_keys()

        return self._make_result(
            state=state,
            pose=pose,
            dist=motion.dist_to_goal or dist,
            yaw_error=motion.yaw_error_deg,
            entry_pick_event=entry_pick_event,
            goal_switch_event=goal_switch_event,
            humanize_look_yield=motion.look_yield,
            humanize_forward_jitter=motion.forward_jitter,
        )



    def _tick_at_goal(

        self,

        pose: PoseResult,

        *,

        now: float,

        dt: float,

        dist: float,

    ) -> NavTickResult:

        if now >= self._wander_until:

            self._wander_forward = random.random() > 0.35

            span = self._pack.at_goal.wander_sec_max - self._pack.at_goal.wander_sec_min

            self._wander_until = now + self._pack.at_goal.wander_sec_min + random.random() * span



        if self._wander_forward:

            motion = self._humanizer.compute(
                pose,
                self._route_goal,
                self._fov,
                dt_sec=dt,
                now=now,
                look_sweeping=self._look_sweeping,
                allow_forward=True,
            )
            if not motion.look_yield and motion.mouse_dx:
                self._move(motion.mouse_dx, 0)
            if motion.forward and not motion.paused:
                self._set_move_key("w")
            else:
                self.release_keys()

        else:

            if not self._look_sweeping:
                turn = random.choice([-1, 1]) * self._pack.humanize.turn_rate_deg_per_sec * dt
                mx, _ = self._fov.angle_to_mouse(turn, 0.0)
                if mx:
                    self._move(mx, 0)
            self.release_keys()



        return self._make_result(

            state=NavState.AT_GOAL,

            pose=pose,

            dist=dist,

        )

