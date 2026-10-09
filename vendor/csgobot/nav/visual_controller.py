"""Closed-loop route follower with bounded Dust2 corridor continuity.

Route geometry is checked against an annotated footprint-inflated mask. Camera
turns are acceleration-limited; movement is stopped when heading, clearance,
freshness or progress cannot be confirmed. A finite, explicitly logged corridor
permission can bridge a short localization gap using live heading evidence.
Recovery retraces observed ground.
"""
from __future__ import annotations

import logging
import math
from collections import deque

from nav.controller import NavState, NavTickResult
from nav.coords import normalize_angle_deg
from nav.walkable import WalkableMap
from nav.input_lease import KeyLease
from nav.camera_servo import CameraServo


class VisualNavController:
    def __init__(self, pack, fov_mouse, key_down, key_up, move_relative,
                 *, logger=None, walkable=None, watchdog=False, input_allowed=lambda: True,
                 free_roam=False, camera_rate=None, walkable_loader=None, adaptive_goal=False, **_compat):
        self._free_roam = free_roam
        self._adaptive_goal = adaptive_goal
        self._adaptive_routing = free_roam or adaptive_goal
        self._camera_rate = camera_rate
        self._fov = fov_mouse
        self._down, self._up, self._move = key_down, key_up, move_relative
        self._log = logger or logging.getLogger("CS2Bot.nav")
        self._lease = KeyLease(key_down, key_up, background=watchdog, allowed=input_allowed)
        self._camera = CameraServo(move_relative, fov_mouse.fov.x360, background=True, allowed=input_allowed) if watchdog else None
        self._walkable_loader = walkable_loader
        self._supplied_map = walkable
        self.reload_pack(pack)

    def reload_pack(self, pack, *, layer_id=None):
        import json
        from nav.paths import resolve_visual_profile_file
        old_family = getattr(self, '_pack', None)
        self._active_layer = layer_id or ("upper" if pack.map_id in ("de_mirage","de_cache") else None)
        self._layer_config = None
        if pack.map_id in ('de_vertigo','de_mirage','de_cache','de_nuke'):
            self._layer_config = json.loads(resolve_visual_profile_file(pack.map_id,'layers.json').read_text())
            if old_family is None or old_family.map_id != pack.map_id or not hasattr(self,'_layer_grounds'):
                if pack.map_id == 'de_cache':
                    from nav.cache_levels import load_grounds
                    self._layer_grounds=load_grounds(self._layer_config)
                elif pack.map_id == 'de_mirage':
                    from nav.mirage_levels import load_grounds
                    self._layer_grounds=load_grounds(self._layer_config)
                else:
                    self._layer_grounds = {name:WalkableMap.load(map_id) for name,map_id in self._layer_config['layers'].items()}
                if any(g is None for g in self._layer_grounds.values()):
                    raise ValueError('Missing navigation floor mask')
            if layer_id is not None and layer_id not in self._layer_grounds:
                raise ValueError('Unknown navigation floor')
        self.release_keys()
        self._pack = pack
        from nav.traversal_actions import TraversalActions
        self._traversal = TraversalActions.load(pack.map_id)
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
        self._needs_attach = True
        self._lost_since = None
        self._last_measured_point = None
        self.last_pose = None
        self.state = NavState.WAIT_POSE
        self.reason = "awaiting_measurement"
        try:
            self.walkable = (self._layer_grounds[layer_id or 'upper'] if self._layer_config else
                self._walkable_loader(pack.map_id) if self._walkable_loader else self._supplied_map or WalkableMap.load(pack.map_id))
        except (ValueError, OSError) as exc:
            self._log.error("nav: invalid walkable profile: %s", exc)
            self.walkable = None
        from nav.roaming import RoamingGoals
        self._roaming = RoamingGoals(self.walkable) if self._free_roam and self.walkable else None
        if self._layer_config and self._roaming is not None:
            if pack.map_id == 'de_cache':
                from nav.cache_levels import CacheRoamingGoals
                self._roaming=CacheRoamingGoals(self.walkable,layer_id or 'upper',self._layer_config)
            elif pack.map_id == 'de_mirage':
                from nav.mirage_levels import MirageRoamingGoals
                self._roaming=MirageRoamingGoals(self.walkable,layer_id or 'upper',self._layer_config)
            else:
                from nav.layered_roaming import LayeredRoamingGoals
                self._roaming = LayeredRoamingGoals(self.walkable, layer_id or 'upper', self._layer_config['portals'])
        self._spawn_samples = deque(maxlen=3)
        self._base_walkable = self.walkable
        self._obstacles = []
        self._reroutes = deque(maxlen=8)
        self._active_age = 0.
        self._goal_progress = None
        self._goal_progress_at = 0.
        self._travel_demand = 0.
        self._last_demand_tick = None
        self._last_failed_direction = None
        self._last_failed_origin = None
        self._boundary_target = None
        self._boundary_since = None
        self._boundary_origin = None
        self._boundary_drive = 0.
        if self.walkable is None:
            self.reason = "missing_walkable_profile"
            self._log.warning("nav: %s map=%s; create a profile with scripts/nav_workbench.py mask", self.reason, pack.map_id)

    def switch_mission_ground(self, ground, *, actions=None):
        """Change a committed Wingman traversal's geometry without inventing pose."""
        from nav.traversal_actions import TraversalActions
        self.release_keys()
        self.walkable=self._base_walkable=ground
        self._obstacles=[]
        self._reroutes.clear()
        self._path=()
        self._needs_attach=True
        self._history.clear()
        self._recovery_target=None
        self._recovery_count=0
        self._blocked_at=None
        self._traversal=(TraversalActions(actions) if actions is not None else TraversalActions.load(self._pack.map_id))

    def reset_round(self, *, now, preserve_obstacles=False):
        obstacles = [(c,r,t) for c,r,t in self._obstacles if t > now] if preserve_obstacles else []
        self.reload_pack(self._pack)
        if self.walkable is not None and obstacles:
            self._obstacles = obstacles
            self.walkable = self._base_walkable.excluding([(c,r) for c,r,_ in obstacles])

    def set_goal(self, goal, *, continue_motion=False, prepared_path=()):
        """Change a same-map mission without forgetting observed obstacles."""
        from dataclasses import replace
        if not continue_motion:self.release_keys()
        self._pack = replace(self._pack,goal=goal,goals=(goal,))
        self._route_goal = goal
        self._route_index = 0
        self._path = ()
        self._path_index = 1
        self._needs_attach = True
        self._recovery_target = None
        self._recovery_count = 0
        self._blocked_at = None
        self._retry_after = 0.
        self._at_goal_since = None
        self._goal_progress = None
        self._goal_progress_at = self._active_age
        self._travel_demand = 0.
        self._moving_since = None
        self._progress_anchor = None

        # Accept background geometry only when its final goal and every segment
        # still agree with the current ground. Join from the measured position.
        if prepared_path and self.walkable is not None and self.last_pose is not None and self.last_pose.valid:
            current = (self.last_pose.x_norm,self.last_pose.y_norm)
            path = tuple(prepared_path)
            if (len(path) >= 2 and self._distance(path[-1],(goal.x,goal.y)) < .1
                    and all(self.walkable.visible(a,b) for a,b in zip(path,path[1:]))):
                join = path[1:] if self.walkable.comfortable_visible(current,path[1]) else path
                if self.walkable.visible(current,join[0]):
                    self._path = (current,)+join
                    self._path_index = 1
                    self._target = self._path[1]
                    self._needs_attach = False

    @property
    def suppresses_look(self):
        return self._free_roam or self.state != NavState.AT_GOAL

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
        self._corridor_permit = None
        self._continuity_at = None
        if hasattr(self, "_traversal"):
            self._traversal.reset()
        self._lease.release()
        if self._camera is not None:
            self._camera.stop()

    def close(self):
        if self._camera is not None:
            self._camera.close()
        self._lease.close()

    @property
    def _keys(self):
        return self._lease.keys

    def _set_keys(self, keys):
        pose = self.last_pose
        point = (pose.x_norm, pose.y_norm) if pose is not None and pose.valid else None
        self._lease.set_keys(self._traversal.apply(keys, point, now=self._last_tick,
            yaw=pose.yaw_deg if pose is not None and pose.valid else None,
            target=self._target,observation=getattr(self,"_door_observation",None)))

    def _result(self, pose, now, *, stuck=False, switched=False):
        continuity=self.reason=='bounded_corridor_continuity'
        observed=self._corridor_permit.observed_at if continuity else pose.observed_at
        age = max(0., now - observed) if observed is not None else 0.
        point=self._corridor_permit.origin if continuity else (pose.x_norm,pose.y_norm)
        dist = math.hypot(point[0] - self._route_goal.x, point[1] - self._route_goal.y)
        return NavTickResult(
            state=self.state, dist_to_goal=dist, yaw_error_deg=getattr(self, "_yaw_error", 0.),
            pose_valid=pose.valid and not continuity, goal_id=self.goal_id, target_id=self.target_id,
            phase="continuity" if continuity else self._traversal.phase, stuck_event=stuck, goal_switch_event=switched,
            forward_held="w" in self._keys, forward_fail_open=continuity,
            pose_mode="corridor_permit" if continuity else pose.radar_mode,
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

    def _attach_route(self, point):
        """Choose by reachable path length, never a straight line through walls."""
        options = []
        for index, goal in enumerate(self._pack.goals):
            path = self.walkable.plan(point, (goal.x, goal.y))
            if path:
                cost = sum(self._distance(a, b) for a, b in zip(path, path[1:]))
                options.append((cost, index, path))
        if not options:
            return False
        _, self._route_index, self._path = min(options)
        self._route_goal = self._pack.goals[self._route_index]
        self._path_index = 1
        self._at_goal_since = None
        self._retry_after = 0.
        self._needs_attach = False
        return True

    def _attach_roaming(self, point):
        choice = self._roaming.choose(point, self._active_age)
        if choice is None:
            return False
        self._route_goal, self._path = choice
        self._goal_progress = None
        self._goal_progress_at = self._active_age
        self._path_index = 1
        self._needs_attach = False
        self._at_goal_since = None
        self._recovery_count = 0
        return True

    def _travel_keys(self, point, yaw, bearing, distance, *, boundary=False):
        """Steer the body along a checked ray while the camera catches up."""
        directions = ((0., {'w'}), (45., {'w','d'}), (90., {'d'}),
                      (135., {'s','d'}), (180., {'s'}), (-135., {'s','a'}),
                      (-90., {'a'}), (-45., {'w','a'}))
        error = normalize_angle_deg(bearing-yaw)
        ranked = sorted(directions, key=lambda item: abs(normalize_angle_deg(error-item[0]))
                        - ((10. if self._pack.map_id=="de_nuke" else 6.) if item[1] == (self._keys & {"w", "a", "s", "d"}) else 0.))
        px,py = self.walkable.pixel(point)
        # Near a corner the closest WASD direction may sweep into a wall as
        # the camera turns. An adjacent, still forward-progressing direction
        # can keep the body moving along the corridor instead of braking.
        limits = (28.,65.) if self._pack.map_id == 'de_dust2' and not boundary else (28.,)
        if self._pack.map_id=='de_nuke' and not boundary:limits=(28.,55.)
        for limit in limits:
            for offset,keys in ranked:
                if abs(normalize_angle_deg(error-offset)) > limit:
                    continue
                # Held keys rotate with the camera between observations. Check the
                # swept directions as well as the ray at the capture instant.
                turn = math.copysign(min(30.,abs(error)),error)
                clear = True
                for fraction in (0.,.25,.5,.75,1.):
                    angle = math.radians(yaw+offset+turn*fraction)
                    ahead = self.walkable.norm((px+math.cos(angle)*distance,py+math.sin(angle)*distance))
                    clear = clear and (self._base_walkable.increasing_clearance(point,ahead) if boundary
                                        else self.walkable.visible(point,ahead))
                if not clear:
                    continue
                if clear:
                    return keys
        return set()

    def _lookahead_target(self, point, distance=24.):
        # Follow a point ahead on the polyline, rather than a tiny waypoint that
        # ends up behind the body. Every corner shortcut must remain visible.
        index = self._path_index
        a = self.walkable.pixel(self._path[max(0,index-1)])
        b = self.walkable.pixel(self._path[index])
        p = self.walkable.pixel(point)
        dx,dy = b[0]-a[0],b[1]-a[1]
        fraction = max(0.,min(1.,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/max(1e-9,dx*dx+dy*dy)))
        cursor = self.walkable.norm((a[0]+fraction*dx,a[1]+fraction*dy))
        target = self._path[index]
        remaining = distance
        for endpoint in self._path[index:]:
            length = self._distance(cursor,endpoint)
            fraction = min(1.,remaining/max(length,1e-9))
            candidate = (cursor[0]+fraction*(endpoint[0]-cursor[0]),cursor[1]+fraction*(endpoint[1]-cursor[1]))
            if not self.walkable.visible(point,candidate):
                break
            target = candidate
            remaining -= length
            if remaining <= 0:
                break
            cursor = endpoint
        return target

    def _boundary_step(self, point, pose, now, dt):
        target = None
        if self._pack.map_id=='de_vertigo':
            target=self._boundary_target
            if (target is None or not self._base_walkable.contains(target)
                    or self._distance(point,target)>12
                    or not self._base_walkable.increasing_clearance(point,target)):
                target=self._base_walkable.boundary_exit(point,prefer_interior=True)
            self._boundary_target=target
        else:
            target = self._base_walkable.boundary_exit(point)
        if target is None:
            return False
        if self._needs_attach:
            if not self._spawn_samples or self._spawn_samples[-1][0]!=pose.observed_at:
                self._spawn_samples.append((pose.observed_at,point))
            if len(self._spawn_samples)<3 or any(self._distance(point,p)>10 for _,p in self._spawn_samples):
                self._stop(NavState.WAIT_POSE,"confirm_boundary_position")
                return True
        if self._boundary_since is None:
            self._boundary_since, self._boundary_origin = now,point
            self._boundary_drive = 0.
        if self._keys & {'w','a','s','d'}:
            self._boundary_drive += dt
        if self._boundary_drive>3 or self._distance(point,self._boundary_origin)>16:
            self._stop(NavState.BLOCKED,"boundary_exit_exhausted")
            return True
        # Temporary obstacles remain restrictions even during a boundary exit.
        if any(self._distance(target,c)<=radius+2 or self._distance(point,c)<=radius+2
               for c,radius,_ in self._obstacles):
            return False
        self._path=()
        self._target=target
        px,py=self.walkable.pixel(point);tx,ty=self.walkable.pixel(target)
        self._yaw_error=normalize_angle_deg(math.degrees(math.atan2(ty-py,tx-px))-pose.yaw_deg)
        self._turn(self._yaw_error,dt)
        probe=min(3.,self._distance(point,target))
        keys = self._travel_keys(point,pose.yaw_deg,pose.yaw_deg+self._yaw_error,probe,boundary=True)
        self._set_keys(keys)
        if keys:
            self.state,self.reason=NavState.STUCK_ESCAPE,"exit_boundary_toward_clearance"
        else:
            self.state,self.reason=NavState.SEEK_GOAL,"align_boundary_exit"
        return True

    def _restore_ground(self):
        self.walkable = self._base_walkable
        self._obstacles.clear()
        if self._roaming is not None:
            self._roaming.set_ground(self.walkable)

    def _refresh_obstacles(self, point, now):
        # Recovery disks are hypotheses, not static map walls. A later measured
        # body position must not become trapped inside one until its timeout.
        obstacles = []
        for center, radius, expires in self._obstacles:
            if expires <= now:
                continue
            if self._base_walkable.contains(point):
                radius = min(radius, max(0., self._distance(point, center)-4.))
            if radius >= 3:
                obstacles.append((center, radius, expires))
        if obstacles != self._obstacles:
            self._obstacles = obstacles
            self.walkable = self._base_walkable.excluding([(c,r) for c,r,_ in obstacles])
            if self._roaming is not None:self._roaming.set_ground(self.walkable)
            self._path = ()

    def _avoid_failed_direction(self, point, now):
        if sum(now-t<60 for t in self._reroutes)>=3:
            return False
        target = self._last_failed_direction or self._target
        self._last_failed_direction = None
        origin = self._last_failed_origin if self._adaptive_goal and self._last_failed_origin is not None else point
        self._last_failed_origin = None
        px,py = self.walkable.pixel(origin)
        tx,ty = self.walkable.pixel(target)
        length = math.hypot(tx-px,ty-py)
        if length<4:
            return False
        center = self.walkable.norm((px+(tx-px)/length*18,py+(ty-py)/length*18))
        obstacles = self._obstacles + [(center,10,now+60)]
        ground = self._base_walkable.excluding([(c,r) for c,r,_ in obstacles])
        if not ground.contains(point):
            return False
        previous = self.walkable
        self.walkable = ground
        if self._roaming is not None:
            self._roaming.set_ground(ground)
            attached = self._attach_roaming(point)
        else:
            path = ground.plan(point,(self._route_goal.x,self._route_goal.y))
            attached = bool(path)
            if attached:
                self._path = path
                self._path_index = 1
                self._needs_attach = False
        if not attached:
            self.walkable = previous
            if self._roaming is not None:self._roaming.set_ground(previous)
            return False
        self._obstacles = obstacles
        self._reroutes.append(now)
        self._goal_progress = None
        self._goal_progress_at = self._active_age
        self._progress_anchor = None
        self._travel_demand = 0.
        self._recovery_count = 0
        self._history.clear()
        self._recovery_target = None
        self._moving_since = None
        return True

    def _turn(self, error, dt):
        if not self._lease.active:
            return
        if self._camera is not None:
            self._camera.submit(error, self.last_pose.observed_at,
                                limit=self._camera_rate or self._pack.humanize.turn_rate_deg_per_sec,
                                responsive=self._adaptive_goal,
                                deadband_deg=3. if self._pack.map_id=="de_nuke" else 1.5)
            return
        limit = min(360., self._camera_rate or self._pack.humanize.turn_rate_deg_per_sec)
        acceleration = (3600. if self._adaptive_goal else 2160.) if limit > 120 else 360.
        gain = (16. if self._adaptive_goal else 10.) if limit > 120 else 4.
        desired = max(-limit, min(limit, gain * error))
        change = max(-acceleration * dt, min(acceleration * dt, desired - self._turn_rate))
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

    @property
    def input_active(self):
        return self._lease.active and self._lease.allowed()

    def _continue_corridor(self,hint,now):
        permit=getattr(self,'_corridor_permit',None)
        if permit is None or not permit.allows(hint,now,self.walkable):return False
        if self._camera is not None:self._camera.stop()
        self._turn_rate=self._mouse_remainder=0.
        self._lease.renew(permit.expires_at-now)
        self._set_keys({'w'})
        self._continuity_at=hint.observed_at
        self.state,self.reason=NavState.SEEK_GOAL,'bounded_corridor_continuity'
        return True

    def tick(self, pose, *, now, paused, motion_hint=None, door_observation=None, **_compat):
        self._door_observation=door_observation
        goal_switched = False
        dt = .016 if self._last_tick is None else min(.1, max(0., now - self._last_tick))
        previous_tick = self._last_tick
        self._last_tick = now
        if self._adaptive_routing and self._keys & {"w","a","s","d"} and not paused and previous_tick is not None:
            self._travel_demand += min(.25,max(0.,now-previous_tick))
        self.last_pose = pose
        if (not pose.valid or pose.radar_mode != "visual" or pose.observed_at is None
                or not 0 <= now - pose.observed_at <= .25 or pose.confidence < .45
                or not all(math.isfinite(v) for v in (pose.x_norm, pose.y_norm, pose.yaw_deg, pose.confidence))):
            if paused:
                self._stop(NavState.PAUSED, "external_pause")
                return self._result(pose, now)
            if self._continue_corridor(motion_hint,now):
                if self._lost_since is None:self._lost_since=now
                self._observations.clear()
                return self._result(pose,now)
            self._stop(NavState.WAIT_POSE, "no_fresh_measured_pose")
            if self._lost_since is None:
                self._lost_since = now
            # Release input immediately, but retain the mission through a brief
            # visual dropout. A missed frame is not evidence of a respawn.
            if not self._adaptive_routing:
                self._path = ()
                self._history.clear()
            self._observations.clear()
            return self._result(pose, now)
        if self._layer_config:
            # Legacy measured callers without a layer retain the surface. The
            # product Mirage perception emits explicit 'unknown' when ambiguous.
            measured_layer=pose.layer_id or ('upper' if self._pack.map_id in ('de_mirage','de_cache') else None)
            if measured_layer not in self._layer_grounds:
                self._stop(NavState.WAIT_POSE, 'unconfirmed_floor')
                return self._result(pose,now)
            if measured_layer != self._active_layer:
                # A walking portal is a committed crossing, not a new random
                # mission halfway down a ramp. Only retain a nearby destination;
                # floor geometry and obstacles are still rebuilt for the new floor.
                carry_goal=None
                carry_age=self._active_age
                if (((self._pack.map_id=='de_vertigo' and self._route_goal.id.startswith('portal_'))
                        or (self._pack.map_id=='de_cache' and self._active_layer=='roof'
                            and measured_layer=='upper' and self._route_goal.id=='roof_drop_north'))
                        and self._last_measured_point is not None
                        and self._distance((pose.x_norm,pose.y_norm),self._last_measured_point)<40
                        and self._distance((pose.x_norm,pose.y_norm),(self._route_goal.x,self._route_goal.y))<120):
                    carry_goal=self._route_goal
                self.reload_pack(self._pack,layer_id=measured_layer)
                self.last_pose = pose
                self._last_tick = now
                if carry_goal is not None and self.walkable is not None:
                    path=self.walkable.plan((pose.x_norm,pose.y_norm),(carry_goal.x,carry_goal.y))
                    if path:
                        self._route_goal=carry_goal
                        self._path=path
                        self._path_index=1
                        self._needs_attach=False
                        self._active_age=carry_age
                        if self._roaming is not None:self._roaming.last_portal_at=carry_age
                self._log.info('nav: floor=%s; portal_continued=%s',pose.layer_id,carry_goal is not None and not self._needs_attach)
        # Perception/floor updates must run even while the mission planner or
        # combat owns input. Otherwise a lower-floor spawn is planned against
        # the upper mask and "no mission" keeps this controller paused forever.
        if paused:
            self._stop(NavState.PAUSED, "external_pause")
            return self._result(pose, now)
        self._corridor_permit = None
        self._continuity_at = None
        self._lease.renew(.25 - (now - pose.observed_at))
        if self.walkable is None:
            self._stop(NavState.BLOCKED, "missing_walkable_profile")
            return self._result(pose, now)
        point = (pose.x_norm, pose.y_norm)
        relocated = self._last_measured_point is not None and self._distance(point, self._last_measured_point) > 80
        long_loss = self._lost_since is not None and now-self._lost_since >= 1.
        # A short sensing outage is not a new spawn when the current measured
        # body is still next to its old position and its route remains visible.
        # Reattaching here discarded a usable route and added a second pause.
        if (long_loss and self._free_roam and self._pack.map_id == 'de_dust2'
                and self._path and self._last_measured_point is not None
                and self._distance(point,self._last_measured_point) <= 24.
                and self.walkable.contains(point) and self.walkable.visible(point,self._target)):
            long_loss = False
        if relocated or long_loss:
            self._spawn_samples.clear()
        if relocated or long_loss:
            self._needs_attach = True
            self._path = ()
            self._history.clear()
            self._observations.clear()
            self._recovery_target = None
            self._moving_since = None
            self._progress_anchor = None
            if relocated:
                self._travel_demand = 0.
                self._boundary_since = None
                self._boundary_origin = None
                self._restore_ground()
                self._reroutes.clear()
                self._blocked_at = None
                self._recovery_count = 0
        self._lost_since = None
        self._last_measured_point = point
        if self._adaptive_routing and self._obstacles:
            self._refresh_obstacles(point, now)
        if not self.walkable.contains(point):
            if (self._adaptive_routing and not self._base_walkable.contains(point)
                    and self._boundary_step(point,pose,now,dt)):
                return self._result(pose,now)
            self._stop(NavState.BLOCKED, "pose_outside_verified_ground" if not self._base_walkable.contains(point) else "temporary_obstacle_at_pose")
            self._path = ()
            return self._result(pose, now)
        self._boundary_target = None
        self._boundary_since = self._boundary_origin = None
        # A blocked attempt cannot re-arm itself merely because another tick ran.
        if self._blocked_at is not None:
            if self._distance(point, self._blocked_at) < 12:
                self._stop(NavState.BLOCKED, "recovery_exhausted")
                return self._result(pose, now)
            self._blocked_at = None
            self._recovery_count = 0
            self._path = ()
        if self._needs_attach and self._roaming is not None:
            if not self._spawn_samples or self._spawn_samples[-1][0] != pose.observed_at:
                self._spawn_samples.append((pose.observed_at, point))
            if (len(self._spawn_samples) < 3 or
                    any(self._distance(point, p) > 10 for _, p in self._spawn_samples)):
                self._stop(NavState.WAIT_POSE, "confirm_spawn_position")
                return self._result(pose, now)
            if not self._attach_roaming(point):
                self._stop(NavState.BLOCKED, "no_reachable_roaming_goal")
                return self._result(pose, now)
        if self._needs_attach and self._pack.strategy == "route_cycle":
            if not self._attach_route(point):
                self._stop(NavState.BLOCKED, "no_reachable_route_goal")
                return self._result(pose, now)
        self._active_age += dt
        if self._roaming is not None:
            self._roaming.observe(point, self._active_age)
        goal = (self._route_goal.x, self._route_goal.y)
        if self._history and self._distance(point, self._history[-1]) > 80:
            self._path = ()
            self._history.clear()
            self._recovery_target = None
        if not self._history or self._distance(point, self._history[-1]) >= 6:
            self._history.append(point)

        tolerance = min(10., max(3., self._route_goal.arrive_radius * min(self.walkable.width, self.walkable.height)))
        if self._distance(point, goal) <= tolerance and self.walkable.visible(point, goal):
            if self._roaming is not None:
                if not self._attach_roaming(point):
                    self._stop(NavState.BLOCKED, "no_reachable_roaming_goal")
                    return self._result(pose,now)
                goal = (self._route_goal.x,self._route_goal.y)
                goal_switched = True
            else:
                self._stop(NavState.AT_GOAL, "goal_reached")
                if self._at_goal_since is None:
                    self._at_goal_since = now
                switched = False
                if (self._pack.strategy == "route_cycle" and len(self._pack.goals) > 1
                        and now-self._at_goal_since >= self._pack.route.dwell_at_goal_sec):
                    self._route_index = (self._route_index+1) % len(self._pack.goals)
                    self._route_goal = self._pack.goals[self._route_index]
                    self._path = ()
                    self._at_goal_since = None
                    self._recovery_count = 0
                    switched = True
                return self._result(pose,now,switched=switched)
        self._at_goal_since = None

        if self._last_observation_at != pose.observed_at:
            self._observations.append(point)
            self._last_observation_at = pose.observed_at
        ordered_x = sorted(p[0] for p in self._observations)
        ordered_y = sorted(p[1] for p in self._observations)
        median = (ordered_x[len(ordered_x)//2], ordered_y[len(ordered_y)//2])
        if self._progress_anchor is None or self._distance(median, self._progress_anchor) >= 6.:
            self._progress_anchor = median
            self._travel_demand = 0.
            self._moving_since = now if self._keys & {"w", "a", "s", "d"} else None
        if not self._keys & {"w", "a", "s", "d"}:
            # A watchdog/focus stop is not time spent pushing into a wall.
            self._moving_since = None
        stuck = bool(self._keys & {"w", "a", "s", "d"}) and self._moving_since is not None and now - self._moving_since >= 1.2
        stuck = stuck or (self._adaptive_routing and self._travel_demand >= 1.2)
        if self._traversal.doors.busy(now):stuck=False
        if stuck:
            self._travel_demand = 0.
            self.release_keys()
            self._moving_since = None
            self._recovery_count += 1
            candidates = [p for p in reversed(self._history) if 12 <= self._distance(point, p) <= 60 and self.walkable.visible(point, p)]
            if self._recovery_target is not None or self._recovery_count > 2 or not candidates:
                if self._adaptive_routing and self._avoid_failed_direction(point, now):
                    self._stop(NavState.SEEK_GOAL, "obstacle_replanned")
                    return self._result(pose, now, stuck=True, switched=True)
                self._blocked_at = point
                self._stop(NavState.BLOCKED, "no_verified_recovery")
                return self._result(pose, now, stuck=True)
            self._last_failed_direction = self._target
            self._last_failed_origin = point
            self._recovery_target = candidates[0]
            self._recovery_started = now
            self._turn_rate = 0.

        reverse = False
        if self._recovery_target is not None:
            if self._distance(point, self._recovery_target) <= 5:
                self._recovery_target = None
                self._path = ()
                if self._adaptive_routing and self._avoid_failed_direction(point, now):
                    self._stop(NavState.SEEK_GOAL, "obstacle_replanned")
                    return self._result(pose, now, switched=True)
                self._stop(NavState.SEEK_GOAL, "recovered_replan")
                return self._result(pose, now)
            if now - self._recovery_started > 4:
                if self._adaptive_goal and self._avoid_failed_direction(point,now):
                    self._stop(NavState.SEEK_GOAL,"recovery_timeout_replanned")
                    return self._result(pose,now,stuck=True)
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
                if not self._path:
                    self._retry_after = now + 1.
                    self._stop(NavState.BLOCKED, "no_verified_route")
                    return self._result(pose, now)
                self._retry_after = 0.
            while (self._path_index < len(self._path) - 1
                   and self._distance(point, self._path[self._path_index]) < 24
                   and self.walkable.visible(point, self._path[self._path_index + 1])):
                self._path_index += 1
            self._target = self._lookahead_target(point) if self._adaptive_routing else self._path[self._path_index]
            self.state, self.reason = NavState.SEEK_GOAL, "follow_verified_route"
        if self._adaptive_routing and not reverse:
            remaining = self._distance(point,self._path[self._path_index]) + sum(self._distance(a,b) for a,b in zip(self._path[self._path_index:],self._path[self._path_index+1:]))
            if self._goal_progress is None or remaining < self._goal_progress-12:
                self._goal_progress, self._goal_progress_at = remaining, self._active_age
            elif self._active_age-self._goal_progress_at > 10:
                if self._avoid_failed_direction(point,now):
                    self._stop(NavState.SEEK_GOAL,"no_progress_replanned")
                    return self._result(pose,now,switched=True)
                self._blocked_at = point
                self._stop(NavState.BLOCKED,"no_progress_exhausted")
                return self._result(pose,now)
        if not self.walkable.visible(point, self._target):
            self._path = ()
            self._stop(NavState.BLOCKED, "segment_obstructed")
            return self._result(pose, now)
        px, py = self.walkable.pixel(point)
        tx, ty = self.walkable.pixel(self._target)
        bearing = math.degrees(math.atan2(ty - py, tx - px))
        if self._pack.map_id=='de_nuke' and not reverse:
            guided=self._traversal.doors.opening_heading(point,now=now,yaw=pose.yaw_deg,
                target=self._target,observation=getattr(self,"_door_observation",None))
            if guided is not None:bearing=guided
        heading = bearing + (180. if reverse else 0.)
        self._yaw_error = normalize_angle_deg(heading - pose.yaw_deg)
        self._turn(self._yaw_error, dt)
        probe = min(14.,self._distance(point,self._target))
        if self._adaptive_routing and not reverse:
            keys = self._travel_keys(point,pose.yaw_deg,bearing,probe)
        else:
            travel_yaw = math.radians(pose.yaw_deg + (180. if reverse else 0.))
            ahead = self.walkable.norm((px+math.cos(travel_yaw)*probe,py+math.sin(travel_yaw)*probe))
            moving_key = 's' if reverse else 'w'
            limit = 40. if moving_key in self._keys else 25.
            keys = {moving_key} if abs(self._yaw_error)<=limit and self.walkable.visible(point,ahead) else set()
        if keys:
            if self._moving_since is None:
                self._moving_since = now
                if not self._free_roam or self._progress_anchor is None:
                    self._progress_anchor = point
        else:
            self._moving_since = None
            self.reason = "align_measured_heading"
        self._set_keys(keys)
        if (self._free_roam and self._pack.map_id=='de_dust2' and keys=={'w'}
                and abs(self._yaw_error)<=8. and self._recovery_target is None
                and self._path and self._path_index<len(self._path)
                and motion_hint is not None):
            from nav.motion_continuity import CorridorPermit
            permit=CorridorPermit.create(pose,self.walkable,self._path[self._path_index])
            if permit is not None and permit.allows(motion_hint,now,self.walkable):
                self._corridor_permit=permit
                self._lease.renew(permit.expires_at-now)
        return self._result(pose, now, stuck=stuck, switched=goal_switched)
