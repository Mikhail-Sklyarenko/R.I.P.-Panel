"""Single-account Wingman test runtime, separate from DM lifecycle and buying."""
import json
import hashlib
import logging
import math
import os
from pathlib import Path
import sys
import time
import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:sys.path.append(str(ROOT))
from modules.wingman.engine import RoundEngine, Decision, Phase, valid_money
from modules.wingman.maps import profile_folder, map_ready
from modules.wingman.telemetry import Receiver
from modules.wingman.visual import HudReader, VisualEvidence
from modules.wingman.economy import Item, plan_buy, plan_grenades, PurchaseTransaction
from nav.input_lease import KeyLease
from nav.pack import NavGoal
from nav.walkable import WalkableMap
from nav.wingman_missions import MissionPlanner, Mission
from nav.wingman_ingress import WingmanIngress
from nav.wingman_recovery import WeaponSelection
from nav.wingman_objective_look import ObjectiveLook
from nav.wingman_bomb import BombReader, BombTracker

LOG = logging.getLogger("CS2Bot.wingman")


def enabled():
    return os.environ.get("CSGOBOT_GAME_MODE") == "wingman"


def load_ground(map_id):
    if not map_ready(map_id):raise ValueError("Wingman map profile is not ready: " + str(map_id))
    ground = WalkableMap.load(map_id,profile_folder(map_id))
    if ground is None:raise ValueError("Wingman map profile missing: " + str(map_id))
    return ground


