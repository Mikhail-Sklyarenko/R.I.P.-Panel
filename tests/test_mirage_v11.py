import json
import cv2
import numpy as np
import pytest
from pathlib import Path
from types import SimpleNamespace

@pytest.mark.parametrize('stamp',[40,60,180,400])
def test_player_icon_separate_from_translucent_sky(csgobot_module_path,stamp):
    from nav.minimap_reader import MinimapReader
    from nav.calibration import load_calibration
    from nav.paths import resolve_calibration_path
    from nav.icon_heading import observe_heading
    reader=MinimapReader(load_calibration(resolve_calibration_path()))
    frame=cv2.cvtColor(cv2.imread(str(Path(__file__).parent/f'fixtures/nav_mirage_glare/{stamp}.png')),cv2.COLOR_BGR2RGB)
    pose=reader.read(frame)
    assert pose.valid and 25<=pose.blob_area_px<=100
    crop,cx,cy,r=reader._crop_from_circle(frame,reader.last_circle)
    assert np.linalg.norm(np.array(reader.last_icon_xy)-[cx,cy])<6
    assert observe_heading(crop,reader.last_icon_component) is not None
    # Empty sky must not acquire the missing player through position priors.
    frame[115:147,115:147]=frame[115,112]
    assert not reader.read(frame).valid


def test_cyan_marker_still_detected(csgobot_module_path):
    from nav.minimap_reader import MinimapReader
    from nav.calibration import load_calibration
    from nav.paths import resolve_calibration_path
    reader=MinimapReader(load_calibration(resolve_calibration_path()))
    rgb=np.zeros((100,100,3),np.uint8)
    low=np.array(reader._mm.player_icon.rgb_min);high=np.array(reader._mm.player_icon.rgb_max)
    rgb[47:54,47:54]=((low+high)//2).astype(np.uint8)
    yellow,cyan=reader._player_color_masks(rgb)
    assert cyan[50,50] and not yellow[50,50]


def test_jungle_crouch_only_with_motion_and_local_position(csgobot_module_path):
    from nav.traversal_actions import TraversalActions
    a=TraversalActions.load('de_mirage')
    assert a.apply({'w'},(385/1023,537/1023))=={'w','ctrl'}
    assert a.apply({'s'},(385/1023,537/1023))=={'s','ctrl'}
    assert a.apply({'w'},(412/1023,537/1023))=={'w','ctrl'}
    assert a.apply({'w'},(416/1023,537/1023))=={'w'}
    assert a.apply({'w'},(.85,.54))=={'w'}
    assert a.apply(set(),(385/1023,537/1023))==set()
    assert a.apply({'w'},None)=={'w'}
    assert TraversalActions.load('de_cache').apply({'w'},(385/1023,537/1023))=={'w'}


def test_crouch_shares_input_lease_and_releases_on_pause_loss_reload(csgobot_module_path):
    from nav.farm_runtime import create_navigation,CameraOwnership
    from nav.pack import load_nav_pack
    from nav.paths import resolve_nav_pack_path
    from nav.pose import PoseResult
    keys=set();owner=CameraOwnership(lambda *args:None,lambda:True);owner.select('nav')
    c=create_navigation(load_nav_pack(resolve_nav_pack_path('mirage_visual')),
        SimpleNamespace(fov=SimpleNamespace(x360=7792)),keys.add,keys.discard,owner,expanded=True,watchdog=False)
    try:
        def held():
            c.last_pose=PoseResult(385/1023,537/1023,0,.95,True,60,'visual',None,1.)
            c._lease.renew(.25);c._set_keys({'w'});assert keys=={'w','ctrl'}
        held();c.tick(c.last_pose,now=1.1,paused=True);assert not keys
        held();c.tick(PoseResult.invalid(),now=1.1,paused=False);assert not keys
        held();c._lease.renew(0);c._lease.expire();assert not keys
        held();c.reload_pack(load_nav_pack(resolve_nav_pack_path('cache_visual')));assert not keys
        assert not c._traversal.zones
    finally:c.close()


def test_jungle_route_is_connected_through_crouch_zone(csgobot_module_path):
    from nav.walkable import WalkableMap
    from nav.traversal_actions import TraversalActions
    w=WalkableMap.load('de_mirage');a=TraversalActions.load('de_mirage')
    for start,end in [((400,595),(400,535)),((400,535),(400,595))]:
        p=w.plan(w.norm(start),w.norm(end));assert p
        assert all(w.visible(x,y) for x,y in zip(p,p[1:]))
        assert any('ctrl' in a.apply({'w'},tuple(np.array(x)*(1-t)+np.array(y)*t))
                   for x,y in zip(p,p[1:]) for t in np.linspace(0,1,25))

@pytest.mark.parametrize('start,end', [((400,610),(400,530)),((400,530),(400,610))])
def test_crouch_passage_closed_loop_with_low_ceiling(csgobot_module_path,start,end):
    from nav.visual_controller import VisualNavController
    from nav.pose import PoseResult
    import math
    goal=SimpleNamespace(id='exit',x=end[0]/1023,y=end[1]/1023,arrive_radius=.004)
    pack=SimpleNamespace(map_id='de_mirage',goal=goal,goals=(goal,),strategy='single',
        route=SimpleNamespace(dwell_at_goal_sec=0),humanize=SimpleNamespace(turn_rate_deg_per_sec=300))
    keys=set();mouse=[]
    c=VisualNavController(pack,SimpleNamespace(fov=SimpleNamespace(x360=3600)),
        keys.add,keys.discard,lambda dx,dy:mouse.append(dx/10),watchdog=False)
    x,y=map(float,start);yaw=-90 if end[1]<start[1] else 90;crouched=0;collisions=0
    try:
        for i in range(400):
            now=1+i*.05
            c.tick(PoseResult(x/1023,y/1023,yaw,.95,True,60,'visual',None,now),now=now,paused=False)
            yaw+=sum(mouse);mouse.clear()
            forward=int('w' in keys)-int('s' in keys)
            speed=18 if 'ctrl' in keys else 55
            nx=x+forward*math.cos(math.radians(yaw))*speed*.05
            ny=y+forward*math.sin(math.radians(yaw))*speed*.05
            low=378<=nx<=426 and 528<=ny<=552
            if low and forward and 'ctrl' not in keys:collisions+=1
            elif c.walkable.visible((x/1023,y/1023),(nx/1023,ny/1023)):x,y=nx,ny
            crouched+=bool(forward and 'ctrl' in keys)
        assert np.linalg.norm(np.array([x,y])-end)<8,(x,y,c.reason)
        assert crouched>10 and collisions==0
        assert 'ctrl' not in keys
    finally:c.close()
