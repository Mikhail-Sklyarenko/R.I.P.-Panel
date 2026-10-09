from collections import Counter
import importlib
import math
from types import SimpleNamespace
import pytest


@pytest.mark.parametrize('map_id,pack_name,start',[
    ('de_dust2','dust2_visual_mvp',(.4,.9)),
    ('de_mirage','mirage_visual',(.6,.46)),
])
def test_both_maps_move_while_camera_turns_and_respect_walls(csgobot_module_path,map_id,pack_name,start):
    from nav.farm_runtime import create_navigation,CameraOwnership
    from nav.pack import load_nav_pack
    from nav.paths import resolve_nav_pack_path
    from nav.pose import PoseResult
    keys=set();mouse=[]
    owner=CameraOwnership(lambda dx,dy:mouse.append(dx/10),lambda:True);owner.select('nav')
    c=create_navigation(load_nav_pack(resolve_nav_pack_path(pack_name)),
        SimpleNamespace(fov=SimpleNamespace(x360=3600)),keys.add,keys.discard,owner,expanded=True,watchdog=False)
    c._roaming.rng.seed(31)
    x,y=start;yaw=170.;moving=0;collisions=0;switches=0;reasons=Counter()
    try:
        for i in range(1200):
            t=1.+i*.05
            result=c.tick(PoseResult(x,y,yaw,.95,True,40,'visual',None,t),now=t,paused=False)
            yaw+=sum(mouse);mouse.clear()
            forward=int('w'in keys)-int('s'in keys);side=int('d'in keys)-int('a'in keys)
            length=max(1.,math.hypot(forward,side));a=math.radians(yaw)
            # A simple fixed-speed planar plant, not a CS2/live traversal claim.
            dx=(forward*math.cos(a)-side*math.sin(a))/length*55*.05
            dy=(forward*math.sin(a)+side*math.cos(a))/length*55*.05
            nx=x+dx/(c.walkable.width-1);ny=y+dy/(c.walkable.height-1)
            if c._base_walkable.visible((x,y),(nx,ny)):x,y=nx,ny
            else:collisions+=1
            reasons[result.reason]+=1
            moving+=bool(keys);switches+=result.goal_switch_event
            assert 'shift' not in keys
        assert collisions==0
        assert moving/1200>.70, (reasons,(x,y),c.path_label)
        assert switches>=2
        c.tick(PoseResult.invalid(),now=62.,paused=False)
        assert not keys
    finally:c.close()
