import cv2
import numpy as np
import pytest
from types import SimpleNamespace


def test_long_room_was_disconnected_by_coarse_grid(csgobot_module_path):
    from nav.farm_runtime import load_ground
    from nav.walkable import WalkableMap
    from nav.paths import resolve_nav_root
    mask=cv2.imread(str(resolve_nav_root()/'experimental/de_dust2/walkable.png'),0)
    old=WalkableMap(mask,clearance_px=6,grid_step=4)
    new=load_ground('de_dust2')
    assert new.step==2 and np.array_equal(old.free,new.free)
    room=(695,615)
    for outside in ((697,520),(695,710)):
        assert not old.plan(old.norm(room),old.norm(outside))
        for start,end in ((room,outside),(outside,room)):
            path=new.plan(new.norm(start),new.norm(end))
            assert path and all(new.visible(a,b) for a,b in zip(path,path[1:]))
    # Door leaves and crates are still solid.
    for blocked in ((685,652),(718,661),(712,568),(715,590)):
        assert not new.contains(new.norm(blocked)),blocked


def test_long_room_can_choose_distant_goals(csgobot_module_path):
    from nav.farm_runtime import load_ground
    from nav.roaming import RoamingGoals
    w=load_ground('de_dust2');roam=RoamingGoals(w,seed=14);point=w.norm((695,615))
    for i in range(8):
        goal,path=roam.choose(point,now=i)
        assert np.linalg.norm(np.array(w.pixel((goal.x,goal.y)))-[695,615])>=100
        assert all(w.visible(a,b) for a,b in zip(path,path[1:]))


@pytest.mark.parametrize('start,end',[((695,615),(697,520)),((697,520),(695,615)),((695,615),(695,710)),((695,710),(695,615))])
def test_long_doors_closed_loop(csgobot_module_path,start,end):
    from nav.visual_controller import VisualNavController
    from nav.farm_runtime import load_ground
    from nav.pose import PoseResult
    import math
    goal=SimpleNamespace(id='outside',x=end[0]/1023,y=end[1]/1023,arrive_radius=.005)
    pack=SimpleNamespace(map_id='de_dust2',goal=goal,goals=(goal,),strategy='single',
        route=SimpleNamespace(dwell_at_goal_sec=0),humanize=SimpleNamespace(turn_rate_deg_per_sec=360))
    keys=set();mouse=[]
    c=VisualNavController(pack,SimpleNamespace(fov=SimpleNamespace(x360=3600)),keys.add,keys.discard,
        lambda dx,dy:mouse.append(dx/10),walkable_loader=load_ground,watchdog=False)
    x,y=map(float,start);yaw=125.;collisions=0;moving=0
    try:
        for i in range(600):
            now=1+i*.05
            c.tick(PoseResult(x/1023,y/1023,yaw,.95,True,60,'visual',None,now),now=now,paused=False)
            yaw+=sum(mouse);mouse.clear()
            forward=int('w' in keys)-int('s' in keys)
            nx=x+forward*math.cos(math.radians(yaw))*55*.05
            ny=y+forward*math.sin(math.radians(yaw))*55*.05
            if c.walkable.visible((x/1023,y/1023),(nx/1023,ny/1023)):x,y=nx,ny
            elif forward:collisions+=1
            moving+=bool(forward)
            assert 'shift' not in keys
            if np.linalg.norm(np.array([x,y])-end)<7:break
        assert np.linalg.norm(np.array([x,y])-end)<7,(start,end,x,y,c.reason)
        assert collisions==0
    finally:c.close()


def test_rich_hud_long_doors_requires_unique_matching_map(csgobot_module_path):
    from pathlib import Path
    from nav.dense_localizer import DenseMapMatcher
    root=Path(__file__).resolve().parents[1]
    fixture=root/'tests/fixtures/nav_dust2_doors'
    crop=cv2.cvtColor(cv2.imread(str(fixture/'100.png')),cv2.COLOR_BGR2RGB)
    mask=cv2.imread(str(fixture/'100_mask.png'),0)
    for map_id in ('de_dust2','de_mirage','de_inferno','de_vertigo','de_cache'):
        radar=cv2.cvtColor(cv2.imread(str(root/f'resources/nav/maps/{map_id}/radar.png')),cv2.COLOR_BGR2RGB)
        matcher=DenseMapMatcher(radar,translucent=True,rich_hud=True)
        result=matcher.match_at_scale(crop,mask,.355)
        if map_id=='de_dust2':
            assert DenseMapMatcher(radar,translucent=True).match_at_scale(crop,mask,.355) is None
            assert result is not None
            # Independent calibrated HUD atlas locates this frame around (700,637).
            assert np.linalg.norm(result[0]@np.array([112,112,1])-[700,637])<4
        else:
            assert result is None,map_id
        assert matcher.match_at_scale(np.zeros_like(crop),mask,.355) is None


def test_weighted_search_preserves_obstacle_exclusions(csgobot_module_path):
    from nav.walkable import WalkableMap
    mask=np.full((100,100),255,np.uint8);mask[:,48:52]=0;mask[70:90,48:52]=255
    w=WalkableMap(mask,clearance_px=2,grid_step=2,search_weight=1.5)
    start,end=w.norm((20,20)),w.norm((80,20))
    path=w.plan(start,end)
    assert path and all(w.visible(a,b) for a,b in zip(path,path[1:]))
    assert max(w.pixel(p)[1] for p in path)>=70
    blocked=mask.copy();blocked[70:90,48:52]=0
    assert not WalkableMap(blocked,clearance_px=2,grid_step=2,search_weight=1.5).plan(start,end)


def test_hud_atlas_recovers_long_doors_without_new_calibration(csgobot_module_path):
    from pathlib import Path
    from nav.hud_atlas_matcher import HudAtlasMatcher
    root=Path(__file__).resolve().parents[1]
    fixture=root/'tests/fixtures/nav_dust2_doors'
    rgb=cv2.cvtColor(cv2.imread(str(fixture/'100.png')),cv2.COLOR_BGR2RGB)
    mask=cv2.imread(str(fixture/'100_hud_mask.png'),0)
    matcher=HudAtlasMatcher('de_dust2',(1024,1024))
    result=matcher.match_at_scale(rgb,mask,.355)
    assert result is not None
    assert np.linalg.norm(result[0]@np.array([112,112,1])-[700,637])<4
    assert matcher.match_at_scale(np.zeros_like(rgb),mask,.355) is None
    assert matcher.match_at_scale(np.random.default_rng(24).integers(0,255,rgb.shape,dtype=np.uint8),mask,.355) is None
    matcher.known[:]=0
    assert matcher.match_at_scale(rgb,mask,.355) is None


def test_dust2_hud_atlas_rejects_other_maps(csgobot_module_path):
    from pathlib import Path
    from nav.hud_atlas_matcher import HudAtlasMatcher
    root=Path(__file__).resolve().parents[1]
    matcher=HudAtlasMatcher('de_dust2',(1024,1024))
    for stamp in (30,140):
        fixture=root/'tests/fixtures/nav_inferno_boundary'
        rgb=cv2.cvtColor(cv2.imread(str(fixture/f'{stamp}.png')),cv2.COLOR_BGR2RGB)
        mask=cv2.imread(str(fixture/f'{stamp}_mask.png'),0)
        assert matcher.match_at_scale(rgb,mask,.355) is None
