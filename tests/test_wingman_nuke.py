"""Nuke regression: real HUD crops plus synthetic round/input contracts."""
from pathlib import Path
from types import SimpleNamespace as NS
from dataclasses import replace
import json
import time
import cv2
import numpy as np
import pytest
from tests.test_wingman_live import runtime, payload

ROOT=Path(__file__).resolve().parents[1]
FIX=ROOT/'tests/fixtures/wingman/nuke'

def frame(t):
    return cv2.cvtColor(cv2.imread(str(FIX/f'{t}.png')),cv2.COLOR_BGR2RGB)


def test_nuke_profile_objectives_connected_on_their_own_floor(csgobot_path):
    from nav.walkable import WalkableMap
    o=json.loads((ROOT/'resources/wingman/nuke/objectives.json').read_text())
    grounds={'lower':WalkableMap.load('de_nuke_lower'),'upper':WalkableMap.load('de_nuke')}
    for key,points in o.items():
        if not key.endswith('_points'):continue
        g=grounds['upper' if key=='upper_exit_points' else 'lower']
        start=g.norm((610,380) if key=='upper_exit_points' else (710,721))
        for xy in points:
            assert g.contains(g.norm(xy)),(key,xy)
            assert g.plan(start,g.norm(xy)),(key,xy)
    g=grounds['lower']
    assert not g.visible(g.norm((620,520)),g.norm((656,520)))
    assert g.visible(g.norm((620,555)),g.norm((656,555)))
    assert not g.contains(g.norm((584,581)))  # Reactor, not open floor.


def test_nuke_orange_door_requires_current_scene_and_map(csgobot_path):
    from nav.door_actions import observe_door,DoorActions,DoorObservation
    assert observe_door(frame(48),'de_nuke',1).red_panel
    assert observe_door(frame(88),'de_nuke',1).red_panel
    assert not observe_door(frame(49),'de_nuke',1).red_panel
    assert not observe_door(frame(89),'de_nuke',1).red_panel
    zones=json.loads((ROOT/'resources/nav/profiles/de_nuke/traversal.json').read_text())['zones']
    d=DoorActions(z for z in zones if z['action']=='use_door')
    p=(648/1023,555/1023);target=(620/1023,555/1023)
    def apply(obs,now=1):return d.apply({'w'},p,now=now,yaw=180,target=target,observation=obs)
    assert 'e' not in apply(DoorObservation(1,'de_inferno',True))
    assert 'e' not in apply(DoorObservation(0,'de_nuke',True))
    assert 'e' in apply(DoorObservation(1,'de_nuke',True))
    assert 'e' not in apply(DoorObservation(1.2,'de_nuke',True),1.2)
    d.reset()
    assert 'e' not in apply(DoorObservation(2,'de_nuke',True),2)


def test_radar_geometry_recovers_only_with_visible_disk(csgobot_path):
    from nav.minimap_reader import MinimapReader
    from nav.calibration import load_calibration
    from nav.paths import resolve_calibration_path
    from nav.radar_geom import visible_ring_support,RadarCircle
    r=MinimapReader(load_calibration(resolve_calibration_path()));r.competitive_markers=True
    for t in (121,122,124,123,135):assert r.read(frame(t)).valid,t
    assert not r.read(frame(139)).valid
    assert not r.read(frame(209)).valid
    assert not visible_ring_support(np.zeros((720,1280,3),np.uint8),RadarCircle(130,130,108))


def test_conflicting_floor_geometry_cannot_vote_by_confidence(csgobot_path,monkeypatch):
    import nav.nuke_localizer as n
    from nav.visual_localizer import Registration
    monkeypatch.setattr(n,'select_layer',lambda *a:None)
    m=np.array([[1.,0.,0.],[0.,1.,0.]])
    a=Registration(m,.9,20,0.,'test')
    assert n.choose_floor(None,None,{'upper':a,'lower':a},{}) is None
    assert n.choose_floor(None,None,{'lower':a},{}).layer_id=='lower'
    assert n.choose_floor(None,None,{'lower':replace(a,confidence=.3)}, {}) is None


