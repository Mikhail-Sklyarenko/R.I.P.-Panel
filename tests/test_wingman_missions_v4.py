"""Mission changes, round continuity and small-target fire regressions."""
import json
import math
import random
import time
from pathlib import Path
from types import SimpleNamespace as NS
from tests.test_wingman_live import runtime, observe, payload
from tests.test_wingman_navigation_v3 import make_controller


def catalog():
    return json.loads((Path(__file__).resolve().parents[1]/'resources/wingman/inferno/objectives.json').read_text())


def test_all_new_candidates_reachable_without_reopening_recorded_wall(csgobot_path):
    from nav.wingman_runtime import load_ground
    g=load_ground('de_inferno');start=g.norm((525,677))
    for key in ('plant_points','approach_points','patrol_points'):
        for p in catalog()[key]:
            assert g.contains(g.norm(p)),(key,p)
            route=g.plan(start,g.norm(p))
            assert route and all(g.visible(a,b) for a,b in zip(route,route[1:])),(key,p)
    assert not g.visible(g.norm((730,730)),g.norm((802,726)))


def test_rounds_use_different_plants_and_ct_explores_beyond_site(csgobot_path):
    from nav.wingman_missions import MissionPlanner
    from nav.wingman_runtime import load_ground
    p=MissionPlanner(catalog(),rng=random.Random(7));g=load_ground('de_inferno')
    plants=[];approaches=[]
    for _ in range(8):
        p.reset_round();p.choose(g,g.norm((525,677)),team='T',bomb='carried_self')
        plants.append(p.queue[-1].point);approaches.append(p.queue[0].point)
        while p.queue:p.complete()
    assert len(set(plants))>=3 and all(a!=b for a,b in zip(plants,plants[1:]))
    assert len(set(approaches))>=2
    p.reset_round();start=g.norm((889,653));visited=[]
    for _ in range(8):
        m=p.choose(g,start,team='CT',bomb='not_carried_self')
        visited.append(m.point);start=g.norm(m.point);p.complete()
    assert len(set(visited))>=5 and min(x for x,y in visited)<750
    assert all(math.dist(a,b)>=28 for a,b in zip(visited,visited[1:]))


def test_planted_bomb_preempts_ct_patrol_and_search_does_not_repeat(csgobot_path):
    from nav.wingman_missions import MissionPlanner
    from nav.wingman_runtime import load_ground
    p=MissionPlanner(catalog(),rng=random.Random(3));g=load_ground('de_inferno');start=g.norm((889,653))
    assert p.choose(g,start,team='CT',bomb='not_carried_self').action=='patrol'
    m=p.choose(g,start,team='CT',bomb='planted');assert m.action=='defuse'
    seen=[]
    for _ in range(5):
        m=p.choose(g,start,team='CT',bomb='planted');seen.append(m.point)
        start=g.norm(m.point);p.complete()
    assert len(set(seen))==5


def test_failed_plant_is_not_retried_each_frame(csgobot_path):
    from nav.wingman_missions import MissionPlanner
    from nav.wingman_runtime import load_ground
    p=MissionPlanner(catalog(),rng=random.Random(1));g=load_ground('de_inferno');start=g.norm((832,718))
    m=p.choose(g,start,team='T',bomb='carried_self')
    while m.action=='approach':p.complete();m=p.choose(g,start,team='T',bomb='carried_self')
    failed=m.point;p.complete(failed=True)
    p.choose(g,start,team='T',bomb='carried_self')
    assert p.queue[-1].point!=failed


def test_round_reset_preserves_unexpired_hypotheses_only(csgobot_path):
    c,g,held,yaw=make_controller()
    try:
        c._obstacles=[(g.norm((100,100)),10,60.),(g.norm((120,100)),10,2.)]
        c._set_keys({'w'})
        c.reset_round(now=3.,preserve_obstacles=True)
        assert not held and c.last_pose is None and len(c._obstacles)==1
        assert not c.walkable.contains(g.norm((100,100)))
        c.reset_round(now=4.,preserve_obstacles=False)
        assert not c._obstacles and c.walkable.contains(g.norm((100,100)))
    finally:c.close()


def test_patrol_arrival_advances_without_two_second_dwell(runtime):
    from nav.pose import PoseResult
    from nav.wingman_runtime import load_ground
    r,s,*_=runtime;observe(r,s,payload(player={'team':'CT','weapons':{}}))
    g=load_ground('de_inferno');goals=[]
    c=NS(walkable=g,last_pose=PoseResult(*g.norm((889,653)),0,.95,True,20,'visual',None,time.monotonic()),
         reason='tracking',release_keys=lambda:None,set_goal=lambda goal,**kw:goals.append(goal))
    wait_mission(r,c);old=r.mission
    # Finish the prefetched search while the current leg is still being walked.
    r.planning.result(timeout=5)
    c.last_pose=PoseResult(*g.norm(old.point),0,.95,True,20,'visual',None,time.monotonic())
    r.set_objective(c,now=time.monotonic())
    assert len(goals)==2 and r.mission.point!=old.point and r.interaction is None
    observe(r,s,payload(player={'team':'CT','weapons':{}},round={'bomb':'planted'}))
    r.set_objective(c,now=time.monotonic())
    assert r.mission is None  # old patrol cannot continue while bomb plan is pending
    wait_mission(r,c)
    assert r.mission.action=='defuse'


def wait_mission(r,c):
    from dataclasses import replace
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        c.last_pose=replace(c.last_pose,observed_at=time.monotonic())
        r.set_objective(c,now=time.monotonic())
        if r.mission:return
        time.sleep(.005)
    raise AssertionError('mission did not finish')


