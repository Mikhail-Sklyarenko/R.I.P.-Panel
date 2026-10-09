"""Mirage aperture geometry, directed jump/crouch, and bounded input ownership."""
import math
from types import SimpleNamespace
import pytest


def test_window_crouch_is_at_actual_opening_not_old_southern_zone(csgobot_module_path):
    from nav.traversal_actions import TraversalActions
    a=TraversalActions.load('de_mirage')
    assert a.apply({'w'},(397/1023,569/1023),now=1,yaw=-90)=={'w'}
    assert a.apply({'w'},(385/1023,537/1023),now=1.1,yaw=180)=={'w','ctrl'}
    assert a.apply({'w'},(379/1023,537/1023),now=1.2,yaw=180)=={'w','ctrl'}
    assert a.apply({'w'},(345/1023,537/1023),now=1.3,yaw=180)=={'w'}


def test_ct_entry_jumps_then_ducks_with_bounded_attempts(csgobot_module_path):
    from nav.traversal_actions import TraversalActions
    a=TraversalActions.load('de_mirage');p=(346/1023,537/1023)
    assert a.apply({'w'},p,now=1,yaw=0)=={'w','space'}
    assert a.apply({'w'},p,now=1.1,yaw=0)=={'w','space','ctrl'}
    assert a.apply({'w'},p,now=1.3,yaw=0)=={'w','ctrl'}
    a.reset()
    assert 'space' not in a.apply({'w'},p,now=1.4,yaw=0)
    assert 'space' in a.apply({'w'},p,now=2.3,yaw=0)
    a.reset()
    assert 'space' not in a.apply({'w'},p,now=4,yaw=0)
    assert a.apply(set(),p,now=4.1,yaw=0)==set()
    assert a.apply({'w'},None,now=4.2,yaw=0)=={'w'}
    # Leaving the vicinity allows a later independent crossing.
    a.apply({'w'},(.8,.8),now=5,yaw=0)
    assert 'space' in a.apply({'w'},p,now=6,yaw=0)


@pytest.mark.parametrize('keys,yaw',[({'w'},180),({'s'},0),({'a'},0),({'w'},90)])
def test_exit_or_sideways_travel_never_jumps(csgobot_module_path,keys,yaw):
    from nav.traversal_actions import TraversalActions
    a=TraversalActions.load('de_mirage')
    assert 'space' not in a.apply(keys,(360/1023,537/1023),now=1,yaw=yaw)


@pytest.mark.parametrize('start,end',[(340,405),(405,340)])
def test_controller_crosses_synthetic_sill_and_low_aperture(csgobot_module_path,start,end):
    from nav.visual_controller import VisualNavController
    from nav.pose import PoseResult
    goal=SimpleNamespace(id='exit',x=end/1023,y=540/1023,arrive_radius=.004)
    pack=SimpleNamespace(map_id='de_mirage',goal=goal,goals=(goal,),strategy='single',
        route=SimpleNamespace(dwell_at_goal_sec=0),humanize=SimpleNamespace(turn_rate_deg_per_sec=300))
    keys=set();mouse=[]
    c=VisualNavController(pack,SimpleNamespace(fov=SimpleNamespace(x360=3600)),
        keys.add,keys.discard,lambda dx,dy:mouse.append(dx/10),watchdog=False)
    x=float(start);y=540.;yaw=0 if end>start else 180;z=0.;vz=0.;last_space=False
    collisions=0;jumps=0
    try:
        for i in range(300):
            now=1+i*.05
            c.tick(PoseResult(x/1023,y/1023,yaw,.95,True,60,'visual',None,now),now=now,paused=False)
            yaw+=sum(mouse);mouse.clear()
            if 'space' in keys and not last_space and z==0:vz=35.;jumps+=1
            last_space='space' in keys
            z=max(0.,z+vz*.05);vz=vz-90*.05 if z>0 else 0.
            speed=55. if z>0 or 'ctrl' not in keys else 18.
            f=int('w' in keys)-int('s' in keys);side=int('d' in keys)-int('a' in keys)
            norm=max(1,math.hypot(f,side));angle=math.radians(yaw)
            nx=x+(f*math.cos(angle)-side*math.sin(angle))*speed*.05/norm
            ny=y+(f*math.sin(angle)+side*math.cos(angle))*speed*.05/norm
            crossing=min(x,nx)<=378<=max(x,nx) and x!=nx
            sill_crossing=x<350<=nx
            blocked=(crossing and 'ctrl' not in keys) or (sill_crossing and z<2.)
            if blocked:collisions+=1
            elif c.walkable.visible((x/1023,y/1023),(nx/1023,ny/1023)):x,y=nx,ny
            if abs(x-end)<5:break
        assert abs(x-end)<5,(x,y,z,keys,c.reason)
        assert collisions==0
        assert jumps==(1 if end>start else 0)
        c.tick(PoseResult.invalid(),now=20,paused=True)
        assert not keys
    finally:c.close()