def test_recorded_hud_floor_identity(csgobot_path):
    from nav.minimap_reader import MinimapReader
    from nav.calibration import load_calibration
    from nav.paths import resolve_calibration_path
    from nav.visual_localizer import VisualLocalizer
    from nav.hud_mask import exclude_range_ring
    r=MinimapReader(load_calibration(resolve_calibration_path()));r.competitive_markers=True
    loc=VisualLocalizer('de_nuke')
    for t,layer,expected in ((8,'lower',(711,723)),(43,'lower',(657,648)),(116,'upper',(619,359)),(150,'upper',(608,392)),(161,'ramp',(596,343)),(162,'ramp',(593,379))):
        image=frame(t);assert r.read(image).valid
        crop,cx,cy,rad=r._crop_from_circle(image,r.last_circle)
        yy,xx=np.ogrid[:crop.shape[0],:crop.shape[1]];dist=(xx-cx)**2+(yy-cy)**2
        mask=np.uint8((dist<(rad-8)**2)&(dist>22**2))*255
        mask[cv2.dilate(np.uint8(cv2.cvtColor(crop,cv2.COLOR_RGB2HSV)[:,:,1]>160),np.ones((7,7),np.uint8))>0]=0
        exclude_range_ring(mask,cx,cy,rad)
        a=loc.register(crop,mask)
        assert a is not None and a.layer_id==layer,(t,a)
        xy=a.matrix@np.array([*r.last_icon_xy,1.])
        assert np.linalg.norm(xy-np.array(expected))<12,(t,xy)


def test_switch_releases_input_and_discards_old_mission(runtime,monkeypatch):
    from nav import wingman_runtime as wr
    from nav.wingman_missions import Mission
    r,s,events,focus,config=runtime
    monkeypatch.setattr(wr,'map_ready',lambda name:True)
    assert s.accept(payload())
    r.decision=wr.Decision("live",False,navigation=True,combat=True)
    r.lease.renew(.2);r.lease.set_keys({'w'})
    r.mission=Mission((850,700),'plant');r.interaction='plant';r.bomb_point=(850,700)
    r.mission_layer='lower';r.floor_exit_visits[(614,454)]=3
    r.select_map('de_nuke')
    assert ('up','w') in events
    assert r.map_id=='de_nuke' and r.objectives['site']==[584,550]
    assert r.mission is None and r.interaction is None and r.bomb_point is None
    assert r.mission_layer is None and not r.floor_exit_visits
    assert not r.decision.navigation and not r.decision.combat
    assert r.bomb_tracker.reader.site_bounds==(543,500,627,607)
    r.select_map('de_inferno')
    assert r.objectives['map_id']=='de_inferno'
    assert r.bomb_tracker.reader.site_bounds==(800,640,885,760)


def test_map_change_starts_new_epoch_even_when_round_number_restarts(monkeypatch):
    from modules.wingman import maps
    from modules.wingman.telemetry import GameState
    monkeypatch.setattr(maps,'map_ready',lambda name:name in ('de_inferno','de_nuke'))
    s=GameState();assert s.accept(payload(map={'round':7}))
    before=s.snapshot().observation.match_id
    assert s.accept(payload(map={'name':'de_nuke','round':0}))
    o=s.snapshot().observation
    assert o.connected and o.map_id=='de_nuke' and o.match_id!=before


