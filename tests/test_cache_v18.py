"""Recorded Cache respawns and roof drop/ground separation regressions."""
import math
from pathlib import Path
from types import SimpleNamespace
import cv2
import numpy as np
import pytest


def recorded(t):
    band=cv2.imread(str(Path(__file__).parent/f'fixtures/nav_cache_v18/radar_{t}.png'))
    frame=np.zeros((720,1280,3),np.uint8)
    frame[:band.shape[0],:band.shape[1]]=cv2.cvtColor(band,cv2.COLOR_BGR2RGB)
    return frame


@pytest.mark.parametrize('stamp,layer',[(10,'roof'),(14,'roof'),(20,'roof'),(40,'upper'),(60,'upper'),(120,'upper'),(160,'upper'),(180,'roof'),(210,'roof'),(230,'roof'),(236,'roof'),(242,'roof')])
def test_recorded_stops_produce_fresh_pose_and_correct_surface(csgobot_module_path,stamp,layer):
    from nav.async_perception import AsyncVisualPerception
    from nav.calibration import load_calibration
    from nav.paths import resolve_calibration_path
    from nav.minimap_reader import MinimapReader
    p=AsyncVisualPerception(MinimapReader(load_calibration(resolve_calibration_path())),SimpleNamespace(map_id='de_cache',ready=False))
    try:
        p.update(recorded(stamp),now=1.)
        pose=p.update(recorded(stamp),now=1.1).pose
        assert pose.valid and pose.layer_id==layer and pose.observed_at==1.1
        assert p.reason=='measured_global_contours'
        p.reload_map('de_dust2')
        assert p._cache_levels is None and p._accepted is None
    finally:p.close()


def test_roof_needs_current_label_and_matching_position(csgobot_module_path):
    from nav.cache_levels import CacheLevels
    c=CacheLevels();point=(417/1023,594/1023)
    assert c.classify(recorded(210),point,1)=='roof'
    assert c.classify(recorded(40),point,1.1) is None
    blank=recorded(210);blank[254:283]=0
    assert c.classify(blank,point,1.2) is None
    assert c.classify(recorded(210),(186/1023,388/1023),1.3)=='upper'
    assert c.classify(blank,(417/1023,573/1023),1.4)=='upper'


def controller():
    from nav.visual_controller import VisualNavController
    from nav.pack import load_nav_pack
    from nav.paths import resolve_nav_pack_path
    keys=set();mouse=[]
    c=VisualNavController(load_nav_pack(resolve_nav_pack_path('cache_visual')),
        SimpleNamespace(fov=SimpleNamespace(x360=3600)),keys.add,keys.discard,
        lambda dx,dy:mouse.append(dx/10),free_roam=True,watchdog=False)
    c._roaming.rng.seed(18)
    return c,keys,mouse


@pytest.mark.parametrize('yaw',[-175.,-75.,45.,160.])
def test_measured_roof_spawn_reaches_ground_then_releases_on_loss(csgobot_module_path,yaw):
    from nav.pose import PoseResult
    c,keys,mouse=controller();x,y=417.,594.;left_roof=False
    try:
        ground=c._layer_grounds['upper'];roof=c._layer_grounds['roof']
        assert not ground.contains((x/1023,y/1023))
        assert roof.contains((x/1023,y/1023))
        for i in range(180):
            now=1+i*.05;layer='roof' if y>=574 else 'upper'
            pose=PoseResult(x/1023,y/1023,yaw,.9,True,radar_mode='visual',observed_at=now,layer_id=layer)
            c.tick(pose,now=now,paused=False);yaw+=sum(mouse);mouse.clear()
            if layer=='upper':
                left_roof=True
                assert c._route_goal.id=='roof_drop_north'
                assert not c._needs_attach
            f=int('w'in keys)-int('s'in keys);s=int('d'in keys)-int('a'in keys);a=math.radians(yaw);norm=max(1,math.hypot(f,s))
            nx=x+(f*math.cos(a)-s*math.sin(a))*40*.05/norm
            ny=y+(f*math.sin(a)+s*math.cos(a))*40*.05/norm
            surface=roof if y>=574 else ground
            assert surface.visible((x/1023,y/1023),(nx/1023,ny/1023)),(x,y,nx,ny,c.reason)
            x,y=nx,ny
            if y<572:break
        assert left_roof and y<572,(x,y,c.reason)
        c.tick(PoseResult.invalid(),now=20,paused=False)
        assert not keys
        c.reload_pack(c._pack)
        assert c._active_layer=='upper' and not c.walkable.contains((417/1023,594/1023))
    finally:c.close()


def test_truck_spawn_selects_walkable_route_without_waiting(csgobot_module_path):
    from nav.pose import PoseResult
    c,keys,_=controller()
    try:
        for i in range(5):
            now=1+i*.05
            c.tick(PoseResult(186/1023,388/1023,-92,.9,True,radar_mode='visual',observed_at=now,layer_id='upper'),now=now,paused=False)
        assert c._path and keys & {'w','a','s','d'},c.reason
        assert all(c.walkable.visible(a,b)for a,b in zip(c._path,c._path[1:]))
    finally:c.close()


def test_unknown_roof_and_combat_release_keys(csgobot_module_path):
    from nav.pose import PoseResult
    c,keys,_=controller()
    try:
        for i in range(5):
            now=1+i*.05
            p=PoseResult(417/1023,594/1023,-90,.9,True,radar_mode='visual',observed_at=now,layer_id='roof')
            c.tick(p,now=now,paused=False)
        assert keys
        from dataclasses import replace
        c.tick(replace(p,layer_id='unknown',observed_at=1.3),now=1.3,paused=False)
        assert not keys and c.reason=='unconfirmed_floor'
        c.tick(replace(p,observed_at=1.4),now=1.4,paused=True)
        assert not keys
    finally:c.close()


@pytest.mark.parametrize('stamp',[40,60,120,160])
def test_other_place_labels_cannot_authorize_roof(csgobot_module_path,stamp):
    from nav.cache_levels import CacheLevels
    assert CacheLevels().classify(recorded(stamp),(417/1023,594/1023),1.) is None


def test_ground_route_cannot_cross_roof_footprint(csgobot_module_path):
    from nav.walkable import WalkableMap
    g=WalkableMap.load('de_cache')
    a,b=g.norm((417,550)),g.norm((415,643))
    assert not g.visible(a,b)
    path=g.plan(a,b)
    assert path and all(g.visible(x,y)for x,y in zip(path,path[1:]))
    assert not g.contains(g.norm((417,594)))
