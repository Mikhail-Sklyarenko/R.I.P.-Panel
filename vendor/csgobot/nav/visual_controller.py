"""Closed-loop route follower. Only fresh independent map measurements drive it.

Route geometry is checked against an annotated footprint-inflated mask. Camera
turns are acceleration-limited; movement is stopped when heading, clearance,
freshness or progress cannot be confirmed. Recovery retraces observed ground.
"""
from __future__ import annotations

import logging
import math
from collections import deque

from nav.controller import NavState, NavTickResult
from nav.coords import normalize_angle_deg
from nav.walkable import WalkableMap
from nav.input_lease import KeyLease


class VisualNavController:
    def __init__(self, pack, fov_mouse, key_down, key_up, move_relative,
                 *, logger=None, walkable=None, watchdog=False, **_compat):
        self._fov = fov_mouse
        self._down, self._up, self._move = key_down, key_up, move_relative
        self._log = logger or logging.getLogger("CS2Bot.nav")
        self._lease = KeyLease(key_down, key_up, background=watchdog)
        self._supplied_map = walkable
        self.reload_pack(pack)

    def reload_pack(self, pack):
        self.release_keys()
        self._pack = pack
        self._route_index = 0
        self._route_goal = (pack.goals or (pack.goal,))[0]
        self._target = (self._route_goal.x, self._route_goal.y)
        self._path = ()
        self._path_index = 1
        self._last_tick = None
        self._turn_rate = self._mouse_remainder = 0.
        self._progress_anchor = None
        self._moving_since = None
        self._history = deque(maxlen=80)
        self._observations = deque(maxlen=5)
        self._last_observation_at = None
        self._recovery_target = None
        self._recovery_started = None
        self._recovery_count = 0
        self._blocked_at = None
        self._at_goal_since = None
        self._retry_after = 0.
        self.last_pose = None
        self.state = NavState.WAIT_POSE
        self.reason = "awaiting_measurement"
        try:
            self.walkable = self._supplied_map or WalkableMap.load(pack.map_id)
        except (ValueError, OSError) as exc:
            self._log.error("nav: invalid walkable profile: %s", exc)
            self.walkable = None
        if self.walkable is None:
            self.reason = "missing_walkable_profile"
            self._log.warning("nav: %s map=%s; create a profile with scripts/nav_workbench.py mask", self.reason, pack.map_id)

    @property
    def suppresses_look(self):
        return self.state != NavState.AT_GOAL

    @property
    def is_locomoting(self):
        return self.state in (NavState.SEEK_GOAL, NavState.STUCK_ESCAPE)

    @property
    def goal_id(self):
        return self._route_goal.id

    @property
    def target_id(self):
        return f"path:{self._path_index}"

    @property
    def edge_neighbors(self):
        return {}

    @property
    def path_label(self):
        return ">".join(f"{x:.3f},{y:.3f}" for x, y in self._path)

    def face_target(self):
        return self._target

    def release_keys(self):
        self._lease.release()

    def close(self):
        self._lease.close()

    @property
    def _keys(self):
        return self._lease.keys

    def _set_keys(self, keys):
        self._lease.set_keys(keys)

    def _result(self, pose, now, *, stuck=False, switched=False):
        age = max(0., now - pose.observed_at) if pose.observed_at is not None else 0.
        dist = math.hypot(pose.x_norm - self._route_goal.x, pose.y_norm - self._route_goal.y)
        return NavTickResult(
            state=self.state, dist_to_goal=dist, yaw_error_deg=getattr(self, "_yaw_error", 0.),
            pose_valid=pose.valid, goal_id=self.goal_id, target_id=self.target_id,
            phase="goal", stuck_event=stuck, goal_switch_event=switched,
            forward_held="w" in self._keys, pose_mode=pose.radar_mode,
            path=self.path_label, reason=self.reason, pose_age_sec=age,
        )

    def _stop(self, state, reason):
        self.release_keys()
        self.state, self.reason = state, reason
        self._turn_rate = self._mouse_remainder = 0.
        self._moving_since = None

    def _distance(self, a, b):
        ap, bp = self.walkable.pixel(a), self.walkable.pixel(b)
        return math.hypot(ap[0] - bp[0], ap[1] - bp[1])

    def _turn(self, error, dt):
        if not self._lease.active:
            return
        limit = min(120., self._pack.humanize.turn_rate_deg_per_sec)
        desired = max(-limit, min(limit, 4. * error))
        change = max(-360. * dt, min(360. * dt, desired - self._turn_rate))
        self._turn_rate += change
        angle = self._turn_rate * dt
        # No overshoot across zero and no unobserved yaw integration.
        if angle * error <= 0:
            angle = 0.
        elif abs(angle) > abs(error):
            angle = error
        counts = angle * self._fov.fov.x360 / 360. + self._mouse_remainder
        dx = int(counts)
        self._mouse_remainder = counts - dx
        if dx:
            self._move(dx, 0)

    def tick(self, pose, *, now, paused, **_compat):
        dt = .016 if self._last_tick is None else min(.1, max(0., now - self._last_tick))
        self._last_tick = now
        self.last_pose = pose
        if paused:
            self._stop(NavState.PAUSED, "external_pause")
            return self._result(pose, now)
        if (not pose.valid or pose.radar_mode != "visual" or pose.observed_at is None
                or not 0 <= now - pose.observed_at <= .25 or pose.confidence < .45
                or not all(math.isfinite(v) for v in (pose.x_norm, pose.y_norm, pose.yaw_deg, pose.confidence))):
            self._stop(NavState.WAIT_POSE, "no_fresh_measured_pose")
            self._path = ()
            self._history.clear()
            self._recovery_target = None
            self._observations.clear()
            return self._result(pose, now)
        self._lease.renew(.25 - (now - pose.observed_at))
        if self.walkable is None:
            self._stop(NavState.BLOCKED, "missing_walkable_profile")
            return self._result(pose, now)
        point = (pose.x_norm, pose.y_norm)
        goal = (self._route_goal.x, self._route_goal.y)
        if not self.walkable.contains(point):
            self._stop(NavState.BLOCKED, "pose_outside_verified_ground")
            self._path = ()
            return self._result(pose, now)
        # A blocked attempt cannot re-arm itself merely because another tick ran.
        if self._blocked_at is not None:
            if self._distance(point, self._blocked_at) < 12:
                self._stop(NavState.BLOCKED, "recovery_exhausted")
                return self._result(pose, now)
            self._blocked_at = None
            self._recovery_count = 0
            self._path = ()
        if self._history and self._distance(point, self._history[-1]) > 80:
            self._path = ()
            self._history.clear()
            self._recovery_target = None
        if not self._history or self._distance(point, self._history[-1]) >= 6:
            self._history.append(point)

        tolerance = min(10., max(3., self._route_goal.arrive_radius * min(self.walkable.width, self.walkable.height)))
        if self._distance(point, goal) <= tolerance and self.walkable.visible(point, goal):
            self._stop(NavState.AT_GOAL, "goal_reached")
            if self._at_goal_since is None:
                self._at_goal_since = now
            switched = False
            if (self._pack.strategy == "route_cycle" and len(self._pack.goals) > 1
                    and now - self._at_goal_since >= self._pack.route.dwell_at_goal_sec):
                self._route_index = (self._route_index + 1) % len(self._pack.goals)
                self._route_goal = self._pack.goals[self._route_index]
                self._path = ()
                self._at_goal_since = None
                self._recovery_count = 0
                switched = True
            return self._result(pose, now, switched=switched)
        self._at_goal_since = None

        if self._last_observation_at != pose.observed_at:
            self._observations.append(point)
            self._last_observation_at = pose.observed_at
        ordered_x = sorted(p[0] for p in self._observations)
        ordered_y = sorted(p[1] for p in self._observations)
        median = (ordered_x[len(ordered_x)//2], ordered_y[len(ordered_y)//2])
        if self._progress_anchor is None or self._distance(median, self._progress_anchor) >= 6.:
            self._progress_anchor = median
            self._moving_since = now if self._keys & {"w", "s"} else None
        stuck = bool(self._keys & {"w", "s"}) and self._moving_since is not None and now - self._moving_since >= 1.2
        if stuck:
            self.release_keys()
            self._moving_since = None
            self._recovery_count += 1
            candidates = [p for p in reversed(self._history) if 12 <= self._distance(point, p) <= 60 and self.walkable.visible(point, p)]
            if self._recovery_target is not None or self._recovery_count > 2 or not candidates:
                self._blocked_at = point
                self._stop(NavState.BLOCKED, "no_verified_recovery")
                return self._result(pose, now, stuck=True)
            self._recovery_target = candidates[0]
            self._recovery_started = now
            self._turn_rate = 0.

        reverse = False
        if self._recovery_target is not None:
            if self._distance(point, self._recovery_target) <= 5:
                self._recovery_target = None
                self._path = ()
                self._stop(NavState.SEEK_GOAL, "recovered_replan")
                return self._result(pose, now)
            if now - self._recovery_started > 4:
                self._blocked_at = point
                self._stop(NavState.BLOCKED, "recovery_timeout")
                return self._result(pose, now)
            self._target = self._recovery_target
            self.state, self.reason = NavState.STUCK_ESCAPE, "retrace_verified_ground"
            reverse = True
        else:
            if not self._path:
                if now < self._retry_after:
                    self._stop(NavState.BLOCKED, "no_verified_route")
                    return self._result(pose, now)
                self._path = self.walkable.plan(point, goal)
                self._path_index = 1
                self._retry_after = now + 1.
                if not self._path:
                    self._stop(NavState.BLOCKED, "no_verified_route")
                    return self._result(pose, now)
            while (self._path_index < len(self._path) - 1
                   and self._distance(point, self._path[self._path_index]) < 6
                   and self.walkable.visible(point, self._path[self._path_index + 1])):
                self._path_index += 1
            self._target = self._path[self._path_index]
            self.state, self.reason = NavState.SEEK_GOAL, "follow_verified_route"
        if not self.walkable.visible(point, self._target):
            self._path = ()
            self._stop(NavState.BLOCKED, "segment_obstructed")
            return self._result(pose, now)
        px, py = self.walkable.pixel(point)
        tx, ty = self.walkable.pixel(self._target)
        bearing = math.degrees(math.atan2(ty - py, tx - px))
        heading = bearing + (180. if reverse else 0.)
        self._yaw_error = normalize_angle_deg(heading - pose.yaw_deg)
        self._turn(self._yaw_error, dt)
        # Actual WASD is discrete. Walk modifier around corners avoids W jitter.
        # A clear target segment is insufficient while the body still faces a
        # wall. Check the observed heading too before applying translation.
        travel_yaw = math.radians(pose.yaw_deg + (180. if reverse else 0.))
        probe = min(8., self._distance(point, self._target))
        ahead = self.walkable.norm((px + math.cos(travel_yaw) * probe,
                                    py + math.sin(travel_yaw) * probe))
        heading_clear = self.walkable.visible(point, ahead)
        if abs(self._yaw_error) <= 28. and heading_clear:
            keys = {"s" if reverse else "w"}
            if reverse or abs(self._yaw_error) > 10 or self._distance(point, self._target) < 28:
                keys.add("shift")
            if self._moving_since is None:
                self._moving_since = now
                self._progress_anchor = point
            self._set_keys(keys)
        else:
            self.release_keys()
            self._moving_since = None
            self.reason = "align_measured_heading"
        return self._result(pose, now, stuck=stuck)