def test_ramp_exit_keeps_ordered_checkpoints_and_enters_slope(runtime,monkeypatch):
    from nav import wingman_runtime as wr
    from nav.walkable import WalkableMap
    from nav.pose import PoseResult
    from modules.wingman.engine import Decision
    r,s,events,focus,config=runtime;monkeypatch.setattr(wr,'map_ready',lambda name:True)
    r.select_map('de_nuke');assert s.accept(payload())
    r.snapshot=s.snapshot();r.decision=Decision('live',False,navigation=True,combat=True)
    g=WalkableMap.load('de_nuke');calls=[]
    c=NS(walkable=g,last_pose=PoseResult(*g.norm((610,380)),90,.99,True,20,'visual',None,1.,'upper'),
         release_keys=lambda:None,set_goal=lambda goal,**kw:calls.append(goal))
    r.set_objective(c,now=1.);first=r.mission.point
    r.set_objective(c,now=2.)  # Stale pose: keep the transition, do not reroute.
    assert r.mission.point==first and len(calls)==1
    c.last_pose=replace(c.last_pose,observed_at=12.)
    r.set_objective(c,now=12.)
    assert len(calls)==1 and r.mission.point==first  # No timer-based ping-pong.
    c.last_pose=replace(c.last_pose,x_norm=g.norm(first)[0],y_norm=g.norm(first)[1],observed_at=12.1)
    r.set_objective(c,now=12.1)
    assert len(calls)==2 and r.mission.point==(596,315)
    ramp=WalkableMap.load('de_nuke_ramp');c.walkable=ramp
    c.last_pose=replace(c.last_pose,x_norm=ramp.norm((596,330))[0],y_norm=ramp.norm((596,330))[1],layer_id='ramp',observed_at=12.2)
    r.set_objective(c,now=12.2)
    assert r.mission.point==(596,401) and r.mission_layer=='ramp'
    assert ramp.visible(ramp.norm((596,330)),ramp.norm(r.mission.point))


def test_controller_follows_nuke_door_and_ramp_routes_without_mask_collisions(csgobot_path):
    import math
    from nav.visual_controller import VisualNavController
    from nav.pack import load_nav_pack,NavGoal
    from nav.paths import resolve_nav_pack_path
    from nav.pose import PoseResult
    pack=load_nav_pack(resolve_nav_pack_path('nuke_wingman'));held=set();yaw=[0.]
    c=VisualNavController(pack,NS(fov=NS(x360=3600)),held.add,held.discard,
        lambda dx,dy:yaw.__setitem__(0,yaw[0]+dx/10),adaptive_goal=True,camera_rate=360)
    c.reload_pack(pack,layer_id='lower');g=c.walkable;pos=np.array([710.,721.]);now=1.
    try:
        for target in ((518,610),(568,548),(651,552),(674,507),(622,440),(547,438),(604,572),(710,721)):
            c.set_goal(NavGoal('simulation',*g.norm(target),.008),continue_motion=True)
            for i in range(500):
                now+=.05
                pose=PoseResult(*g.norm(pos),yaw[0],.99,True,20,'visual',None,now,'lower')
                c.tick(pose,now=now,paused=False)
                if np.linalg.norm(pos-target)<11:break
                forward=('w'in held)-('s'in held);side=('d'in held)-('a'in held)
                angle=math.radians(yaw[0]);length=max(1.,math.hypot(forward,side))
                nxt=pos+2*np.array([forward*math.cos(angle)-side*math.sin(angle),
                                    forward*math.sin(angle)+side*math.cos(angle)])/length
                assert g.visible(g.norm(pos),g.norm(nxt)),(target,pos,nxt)
                pos=nxt
            assert np.linalg.norm(pos-target)<11,(target,pos,c.reason)
    finally:c.close()


def test_gallery_does_not_jump_while_ground_movement_progresses(csgobot_path):
    from nav.traversal_actions import TraversalActions
    a=TraversalActions.load('de_nuke')
    def tick(x,y,t):return a.apply({'w'},(x/1023,y/1023),now=t,yaw=0,target=(600/1023,y/1023))
    assert 'space' not in tick(544,540,1.)
    assert 'space' not in tick(548,540,1.2)
    assert 'space' not in tick(552,540,1.4)
    assert 'space' in tick(552,540,1.8)
    a.reset()
    assert 'space' not in tick(552,540,2.)