@pytest.mark.parametrize('stamp,expected',[(164,'upper'),(194.5,'upper'),(196.5,'lower'),(197.25,'lower'),(198.25,'lower'),(199.75,'lower'),(200.5,'lower'),(201.5,'upper')])
def test_recorded_place_labels_distinguish_overlapping_levels(csgobot_module_path,stamp,expected):
    from nav.mirage_levels import MirageLevels
    from pathlib import Path
    import cv2,numpy as np
    m=MirageLevels();frame=np.zeros((720,1280,3),np.uint8)
    band=cv2.imread(str(Path(__file__).parent/f'fixtures/nav_mirage_underpass/label_{stamp}.png'))
    frame[254:283,:240]=cv2.cvtColor(band,cv2.COLOR_BGR2RGB)
    assert m.classify(frame,(443/1023,350/1023),1.)==expected
    # Unknown spawn cannot be assigned a level from XY alone.
    m=MirageLevels();assert m.classify(np.zeros_like(frame),(443/1023,350/1023),1.) is None


def test_underpass_geometry_does_not_open_upper_vertical_shortcut(csgobot_module_path):
    from nav.mirage_levels import MirageLevels,load_grounds
    g=load_grounds(MirageLevels().config)
    point=g['lower'].norm((443,370))
    assert g['lower'].contains(point)
    assert not g['upper'].contains(point)
    for start,end in [((540,258),(470,463)),((470,463),(540,258))]:
        route=g['lower'].plan(g['lower'].norm(start),g['lower'].norm(end))
        assert route and all(g['lower'].visible(a,b) for a,b in zip(route,route[1:]))
        assert all(425<=g['lower'].pixel(x)[0]<=575 for x in route)


@pytest.mark.parametrize('start',[(537,258),(443,330),(447,430)])
def test_lower_spawn_traverses_toward_stairs(csgobot_module_path,start):
    from nav.visual_controller import VisualNavController
    from nav.pose import PoseResult
    from nav.pack import load_nav_pack
    from nav.paths import resolve_nav_pack_path
    import numpy as np
    keys=set();mouse=[]
    c=VisualNavController(load_nav_pack(resolve_nav_pack_path('mirage_visual')),
        SimpleNamespace(fov=SimpleNamespace(x360=3600)),keys.add,keys.discard,
        lambda dx,dy:mouse.append(dx/10),watchdog=False,free_roam=True)
    x,y=map(float,start);yaw=90.;collisions=0;arrived=False
    try:
        for i in range(600):
            now=1+i*.05
            c.tick(PoseResult(x/1023,y/1023,yaw,.95,True,60,'visual',None,now,'lower'),now=now,paused=False)
            yaw+=sum(mouse);mouse.clear()
            assert 'space' not in keys and 'ctrl' not in keys
            f=int('w' in keys)-int('s' in keys);s=int('d' in keys)-int('a' in keys)
            scale=55*.05/max(1,math.hypot(f,s));a=math.radians(yaw)
            nx=x+(f*math.cos(a)-s*math.sin(a))*scale;ny=y+(f*math.sin(a)+s*math.cos(a))*scale
            if c.walkable.visible((x/1023,y/1023),(nx/1023,ny/1023)):x,y=nx,ny
            elif f or s:collisions+=1
            if min(np.linalg.norm(np.array([x,y])-exit['point']) for exit in c._layer_config['lower_exits'])<10:
                arrived=True;break
        assert arrived,(x,y,c.reason,c.path_label)
        assert collisions==0
        assert c._active_layer=='lower'
        c.tick(PoseResult(x/1023,y/1023,yaw,.95,True,60,'visual',None,40,'unknown'),now=40,paused=False)
        assert not keys and c.reason=='unconfirmed_floor'
        c.tick(PoseResult(.6,.5,0,.95,True,60,'visual',None,41,'upper'),now=41,paused=False)
        assert c._active_layer=='upper'
    finally:c.close()


def test_floor_memory_expires_without_self_renewal(csgobot_module_path):
    from nav.mirage_levels import MirageLevels
    from pathlib import Path
    import cv2,numpy as np
    m=MirageLevels();frame=np.zeros((720,1280,3),np.uint8)
    band=cv2.imread(str(Path(__file__).parent/'fixtures/nav_mirage_underpass/label_198.25.png'))
    frame[254:283,:240]=cv2.cvtColor(band,cv2.COLOR_BGR2RGB)
    assert m.classify(frame,(443/1023,330/1023),1.)=='lower'
    blank=np.zeros_like(frame)
    assert m.classify(blank,(443/1023,340/1023),1.2)=='lower'
    assert m.classify(blank,(443/1023,350/1023),1.4)=='lower'
    assert m.last_seen==1.
    assert m.classify(blank,(443/1023,350/1023),1.6) is None
    # A contradictory lower label at unrelated coordinates is rejected.
    assert m.classify(frame,(.8,.8),2.) is None
    m.reset()
    assert m.classify(blank,(443/1023,350/1023),2.1) is None


def test_surface_routes_can_approach_both_underpass_stairs(csgobot_module_path):
    from nav.mirage_levels import MirageLevels,load_grounds
    m=MirageLevels();g=load_grounds(m.config)['upper']
    for start,entry in [((595,237),m.config['upper_entries'][0]),((490,470),m.config['upper_entries'][1])]:
        route=g.plan(g.norm(start),g.norm(entry['point']))
        assert route and all(g.visible(a,b) for a,b in zip(route,route[1:]))