def target(csgobot_path,dx=0,width=20):
    from aiming.target_selector import Target
    return Target('c',0,.9,640+dx-width/2,340,640+dx+width/2,400,640+dx,360,abs(dx),False)


def test_small_target_rejects_shoulder_and_uses_capture_projection(csgobot_path):
    from aiming.combat_aim import precise_fire_distance as measure
    kw=dict(center_x=640,center_y=360,captured_at=10.,now=10.1)
    assert math.isinf(measure(target(csgobot_path,8),**kw))
    assert measure(target(csgobot_path,2),**kw)==2
    assert measure(target(csgobot_path,8),project=lambda x,y,t:(x-8,y),**kw)==0
    assert math.isinf(measure(target(csgobot_path),center_x=640,center_y=360,captured_at=10,now=10.3))
    assert math.isinf(measure(target(csgobot_path,1,width=0),**kw))


def test_wingman_aim_finishes_the_last_eight_pixels(runtime):
    from config import AimConfig,CaptureRegion,FOVConfig
    from aiming.aim_mouse_controller import AimMouseController
    from aiming.fov_mouse import FOVMouseMovement
    r,s,e,f,c=runtime
    aim=AimConfig()
    for name in ('aim_dead_zone_high','aim_dead_zone_low','aim_settle_px','aim_unlock_px','mouse_min_delta'):
        setattr(aim,name,getattr(c.aim,name))
    aim.mouse_hz=120;aim.mouse_coast=False
    fov=FOVMouseMovement(CaptureRegion(left=0,top=0,width=1280,height=720),FOVConfig(horizontal=106.26,vertical=73.74,x360=7792))
    mouse=AimMouseController(config=aim,fov_mouse=fov);moves=[];mouse.start(lambda x,y:moves.append((x,y)))
    try:
        at=time.monotonic();mouse.set_target(648,360,smoothing=2.4,now=at)
        deadline=at+.2
        while time.monotonic()<deadline and not mouse.is_settled:time.sleep(.005)
        assert moves and abs(mouse.project_point(648,360,at)[0]-640)<2
    finally:mouse.stop()


def test_confirmed_defuse_survives_one_missing_hud_frame(runtime):
    from modules.wingman.visual import VisualEvidence
    r,s,events,*_=runtime
    observe(r,s,payload(player={'team':'CT','weapons':{}},round={'bomb':'planted'}))
    t=time.monotonic();r.interaction='defuse';r.interaction_at=t
    r.last_hud=VisualEvidence('defusing',.99,'recognized_hud_text',t)
    r.idle_tick(None,now=t+.1)
    r.last_hud=VisualEvidence('unknown',0,'no_verified_overlay',t+.2)
    r.idle_tick(None,now=t+1.)
    assert r.interaction=='defuse' and 'e' in r.lease.keys
    observe(r,s,payload(player={'team':'CT','state':{'health':0}},round={'bomb':'planted'}))
    assert r.interaction is None and not r.lease.keys


def test_old_async_plan_cannot_overwrite_bomb_priority(runtime,monkeypatch):
    from concurrent.futures import Future
    from nav.wingman_runtime import load_ground
    from nav.wingman_missions import Mission
    from nav.pose import PoseResult
    r,s,*_=runtime;observe(r,s,payload(player={'team':'CT','weapons':{}}))
    g=load_ground('de_inferno')
    old=Future();old.set_running_or_notify_cancel()
    r.planning=old;r.active_role='patrol';r.planning_context=(r.round_key,'patrol',id(g))
    c=NS(walkable=g,reason='tracking',release_keys=lambda:None,
         last_pose=PoseResult(*g.norm((889,653)),0,.99,True,20,'visual',None,time.monotonic()),
         set_goal=lambda *a,**kw:None)
    observe(r,s,payload(player={'team':'CT','weapons':{}},round={'bomb':'planted'}))
    r.set_objective(c,now=time.monotonic())
    old.set_result((r.planner,Mission((700,674),'patrol')))
    wait_mission(r,c)
    assert r.mission.action=='defuse'


def test_fire_releases_immediately_when_target_leaves_central_region(csgobot_path):
    from aiming.fire_controller import FireController,FireConfig
    from aiming.combat_aim import precise_fire_distance
    fire=FireController(FireConfig(hold_release_grace_sec=0,humanize_jitter_sec=0,shoot_dead_zone=24))
    assert fire.tick(pixel_distance=0,confidence=.9,is_head=False,now=1).press
    d=precise_fire_distance(target(csgobot_path,8),center_x=640,center_y=360,captured_at=1.,now=1.1)
    assert fire.tick(pixel_distance=d,confidence=.9,is_head=False,now=1.1).release


def test_prepared_path_joins_pose_without_replanning_or_accepting_blocked_edges(csgobot_path):
    from nav.pack import NavGoal
    from nav.pose import PoseResult
    c,g,held,yaw=make_controller()
    try:
        c.last_pose=PoseResult(*g.norm((32,100)),0,.99,True,20,'visual',None,time.monotonic())
        route=g.plan(g.norm((30,100)),g.norm((170,100)))
        c.set_goal(NavGoal('prepared',*g.norm((170,100)),.02),prepared_path=route)
        assert c._path and not c._needs_attach and c._path[0]==g.norm((32,100))
        c.walkable=g.excluding([(g.norm((100,100)),10)])
        c.set_goal(NavGoal('obstructed',*g.norm((170,100)),.02),prepared_path=route)
        assert not c._path and c._needs_attach
    finally:c.close()
