"""Regressions for the wall collision in the 2026-09-21 12-15 recording."""
import math
import json
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
import cv2
import numpy as np
from tests.test_wingman_live import runtime, observe, payload


def test_recorded_wall_transition_is_closed_but_all_starts_reach_site(csgobot_path):
    from nav.wingman_runtime import load_ground
    ground=load_ground('de_inferno');site=ground.norm((820,710))
    assert not ground.visible(ground.norm((730,730)),ground.norm((802,726)))
    for start in ((525,677),(730,730),(889,653)):
        path=ground.plan(ground.norm(start),site)
        assert path and all(ground.visible(a,b) for a,b in zip(path,path[1:]))
        if start[0]<744:assert min(ground.pixel(p)[1] for p in path)<640 or max(ground.pixel(p)[1] for p in path)>760
    root=Path(__file__).resolve().parents[1]
    data=json.loads((root/'resources/wingman/inferno/objectives.json').read_text())
    assert data['search_points']
    for p in data['search_points']:assert ground.contains(ground.norm(p)) and ground.plan(site,ground.norm(p))


def make_controller():
    from nav.visual_controller import VisualNavController
    from nav.pack import load_nav_pack,NavGoal
    from nav.paths import resolve_nav_pack_path
    from nav.walkable import WalkableMap
    pack=load_nav_pack(resolve_nav_pack_path('inferno_visual'))
    goal=NavGoal('mission',170/199,100/199,.025)
    pack=replace(pack,map_id='test',goal=goal,goals=(goal,))
    ground=WalkableMap(np.full((200,200),255,np.uint8),clearance_px=2)
    held=set();yaw=[0.]
    controller=VisualNavController(pack,NS(fov=NS(x360=3600)),held.add,held.discard,
        lambda x,y:yaw.__setitem__(0,yaw[0]+x/10),walkable=ground,adaptive_goal=True,camera_rate=300)
    return controller,ground,held,yaw


def test_unmapped_obstacle_is_bypassed_without_abandoning_mission(csgobot_path):
    from nav.walkable import WalkableMap
    from nav.pose import PoseResult
    c,g,held,yaw=make_controller()
    mask=np.full((200,200),255,np.uint8);cv2.circle(mask,(100,100),8,0,-1)
    world=WalkableMap(mask,clearance_px=2)
    point=np.array([30.,100.]);replanned=False
    try:
        for n in range(600):
            t=n*.05
            c.tick(PoseResult(*g.norm(point),yaw[0],.99,True,20,'visual',None,t),now=t,paused=False)
            replanned |= c.reason=='obstacle_replanned'
            assert c.goal_id=='mission'
            if c.reason=='goal_reached':break
            forward=('w' in held)-('s' in held)
            side=('d' in held)-('a' in held)
            angle=math.radians(yaw[0]);length=max(1.,math.hypot(forward,side))
            candidate=point+np.array([forward*math.cos(angle)-side*math.sin(angle),
                                      forward*math.sin(angle)+side*math.cos(angle)])/length
            if world.visible(g.norm(point),g.norm(candidate)):point=candidate
        assert replanned and c.reason=='goal_reached'
        assert len(c._reroutes)<=3
    finally:c.close()


def test_goal_update_and_brief_icon_loss_keep_obstacle_memory(csgobot_path):
    from nav.pack import NavGoal
    from nav.pose import PoseResult
    c,g,held,yaw=make_controller()
    try:
        c._target=g.norm((170,100));assert c._avoid_failed_direction(g.norm((75,100)),1.)
        memory=list(c._obstacles)
        c.set_goal(NavGoal('defend',.85,.7,.02))
        assert c._obstacles==memory
        c.tick(PoseResult.invalid(),now=2.,paused=False)
        assert not held and c._obstacles==memory and c.goal_id=='defend'
    finally:c.close()


def test_spectator_packet_does_not_erase_purchase_transaction(runtime):
    r,s,events,focus,config=runtime
    observe(r,s,payload(round={'phase':'freezetime'}))
    transaction=object();r.purchase=transaction;r.bought_key=r.round_key;key=r.round_key
    observe(r,s,payload(player={'steamid':'76561198000000002'},round={'phase':'freezetime'}))
    assert r.round_key==key and r.purchase is transaction
    observe(r,s,payload(round={'phase':'freezetime'}))
    assert r.purchase is transaction