def test_live_lower_spawn_can_plan_while_controller_waits_for_mission(runtime):
    """Reproduce the real worker order: plan first, then paused nav tick."""
    from nav.visual_controller import VisualNavController
    from nav.pack import load_nav_pack
    from nav.paths import resolve_nav_pack_path
    from nav.pose import PoseResult
    from modules.wingman.engine import Decision
    r,s,events,focus,config=runtime
    r.select_map('de_nuke')
    assert s.accept(payload(map={'name':'de_nuke'}))
    r.snapshot=s.snapshot();r.decision=Decision('live',False,navigation=True,combat=True)
    held=set();pack=load_nav_pack(resolve_nav_pack_path('nuke_wingman'))
    c=VisualNavController(pack,NS(fov=NS(x360=3600)),held.add,held.discard,lambda dx,dy:None,adaptive_goal=True)
    try:
        t=time.monotonic()
        r.set_objective(c,now=t)
        assert r.mission is None
        pose=PoseResult(710/1023,721/1023,-90,.83,True,20,'visual',None,t,'lower')
        c.tick(pose,now=t,paused=True)
        assert c._active_layer=='lower'
        assert not held  # Preparing the floor must not bypass pause.
        r.set_objective(c,now=t)
        assert r.planning is not None
        r.planning.result(timeout=5)
        t=time.monotonic();c.last_pose=replace(pose,observed_at=t)
        r.set_objective(c,now=t)
        assert r.mission is not None and c._path
        result=c.tick(c.last_pose,now=t,paused=False)
        assert c.reason!='external_pause'
        assert held & {'w','a','s','d'}
    finally:c.close()


def test_new_gsi_arrival_after_frame_capture_is_not_out_of_order(runtime):
    r,s,events,focus,config=runtime
    frame_time=time.monotonic()-.1
    assert s.accept(payload())
    decision=r.observe(np.zeros((720,1280,3),np.uint8),None,now=frame_time)
    assert decision.state=='live' and decision.navigation
    # This fix does not turn genuinely expired GSI into a live state.
    s.clock=lambda:time.monotonic()+1.
    assert r.observe(np.zeros((720,1280,3),np.uint8),None,now=time.monotonic()).state=='waiting'


def test_t_spawn_route_cannot_cut_through_barrel_corner(csgobot_path):
    from nav.walkable import WalkableMap
    g=WalkableMap.load('de_nuke_lower')
    assert not g.contains(g.norm((677,674)))
    assert not g.visible(g.norm((710,721)),g.norm((655,635)))
    path=g.plan(g.norm((710,721)),g.norm((650,555)))
    assert path
    assert all(g.visible(a,b) for a,b in zip(path,path[1:]))
    assert not g.contains(g.norm((615,583)))


def test_nuke_uses_both_entries_across_rounds(csgobot_path):
    from nav.walkable import WalkableMap
    from nav.wingman_missions import MissionPlanner
    import random
    g=WalkableMap.load('de_nuke_lower')
    catalog=json.loads((ROOT/'resources/wingman/nuke/objectives.json').read_text())
    p=MissionPlanner(catalog,rng=random.Random(2));chosen=[]
    for _ in range(6):
        p.reset_round()
        mission=p.choose(g,g.norm((710,721)),team='T',bomb='carried_self')
        assert mission is not None
        chosen.append(p.last_entry)
        points=[g.norm((710,721))]+[g.norm(m.point) for m in p.queue]
        assert all(g.plan(a,b) for a,b in zip(points,points[1:]))
        assert p.queue[-1].action=='plant'
    assert set(chosen)=={'decon','double_doors'}
    assert all(a!=b for a,b in zip(chosen,chosen[1:]))


def test_nuke_stalled_mission_is_abandoned_using_active_navigation_time(runtime):
    from collections import deque
    from nav.walkable import WalkableMap
    from nav.pose import PoseResult
    from nav.wingman_missions import Mission
    from modules.wingman.engine import Decision
    r,s,events,focus,config=runtime;r.select_map('de_nuke')
    assert s.accept(payload(map={'name':'de_nuke'}));r.snapshot=s.snapshot()
    r.decision=Decision('live',False,navigation=True,combat=True)
    r.mission_layer='lower';r.active_role='plant'
    r.mission=Mission((604,572),'plant');r.planner.queue=deque([r.mission])
    g=WalkableMap.load('de_nuke_lower');target=r.mission.point
    r.mission_best_distance=1.;r.mission_progress_age=0.
    c=NS(walkable=g,last_pose=PoseResult(*g.norm((550,520)),0,.9,True,20,'visual',None,100.,'lower'),
         _active_age=0.,reason='follow_verified_route',release_keys=lambda:None)
    # Long wall-clock passage during combat/pause does not expire a mission.
    r.set_objective(c,now=100.);assert r.mission is not None
    c._active_age=20.
    r.set_objective(c,now=100.)
    c.last_pose=replace(c.last_pose,observed_at=102.1)
    r.set_objective(c,now=102.1)
    assert target in r.planner.failed and r.mission is None