class WingmanRuntime:
    def __init__(self, config, mouse, allowed):
        import pydirectinput as keys
        settings = json.loads(Path(os.environ["CSGOBOT_WINGMAN_GSI"]).read_text(encoding="utf-8"))
        import cv2
        from nav.paths import resolve_map_radar_path
        radar=cv2.cvtColor(cv2.imread(str(resolve_map_radar_path("de_inferno"))),cv2.COLOR_BGR2RGB)
        self.map_id="de_inferno"
        self.profile=profile_folder(self.map_id)
        self.bomb_tracker=BombTracker(BombReader(radar))
        self.bomb_point=None
        self.engine = RoundEngine()
        self.objective_look=ObjectiveLook(getattr(getattr(config,"fov",None),"x360",16364)/360.)
        self.objective_camera=None
        self.weapon_selection = WeaponSelection()
        self.hud = HudReader(ROOT / "resources/wingman/hud_ru_1280")
        self.objectives = json.loads((self.profile / "objectives.json").read_text())
        self.ingress = WingmanIngress(self.profile)
        self.planner = MissionPlanner(self.objectives)
        self.plan_executor = ThreadPoolExecutor(max_workers=1,thread_name_prefix="wingman-mission")
        self.planning = None
        self.planning_context = None
        self.active_role = None
        self.mission_layer = None
        self.floor_exit_visits = {}
        self.floor_exit_at = 0.
        self.floor_exit_index = 0.
        self.mission = None
        self.blocked_since = None
        self.next_plan_at = 0.
        self.mouse, self.keys, self.external_allowed = mouse, keys, allowed
        self.decision = Decision("waiting",True)
        self.snapshot = None
        self.frame = 0
        self.round_key = None
        self.next_goal = 0
        self.interaction = None
        self.defuse_confirmed = False
        self.defuse_confirmed_at = None
        self.interaction_at = 0.
        self.goal_id = None
        self.arrived_at = None
        self.purchase = None
        self.bought_key = None
        self.last_log = None
        self.radar_configured = False
        self.last_hud = VisualEvidence("unknown",0.,"no_verified_overlay",0.)
        self.receiver = Receiver(token=settings["token"],port=4019)
        self.lease = KeyLease(self._down,self._up,background=True,allowed=self.interaction_allowed)
        config.patrol.enabled = False
        config.autobuy.enabled = False
        config.team_detect.enabled = False
        config.map_detect.enabled = False
        config.look.enabled = False
        # Finish acquisition before firing; the DM tolerances cover small bodies.
        config.aim.aim_dead_zone_high = 2.
        config.aim.aim_dead_zone_low = 1.
        config.aim.aim_settle_px = 1.5
        config.aim.aim_unlock_px = 3.
        # The precision gate must not chase a heavily delayed EMA. At 14 Hz,
        # alpha .45 trails a 200px/s target by ~17px before mouse smoothing.
        config.aim.aim_smooth_alpha = .85
        config.aim.adaptive_smoothing = False
        config.aim.smoothing_factor = 1.25
        config.aim.aim_near_y_scale = 1.
        config.aim.aim_near_step_max_delta = 16
        config.aim.mouse_step_max_delta = 56
        # Visible enemies at the edge must acquire combat ownership too.
        config.aim.max_assist_distance = math.hypot(config.capture_region.width/2,
                                                   config.capture_region.height/2)
        config.aim.prioritize_heads = False
        config.aim.mouse_min_delta = 0
        config.aim.hold_release_grace_sec = 0.
        config.aim.auto_move = False
        config.aim.target_mode = "team"
        config.nav.enabled = True
        config.nav.pack_id = "inferno_visual"
        config.nav.read_only = False
        LOG.info("wingman_nuke_fix_5: ramp_geometry=on door_visual_heading=on spawn_wall_mask=on")
        LOG.info("wingman_fix_10: c4_offset_mask=on purple_body=on measured_landing=on defuse_look=on")

    def select_map(self, map_id):
        """Prepare all map data first; discard old round/plan state on commit.

        Caller must release input and replace the controller/perception in the
        same frame before allowing another navigation or combat tick.
        """
        if map_id==self.map_id:return
        if not map_ready(map_id):raise ValueError("Wingman profile is not ready: "+str(map_id))
        import cv2
        from nav.paths import resolve_map_radar_path
        folder=profile_folder(map_id)
        objectives=json.loads((folder/"objectives.json").read_text())
        if objectives.get("map_id")!=map_id:raise ValueError("Objective map mismatch")
        ingress=WingmanIngress(folder)
        radar=cv2.cvtColor(cv2.imread(str(resolve_map_radar_path(objectives.get("bomb_radar_map",map_id)))),cv2.COLOR_BGR2RGB)
        # Nuke's B-site target bounds are profile data, never Inferno A defaults.
        reader=BombReader(radar,site_bounds=objectives.get("bomb_bounds",(800,640,885,760)),
                          inferno_hud=map_id=="de_inferno",
                          hud_map_id="de_nuke_lower" if map_id=="de_nuke" else None)
        tracker=BombTracker(reader)
        self.lease.release();self._cancel_plan();self.bomb_tracker.close()
        self.map_id,self.profile=map_id,folder
        self.objectives,self.ingress=objectives,ingress
        self.planner=MissionPlanner(objectives);self.bomb_tracker=tracker
        self.bomb_point=None;self.snapshot=None;self.round_key=None
        self.mission=None;self.active_role=None;self.goal_id=None
        self.mission_layer=None;self.floor_exit_visits.clear();self.floor_exit_at=0.;self.floor_exit_index=0
        self.interaction=None;self.objective_look.reset();self.weapon_selection.reset()
        self.purchase=None;self.bought_key=None;self.next_plan_at=0.
        self.blocked_since=None;self.arrived_at=None;self.next_goal=0
        self.radar_configured=False;self.engine=RoundEngine()
        self.last_hud=VisualEvidence("unknown",0.,"map_changed",0.)
        self.decision=Decision("waiting",True,reason="map_changed")
        LOG.info("wingman_map_selected map=%s profile=%s",map_id,folder)

    def navigation_identity(self):
        profile = self.profile
        metadata = json.loads((profile / "navigation.json").read_text())
        return {"mode":"wingman_missions_v11", "map_id":self.map_id,"profile_path":str(profile),
                "profile_version":metadata["version"],"live_validated":metadata.get("live_validated",False),
                "mask_sha256":hashlib.sha256((profile / "walkable.png").read_bytes()).hexdigest(),
                "adaptive_obstacles":True,"ingress_routes":sorted(self.ingress.routes)}

    def _down(self,key):
        if key == "_attack":self.mouse.press("left")
        else:self.keys.keyDown(key)

    def _up(self,key):
        if key == "_attack":self.mouse.release("left")
        else:self.keys.keyUp(key)

    def interaction_allowed(self):
        s = self.receiver.state.snapshot()
        return bool(s and s.observation.own_player and s.observation.alive and
                    s.observation.phase == Phase.LIVE and s.observation.connected and self.external_allowed())

    def camera_allowed(self):
        return self.interaction is None and not self.restoring_camera and self.decision.combat and self.interaction_allowed()

    def observe(self, image, controller, *, now):
        self.snapshot = self.receiver.state.snapshot()
        # GSI may arrive after the capture timestamp passed by the caller.
        # Compare its unchanged arrival timestamp to the current receiver clock,
        # not the earlier frame time; stale-state limits still apply normally.
        now = max(now, self.receiver.state.clock())
        self.frame += 1
        if self.snapshot is None:
            self.decision = Decision("waiting",True,reason="waiting_for_fresh_game_state")
            self.lease.release()
            self.interaction = None
            self.objective_look.restore()
            self.bomb_tracker.update(image,context=None,now=now)
            self.bomb_point=None
            self._log_state()
            return self.decision
        s = self.snapshot
        o = replace(s.observation,sequence=self.frame)
        key = (o.match_id,o.round_number,o.team)
        if o.own_player and o.team in ("T", "CT") and key != self.round_key:
            same_match = self.round_key is not None and self.round_key[0] == key[0]
            self.lease.release()
            self.round_key = key
            if not same_match:
                self.planner = MissionPlanner(self.objectives)
                self.ingress = WingmanIngress(self.profile)
            preserve_obstacles = same_match and self.ingress.active is None
            self.ingress.reset_round()
            self.weapon_selection.reset()
            self.objective_look.reset()
            self._cancel_plan()
            self.active_role = None
            self.planner.reset_round()
            self.floor_exit_index = 0
            self.mission_layer = None
            self.mission = None
            self.blocked_since = None
            self.next_plan_at = 0.
            self.interaction = None
            self.next_goal = 0
            self.goal_id = None
            self.arrived_at = None
            self.purchase = None
            if controller is not None:
                controller.reset_round(now=now,preserve_obstacles=preserve_obstacles)
        if now-self.last_hud.observed_at >= .1:
            from PIL import Image
            self.last_hud = self.hud.read(Image.fromarray(image),now=now)
        self.decision = self.engine.update_with_visual(o,self.last_hud,now=now)
        # A visible buy menu vetoes gameplay, but cannot authorize a buy on its own.
        if (o.phase == Phase.FREEZE and o.own_player and o.alive and o.connected
                and o.team in ("T", "CT") and valid_money(o.money)
                and self.decision.state in ("buy", "freeze", "buy_menu")
                and self.last_hud.reason != "uncalibrated_resolution"
                and 0 <= now-o.observed_at <= self.engine.max_age):
            self.decision = Decision("buy",True,buy_key=f"{key}")
        if not (o.own_player and o.alive and o.phase == Phase.LIVE and o.connected) or self.decision.state not in ("live","defusing"):
            self.lease.release()
            self.interaction = None
            if o.own_player and o.alive and o.phase==Phase.LIVE:
                self.objective_look.restore()
            else:self.objective_look.reset()
        if not self.radar_configured and o.connected and o.own_player and o.alive and self.decision.state in ("buy","live"):
            self.decision = Decision("configure_radar",True)
        bomb_context=key if (o.own_player and o.alive and o.connected and o.team=='CT'
            and o.phase==Phase.LIVE and o.bomb=='planted') else None
        bomb_point=self.bomb_tracker.update(image,context=bomb_context,now=now)
        if bomb_point!=self.bomb_point:
            self.bomb_point=bomb_point
            self._cancel_plan()
            if self.interaction is None and self.active_role=='defuse':
                self.mission=None;self.goal_id=None;self.next_plan_at=0.
                self.planner.queue.clear()
            if bomb_point is not None:LOG.info('bomb_radar target=%s confirmed_frames=3',bomb_point)
        self.planner.bomb_point=self.bomb_point
        self._select_weapon(now)
        self._log_state()
        return self.decision

    def _select_weapon(self,now):
        if self.snapshot is None:return
        key=self.weapon_selection.choose(self.snapshot,now=now,
            allowed=self.decision.combat and self.interaction is None and self.interaction_allowed())
        if key is not None:
            self.keys.press(key)
            LOG.info('weapon_restore slot=%s active=%s',key,self.snapshot.active_weapon)

    @property
    def restoring_camera(self):
        return self.objective_look.restoring

    def objective_camera_allowed(self):
        return (self.interaction=='defuse' or self.restoring_camera) and self.interaction_allowed() and (
            self.decision.state in ('live','defusing'))

    def _log_state(self):
        key = (self.decision.state,self.decision.reason)
        if key != self.last_log:
            o = self.snapshot.observation if self.snapshot else None
            LOG.info("state=%s side=%s round=%s reason=%s",self.decision.state,
                     o.team if o else "?",o.round_number if o else "?",self.decision.reason)
            self.last_log = key

    def idle_tick(self, controller, *, now):
        if not self.external_allowed() or self.snapshot is None:
            self.lease.release()
            return
        if self.restoring_camera and self.objective_camera_allowed():
            if self.objective_camera is not None:
                self.objective_look.tick(lambda dx,dy:self.objective_camera.emit("objective",dx,dy),now=now)
            return
        if self.decision.state == "configure_radar":
            from modules.ui_nav.window import find_cs2_hwnd
            from modules.ui_nav.cs2_console import run_cs2_console_commands
            run_cs2_console_commands(find_cs2_hwnd(),'cl_radar_rotate 0; cl_radar_always_centered 1; bind "1" "slot1"; bind "2" "slot2"; bind "5" "slot5"; bind "e" "+use"')
            self.radar_configured = True
            LOG.info("Configured north-up radar for the calibrated navigation profile")
        elif self.decision.state == "buy":
            fresh = self.receiver.state.snapshot()
            if fresh is not None and fresh.observation.phase == Phase.FREEZE and fresh.observation.own_player and fresh.observation.alive and fresh.observation.connected:
                self.snapshot = fresh
                self._buy(now)
        elif self.interaction is not None and self.interaction_allowed():
            if self.interaction == "plant":
                if self.snapshot.active_weapon != "weapon_c4":
                    if not getattr(self,"equip_sent",False):
                        self.keys.press("5")
                        self.equip_sent = True
                    if now-self.interaction_at > 1.5:self._end_interaction(failed=True)
                    return
                self.lease.renew(.2)
                self.lease.set_keys({"_attack"})
            else:
                # Face the measured bomb and look down while trying +use.
                if self.last_hud.state == "defusing" and not self.defuse_confirmed:
                    self.defuse_confirmed=True
                    self.defuse_confirmed_at=now
                    LOG.info("defuse_confirmed elapsed_sec=%.2f",now-self.interaction_at)
                if self.objective_camera is not None:
                    self.objective_look.tick(lambda dx,dy:self.objective_camera.emit("objective",dx,dy),
                        now=now,confirmed=self.defuse_confirmed)
                self.lease.renew(.2)
                self.lease.set_keys({"e"})
            if self.interaction == "defuse" and self.last_hud.state == "defusing":
                self.defuse_confirmed = True
            limit = 12. if self.interaction == "defuse" and self.defuse_confirmed else (5. if self.interaction == "plant" else 2.6)
            anchor=self.defuse_confirmed_at if self.interaction=="defuse" and self.defuse_confirmed_at is not None else self.interaction_at
            if now-anchor > limit:self._end_interaction(failed=self.interaction == "plant")

    def _end_interaction(self, *, failed=False):
        self.lease.release()
        if self.interaction=="defuse":self.objective_look.restore()
        self.interaction = None
        self.planner.complete(failed=failed)
        self.mission = None
        self.next_goal += 1
        self.goal_id = None
        self.arrived_at = None

    def _set_nuke_floor_exit(self, controller, pose, *, now):
        """Commit to ordered ramp checkpoints, never alternate remote exits.

        The upper landing and ramp bottom overlap in XY. A direct goal at
        the bottom cannot express the required trip around the railing.
        Floor changes are still confirmed by perception, not by this route.
        """
        ground=controller.walkable
        points=self.objectives["upper_exit_route"]
        start=(pose.x_norm,pose.y_norm)
        index=min(self.floor_exit_index,len(points)-1)
        target=tuple(points[index])
        if math.dist(ground.pixel(start),target)<=3 and ground.visible(start,ground.norm(target)):
            if index==len(points)-1:
                # Hold the endpoint while awaiting measured lower-floor identity.
                # Do not turn back across the ramp or manufacture a floor change.
                return
            index+=1;self.floor_exit_index=index
            target=tuple(points[index]);self.mission=None
        if self.mission is not None and self.mission.action=="transition":return
        path=ground.plan(start,ground.norm(target))
        if not path:
            controller.release_keys()
            return
        self.mission=Mission(target,"transition")
        self.floor_exit_at=now
        controller.set_goal(NavGoal("wingman-floor-exit-"+str(index),*ground.norm(target),.002),
                            continue_motion=True,prepared_path=path)
        LOG.info("nuke_floor_exit layer=%s checkpoint=%d/%d target=%s",pose.layer_id,index+1,len(points),target)

    def set_objective(self, controller, *, now):
        if controller is None or controller.walkable is None or self.snapshot is None:return
        o = self.snapshot.observation
        if o.bomb in ("planted","defused","exploded") and self.interaction == "plant":self._end_interaction()
        if o.bomb in ("defused","exploded") and self.interaction == "defuse":self._end_interaction()
        if self.interaction is not None or self.restoring_camera or not self.decision.navigation:return
        pose=controller.last_pose
        if (pose is not None and pose.valid and pose.confidence>=.45 and pose.observed_at is not None
                and 0<=now-pose.observed_at<=.25):
            if self.map_id=="de_nuke":
                layer=pose.layer_id
                if layer!=self.mission_layer:
                    self._cancel_plan();self.mission=None;self.active_role=None
                    self.goal_id=None;self.next_plan_at=0.;self.mission_layer=layer
                    self.floor_exit_index=(1 if pose.y_norm*1023<326 else 2) if layer=="ramp" else 0
                if layer!="lower":
                    if layer not in ("upper","ramp"):controller.release_keys();return
                    self._set_nuke_floor_exit(controller,pose,now=now)
                    return
            status,route=self.ingress.update(controller,pose,team=o.team,bomb=o.bomb,now=now)
            if status in ('started','active','retreating'):
                if status in ('started','retreating'):
                    self._cancel_plan()
                    LOG.info("ingress=%s status=%s",route,status)
                self.mission=Mission(tuple(controller.walkable.pixel((controller._route_goal.x,controller._route_goal.y))),'ingress')
                return
            if status in ('finished','aborted'):
                self._cancel_plan()
                self.mission=None
                self.active_role=None
                LOG.info("ingress=%s status=%s",route,status)
        if self.map_id=="de_nuke" and self.mission_layer in ("upper","ramp"):
            # A short perception gap must not turn a ramp mission into a B
            # mission on the old floor or rotate between both ramp exits.
            controller.release_keys()
            return
        role = self.planner.role_for(o.team,o.bomb)
        if role != self.active_role:
            self.active_role = role
            self._cancel_plan()
            # A bomb event preempts patrol immediately, even during pose loss.
            self.mission = None
            self.goal_id = None
            self.blocked_since = None
            self.next_plan_at = 0.
            controller.release_keys()
        pose = controller.last_pose
        if (pose is None or not pose.valid or pose.confidence < .45 or pose.observed_at is None
                or not 0 <= now-pose.observed_at <= .25):return
        ground = controller.walkable
        start = (pose.x_norm,pose.y_norm)
        if self.mission is not None:
            target = self.mission.point
            threshold = 4 if self.mission.action=="defuse" else 7 if self.mission.action=="plant" else 14
            if self.map_id=="de_nuke" and self.mission.action=="approach":threshold=4
            distance=math.dist(ground.pixel(start),target)
            age=getattr(controller,"_active_age",0.)
            stalled=False
            if self.map_id=="de_nuke":
                if distance<getattr(self,"mission_best_distance",float("inf"))-8:
                    self.mission_best_distance=distance;self.mission_progress_age=age
                stalled=age-getattr(self,"mission_progress_age",age)>12.
            arrived = distance <= threshold and ground.visible(start,ground.norm(target))
            if arrived:
                if self.mission.action in ("plant","defuse"):
                    self.interaction = self.mission.action
                    self.interaction_at = now
                    self.defuse_confirmed = False
                    self.defuse_confirmed_at = None
                    self.equip_sent = False
                    if self.interaction=='defuse':
                        aim=self.bomb_point or target
                        x,y=ground.pixel(start)
                        desired=math.degrees(math.atan2(aim[1]-y,aim[0]-x)) if math.dist(aim,(x,y))>1 else pose.yaw_deg
                        error=(desired-pose.yaw_deg+180)%360-180
                        self.objective_look.begin(error,now=now)
                        LOG.info('defuse_prepare distance_px=%.1f yaw_error=%.1f look_down=true',math.dist(aim,(x,y)),error)
                    controller.release_keys()
                    LOG.info("interaction=%s target=%s",self.interaction,target)
                    return
                self.planner.complete()
                self.mission = None
                self.goal_id = None
                self.next_goal += 1
            elif stalled or controller.reason in ("recovery_exhausted","no_verified_route","no_reachable_route_goal",
                                       "no_verified_recovery","recovery_timeout","no_progress_exhausted"):
                if self.blocked_since is None:self.blocked_since=now
                if now-self.blocked_since < 2:return
                LOG.warning("mission_unreachable target=%s reason=%s",target,controller.reason)
                self._cancel_plan()
                self.planner.complete(failed=True)
                self.mission = None
                self.goal_id = None
                self.next_goal += 1
            else:self.blocked_since=None
        context = (self.round_key,role,id(ground))
        if self.planning is not None and self.planning_context != context:self._cancel_plan()
        if self.mission is not None:
            if self.mission.action in ("patrol","support","guard","approach") and self.planning is None:
                self._request_plan(ground,ground.norm(self.mission.point),o,context,prefetch=True)
            return
        if now < self.next_plan_at:return
        prepared_path=()
        if self.planning is not None:
            if not self.planning.done():return
            future=self.planning
            self.planning=None
            try:self.planner,self.mission,prepared_path=future.result()
            except Exception:
                LOG.exception("mission_plan_failed")
                self.mission=None
            if self.mission is None:
                controller.release_keys()
                self.next_plan_at=now+1.
                LOG.warning("mission_wait role=%s reason=no_reachable_candidate",role)
                return
        else:
            planning_start = start if ground.contains(start) else ground.boundary_exit(start)
            if planning_start is None:
                controller.release_keys()
                self.next_plan_at=now+1.
                return
            self._request_plan(ground,planning_start,o,context)
            return
        self.blocked_since = None
        self.mission_origin = ground.pixel(start)
        self.mission_best_distance=math.dist(self.mission_origin,self.mission.point)
        self.mission_progress_age=getattr(controller,"_active_age",0.)
        self.goal_id = f"wingman-{o.round_number}-{self.mission.action}-{self.next_goal}"
        point = ground.norm(self.mission.point)
        # Next tick checks the new heading/footprint; the existing input lease
        # cannot outlive pose freshness while a mission is handed over.
        radius=.003 if self.mission.action=="defuse" else .005
        if self.map_id=="de_nuke" and self.mission.action=="approach":radius=.002
        controller.set_goal(NavGoal(self.goal_id,*point,radius),continue_motion=True,prepared_path=prepared_path)
        LOG.info("mission=%s target=%s side=%s",self.mission.action,self.mission.point,o.team)
        if self.mission.action in ("patrol","support","guard","approach"):
            self._request_plan(ground,point,o,context,prefetch=True)

    def _cancel_plan(self):
        if self.planning is not None:self.planning.cancel()
        self.planning=None
        self.planning_context=None

    def _request_plan(self,ground,start,o,context,*,prefetch=False):
        planner=copy.deepcopy(self.planner)
        if prefetch:planner.complete()
        # Workers never mutate the live strategy or its map edge cache.
        planning_ground=copy.copy(ground)
        planning_ground._edge_cache=dict(ground._edge_cache)
        incoming=None
        if prefetch and getattr(self,"mission_origin",None) is not None:
            x,y=ground.pixel(start)
            incoming=(x-self.mission_origin[0],y-self.mission_origin[1])
        def compute():
            for _ in range(3):
                mission=planner.choose(planning_ground,start,team=o.team,bomb=o.bomb,incoming=incoming)
                if mission is None:return planner,None,()
                route=planning_ground.plan(start,planning_ground.norm(mission.point))
                if route:return planner,mission,route
                planner.complete(failed=True)
            return planner,None,()
        self.planning_context=context
        self.planning=self.plan_executor.submit(compute)

    def _buy(self, now):
        s = self.snapshot
        owned = set(s.weapons)
        if s.armor > 0:owned.add("vest")
        if s.helmet:owned.add("vesthelm")
        if s.defusekit:owned.add("defuser")
        if self.bought_key != self.round_key:
            self.bought_key = self.round_key
            catalog = {i.name:i for i in (
                Item("vest",650,"armor"), Item("weapon_ak47",2700,"primary",("T",)),
                Item("weapon_m4a1_silencer",2900,"primary",("CT",)),
                Item("weapon_mac10",1050,"primary",("T",)), Item("weapon_mp9",1250,"primary",("CT",)),
                Item("defuser",400,"kit",("CT",)))}
            primary = any(w in owned for w in ("weapon_ak47","weapon_m4a1","weapon_m4a1_silencer","weapon_awp","weapon_ssg08","weapon_galilar","weapon_famas","weapon_mp9","weapon_mac10","weapon_p90","weapon_mp7","weapon_mp5sd","weapon_ump45","weapon_bizon","weapon_nova","weapon_xm1014","weapon_mag7","weapon_sawedoff","weapon_m249","weapon_negev"))
            slots = {"primary"} if primary else set()
            if s.armor > 0:slots.add("armor")
            if s.defusekit:slots.add("kit")
            plan = plan_buy(money=s.observation.money,team=s.observation.team,owned=slots,catalog=catalog,
                priority=("vest","weapon_ak47","weapon_m4a1_silencer","weapon_mac10","weapon_mp9","defuser"))
            remaining = s.observation.money - sum(item.price for item in plan)
            grenades = plan_grenades(money=remaining,team=s.observation.team,
                                    weapons=s.weapons,grenade_count=s.grenade_count)
            plan += grenades
            self.purchase = PurchaseTransaction(plan)
            LOG.info("buy_grenades remaining_after_core=%s items=%s",remaining,
                     [item.name for item in grenades])
            LOG.info("buy_plan items=%s budget=%s",[i.name for i in plan],s.observation.money)
        if self.purchase is None:
            LOG.warning("buy skipped: previous transaction unavailable; no replay")
            return
        item = self.purchase.next_item(now=now,money=s.observation.money,owned=owned,buy_allowed=True)
        if item is None:return
        from modules.ui_nav.window import find_cs2_hwnd
        from modules.ui_nav.cs2_console import run_cs2_console_commands
        alias = item.name.removeprefix("weapon_")
        try:
            run_cs2_console_commands(find_cs2_hwnd(),"buy "+alias)
            LOG.info("buy_sent item=%s awaiting_confirmation",item.name)
        except Exception:
            self.purchase.failed = True
            raise

    def close(self):
        self._cancel_plan()
        self.plan_executor.shutdown(wait=False,cancel_futures=True)
        self.lease.close()
        self.receiver.close()
        self.bomb_tracker.close()
