import math
from pathlib import Path
from types import SimpleNamespace as NS
import numpy as np
import pytest
from tests.test_wingman_live import runtime

ROOT=Path(__file__).resolve().parents[1]


def make():
    from nav.wingman_runtime import load_ground
    from nav.wingman_ingress import WingmanIngress
    from nav.visual_controller import VisualNavController
    from nav.pack import load_nav_pack
    from nav.paths import resolve_nav_pack_path
    base=load_ground('de_inferno');held=set();yaw=[0.]
    c=VisualNavController(load_nav_pack(resolve_nav_pack_path('inferno_visual')),
        NS(fov=NS(x360=3600)),held.add,held.discard,lambda x,y:yaw.__setitem__(0,yaw[0]+x/10),
        walkable=base,adaptive_goal=True,camera_rate=360)
    return c,WingmanIngress(ROOT/'resources/wingman/inferno'),base,held,yaw


@pytest.mark.parametrize('name',['long','short','apartments'])
def test_recorded_ingress_follows_its_own_corridor_and_returns_to_base(csgobot_path,name):
    from nav.pose import PoseResult
    c,ingress,base,held,yaw=make();point=np.array([529.,677.]);ingress.counts.update({k:5 for k in ingress.routes if k!=name})
    c.last_pose=PoseResult(*base.norm(point),0,.99,True,20,'visual',None,1.)
    try:
        assert ingress.update(c,c.last_pose,team='T',bomb='carried_self',now=1.)==('started',name)
        world=c.walkable;jumps=0;collisions=0
        for n in range(2000):
            t=1+n*.05;pose=PoseResult(*world.norm(point),yaw[0],.99,True,20,'visual',None,t)
            c.tick(pose,now=t,paused=False)
            status,_=ingress.update(c,pose,team='T',bomb='carried_self',now=t)
            if status=='finished':break
            if 'space' in held:
                jumps+=1;assert 'ctrl' not in held
            f=('w'in held)-('s'in held);side=('d'in held)-('a'in held);a=math.radians(yaw[0]);length=max(1.,math.hypot(f,side))
            end=point+2*np.array([f*math.cos(a)-side*math.sin(a),f*math.sin(a)+side*math.cos(a)])/length
            if world.visible(world.norm(point),world.norm(end)):point=end
            else:collisions+=1
        assert status=='finished',(name,c.reason,point,c.path_label)
        assert collisions==0 and c.walkable is base and not held
        if name=='apartments':assert jumps>0
        assert ingress.update(c,c.last_pose,team='T',bomb='carried_self',now=t)[0] is None
    finally:c.close()


def test_all_three_branches_selected_across_rounds_but_never_for_ct(csgobot_path):
    from nav.pose import PoseResult
    c,i,g,held,yaw=make();seen=[]
    try:
        for _ in range(6):
            i.reset_round();c.reset_round(now=1.)
            pose=PoseResult(*g.norm((529,677)),0,.99,True,20,'visual',None,1.);c.last_pose=pose
            assert i.update(c,pose,team='CT',bomb='not_carried_self',now=1.)==(None,None)
            status,name=i.update(c,pose,team='T',bomb='not_carried_self',now=1.);seen.append(name)
            assert i.update(c,pose,team='T',bomb='planted',now=1.1)==('active',name)
        assert set(seen[:3])=={'long','short','apartments'}
        assert all(a!=b for a,b in zip(seen,seen[1:]))
    finally:c.close()


def test_short_reopens_recorded_south_corridor_not_previous_wall(csgobot_path):
    from nav.wingman_runtime import load_ground
    g=load_ground('de_inferno')
    assert not g.visible(g.norm((730,730)),g.norm((802,726)))
    for xy in [(746,774),(788,768),(805,778),(813,779),(828,754)]:assert g.contains(g.norm(xy))
    path=g.plan(g.norm((700,674)),g.norm((832,734)))
    assert path and max(g.pixel(p)[1] for p in path)>760


def test_balcony_jump_is_directional_and_input_loss_cancels_it(csgobot_path):
    from nav.traversal_actions import TraversalActions
    import json
    route=json.loads((ROOT/'resources/wingman/inferno/ingress.json').read_text())['routes'][2]
    a=TraversalActions(route['actions']);point=(838/1023,817/1023)
    assert 'space' not in a.apply({'w'},point,now=1,yaw=122)
    keys=a.apply({'w'},point,now=2,yaw=-58)
    assert 'space' in keys and 'ctrl' not in keys
    assert not a.apply(set(),point,now=2.1,yaw=-58)
    assert 'space' not in a.apply({'w'},point,now=2.2,yaw=-58)


def test_runtime_round_change_discards_apartment_commitment(runtime):
    from nav.pose import PoseResult
    from tests.test_wingman_live import payload
    import time
    r,s,events,focus,config=runtime
    c,unused,g,held,yaw=make()
    image=np.zeros((720,1280,3),np.uint8)
    try:
        assert s.accept(payload())
        r.observe(image,c,now=time.monotonic())
        r.ingress.counts.update({'long':5,'short':5})
        c.last_pose=PoseResult(*g.norm((529,677)),0,.99,True,20,'visual',None,time.monotonic())
        r.set_objective(c,now=time.monotonic())
        assert r.mission.action=='ingress' and r.ingress.active=='apartments'
        assert c.walkable is not g
        assert s.accept(payload(map={'round':1},round={'phase':'freezetime'}))
        r.observe(image,c,now=time.monotonic())
        assert r.ingress.active is None and r.mission is None and c.last_pose is None
        assert c.walkable is g and not held
    finally:c.close()


def test_centered_radar_uses_visible_purple_tip_not_northern_teammate(csgobot_path):
    import cv2
    from nav.minimap_reader import MinimapReader
    from nav.calibration import load_calibration
    from nav.paths import resolve_calibration_path
    frame=cv2.cvtColor(cv2.imread(str(ROOT/'tests/fixtures/wingman/regression_v6/218.png')),cv2.COLOR_BGR2RGB)
    reader=MinimapReader(load_calibration(resolve_calibration_path()));reader.competitive_markers=True
    pose=reader.read(frame)
    # Lossless fixture has a visible SOUTH tip on the dark purple marker.
    # The old bright-body threshold lost it and incorrectly rejected it.
    assert pose.valid and 95 < pose.yaw_deg < 120
    x,y,_,_=reader.last_circle.rect
    assert math.dist((reader.last_icon_xy[0]+x,reader.last_icon_xy[1]+y),(130,130))<3