def test_nuke_approach_does_not_cut_corner_fourteen_pixels_early(runtime):
    from collections import deque
    from nav.walkable import WalkableMap
    from nav.pose import PoseResult
    from nav.wingman_missions import Mission
    from modules.wingman.engine import Decision
    r,s,events,focus,config=runtime;r.select_map('de_nuke')
    assert s.accept(payload(map={'name':'de_nuke'}));r.snapshot=s.snapshot()
    r.decision=Decision('live',False,navigation=True,combat=True)
    r.mission_layer='lower';r.active_role='plant'
    r.mission=Mission((655,646),'approach');r.planner.queue=deque([r.mission])
    g=WalkableMap.load('de_nuke_lower')
    c=NS(walkable=g,last_pose=PoseResult(*g.norm((655,658)),0,.9,True,20,'visual',None,100.,'lower'),
         _active_age=0.,reason='follow_verified_route',release_keys=lambda:None)
    r.set_objective(c,now=100.)
    assert r.mission is not None and r.mission.point==(655,646)


def test_nuke_upper_landing_and_ramp_are_separate_navigation_surfaces(csgobot_path):
    from nav.walkable import WalkableMap
    upper=WalkableMap.load('de_nuke');ramp=WalkableMap.load('de_nuke_ramp')
    assert upper.plan(upper.norm((608,392)),upper.norm((610,315)))
    assert upper.visible(upper.norm((610,315)),upper.norm((596,315)))
    assert not upper.contains(upper.norm((596,350)))
    assert ramp.visible(ramp.norm((596,315)),ramp.norm((596,401)))
    assert not ramp.contains(ramp.norm((620,350)))


def test_ramp_exit_goal_cannot_stop_before_floor_handoff(csgobot_path):
    from nav.nuke_localizer import NukeDenseMatcher
    o=json.loads((ROOT/'resources/wingman/nuke/objectives.json').read_text())
    x,y=o['upper_exit_route'][-1]
    assert not NukeDenseMatcher.on_ramp((x,y-3))


def test_nuke_startup_preflight_accepts_shipped_three_layer_profile(csgobot_path):
    from nav.preflight import run_nav_preflight
    result=run_nav_preflight(pack_id='nuke_wingman')
    assert result['ok'],result['errors']
    assert result['map_id']=='de_nuke'


@pytest.mark.parametrize('mutation',['missing_ramp','wrong_ramp','unknown_layer','wrong_map'])
def test_nuke_preflight_rejects_incompatible_layer_profiles(csgobot_path,tmp_path,monkeypatch,mutation):
    from nav import paths
    from nav.preflight import run_nav_preflight
    original=paths.resolve_visual_profile_file
    data=json.loads(original('de_nuke','layers.json').read_text())
    if mutation=='missing_ramp':data['layers'].pop('ramp')
    elif mutation=='wrong_ramp':data['layers']['ramp']='de_inferno'
    elif mutation=='unknown_layer':data['layers']['roof']='de_nuke_ramp'
    else:data['map_id']='de_inferno'
    fixture=tmp_path/'layers.json';fixture.write_text(json.dumps(data))
    monkeypatch.setattr(paths,'resolve_visual_profile_file',
        lambda mid,name:fixture if mid=='de_nuke' and name=='layers.json' else original(mid,name))
    result=run_nav_preflight(pack_id='nuke_wingman')
    assert not result['ok']
    assert any('Invalid navigation layer configuration for de_nuke' in error for error in result['errors'])


def test_nuke_preflight_requires_actual_ramp_mask(csgobot_path,monkeypatch):
    from nav.walkable import WalkableMap
    from nav.preflight import run_nav_preflight
    original=WalkableMap.load
    monkeypatch.setattr(WalkableMap,'load',lambda mid:None if mid=='de_nuke_ramp' else original(mid))
    result=run_nav_preflight(pack_id='nuke_wingman')
    assert not result['ok']
    assert any('Missing navigation floor mask: de_nuke_ramp' in error for error in result['errors'])


@pytest.mark.parametrize('t',[214,230,308])
def test_live_test_ramp_geometry_is_not_rejected_as_lower_floor(csgobot_path,t):
    from nav.visual_localizer import VisualLocalizer
    from nav.minimap_reader import MinimapReader
    from nav.calibration import load_calibration
    from nav.paths import resolve_calibration_path
    from nav.hud_mask import exclude_range_ring
    reader=MinimapReader(load_calibration(resolve_calibration_path()));reader.competitive_markers=True
    image=frame('live5_'+str(t));assert reader.read(image).valid
    crop,cx,cy,rad=reader._crop_from_circle(image,reader.last_circle)
    yy,xx=np.ogrid[:crop.shape[0],:crop.shape[1]];dist=(xx-cx)**2+(yy-cy)**2
    mask=np.uint8((dist<(rad-8)**2)&(dist>22**2))*255
    mask[cv2.dilate(np.uint8(cv2.cvtColor(crop,cv2.COLOR_RGB2HSV)[:,:,1]>160),np.ones((7,7),np.uint8))>0]=0
    exclude_range_ring(mask,cx,cy,rad)
    result=VisualLocalizer('de_nuke').register(crop,mask)
    assert result is not None and result.layer_id=='ramp'
    xy=result.matrix@np.r_[reader.last_icon_xy,1.]
    assert 590<xy[0]<606 and 330<xy[1]<370


def test_t_exit_and_bottom_garage_forbid_wall_shortcuts(csgobot_path):
    from nav.walkable import WalkableMap
    g=WalkableMap.load('de_nuke_lower')
    assert not g.visible(g.norm((710,721)),g.norm((678,692)))
    assert not g.visible(g.norm((596,401)),g.norm((596,450)))
    assert g.plan(g.norm((596,401)),g.norm((617,527)))
    o=json.loads((ROOT/'resources/wingman/nuke/objectives.json').read_text())
    for route in o['entry_routes'].values():
        assert route[:2]==[[710,690],[655,688]]
        assert g.visible(g.norm((710,721)),g.norm(route[0]))
        assert g.visible(g.norm(route[0]),g.norm(route[1]))


def test_open_decon_visual_center_corrects_heading_only_on_crossing(csgobot_path):
    from nav.door_actions import observe_door,DoorActions
    zones=json.loads((ROOT/'resources/nav/profiles/de_nuke/traversal.json').read_text())['zones']
    doors=DoorActions(z for z in zones if z['action']=='use_door')
    obs=observe_door(frame('live5_39'),'de_nuke',10.)
    assert obs.opening_error_deg is not None and -30<obs.opening_error_deg<-10
    start=(518/1023,604/1023);target=(549/1023,600/1023)
    heading=doors.opening_heading(start,now=10.,yaw=5.,target=target,observation=obs)
    assert heading is not None and heading<0
    assert doors.opening_heading(start,now=11.,yaw=5.,target=target,observation=obs) is None
    assert doors.opening_heading(start,now=10.,yaw=5.,target=(510/1023,604/1023),observation=obs) is None
    assert doors.opening_heading((710/1023,721/1023),now=10.,yaw=5.,target=target,observation=obs) is None


def test_wingman_faster_acquisition_keeps_precision_step(runtime):
    r,s,events,focus,config=runtime
    assert config.aim.mouse_step_max_delta==56
    assert config.aim.aim_near_step_max_delta==16
    assert config.aim.smoothing_factor==1.25


def test_nuke_camera_ignores_small_alternating_heading_noise(csgobot_path):
    from nav.camera_servo import CameraServo
    clock=[0.];moves=[]
    servo=CameraServo(lambda x,y:moves.append(x),3600,clock=lambda:clock[0])
    for error in [2.5,-2.5]*10:
        servo.submit(error,clock[0],limit=300,responsive=True,deadband_deg=3.)
        clock[0]+=.01;servo.advance()
    assert not moves
    servo.submit(90,clock[0],limit=300,responsive=True,deadband_deg=3.)
    for _ in range(10):clock[0]+=.01;servo.advance()
    assert sum(moves)>100
