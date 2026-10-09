import math
from types import SimpleNamespace
import numpy as np


def test_corner_uses_clear_progressing_direction_instead_of_stopping(csgobot_module_path):
    from nav.visual_controller import VisualNavController
    from nav.walkable import WalkableMap
    ground=np.zeros((100,100),np.uint8);ground[5:70,5:95]=255
    w=WalkableMap(ground,clearance_px=3,grid_step=2)
    c=object.__new__(VisualNavController)
    c.walkable=c._base_walkable=w;c._lease=SimpleNamespace(keys=set())
    c._pack=SimpleNamespace(map_id='de_mirage')
    point=w.norm((50,60))
    assert c._travel_keys(point,-25,20,14)==set()  # Original angular restriction.
    c._pack.map_id='de_dust2'
    assert c._travel_keys(point,-25,20,14)=={'w'}
    for angle in np.linspace(-25,5,21):
        end=w.norm((50+14*math.cos(math.radians(angle)),60+14*math.sin(math.radians(angle))))
        assert w.visible(point,end)
        assert math.cos(math.radians(20-angle))>0
    # A truly obstructed route must not acquire movement through this fallback.
    assert c._travel_keys(w.norm((50,66)),90,90,14)==set()


def test_recovered_same_position_keeps_verified_route(csgobot_module_path):
    from nav.visual_controller import VisualNavController
    from nav.walkable import WalkableMap
    from nav.pose import PoseResult
    goal=SimpleNamespace(id='test',x=.8,y=.8,arrive_radius=.009)
    pack=SimpleNamespace(map_id='de_dust2',goal=goal,goals=(goal,),strategy='single',
        route=SimpleNamespace(dwell_at_goal_sec=0),humanize=SimpleNamespace(turn_rate_deg_per_sec=360))
    keys=set();w=WalkableMap(np.full((256,256),255,np.uint8),clearance_px=6,grid_step=2)
    c=VisualNavController(pack,SimpleNamespace(fov=SimpleNamespace(x360=3600)),
        keys.add,keys.discard,lambda *_:None,walkable=w,watchdog=False,free_roam=True)
    try:
        pose=lambda t:PoseResult(.5,.5,0,.95,True,40,'visual',None,t)
        c.tick(pose(1.),now=1.,paused=False)
        c.tick(pose(1.1),now=1.1,paused=False)
        c.tick(pose(1.2),now=1.2,paused=False)
        serial=c._roaming.serial;assert serial>0
        c.tick(PoseResult.invalid(),now=1.5,paused=False);assert not keys
        c.tick(pose(2.6),now=2.6,paused=False)
        assert c.reason=='follow_verified_route'
        assert c._roaming.serial==serial
        c.tick(pose(2.7),now=2.7,paused=True);assert not keys
    finally:c.close()


def test_corridor_permission_is_finite_and_does_not_cross_walls_or_corners(csgobot_module_path):
    from nav.motion_continuity import CorridorPermit,HeadingObservation
    from nav.walkable import WalkableMap
    from nav.pose import PoseResult
    w=WalkableMap(np.full((256,256),255,np.uint8),clearance_px=6,grid_step=2)
    pose=PoseResult(50/255,128/255,0,.95,True,40,'visual',None,1.)
    permit=CorridorPermit.create(pose,w,w.norm((230,128)))
    assert permit and permit.expires_at==1.75
    assert permit.allows(HeadingObservation(0,1.5,'de_dust2'),1.51,w)
    assert not permit.allows(HeadingObservation(0,1.8,'de_dust2'),1.8,w)
    assert not permit.allows(HeadingObservation(25,1.5,'de_dust2'),1.51,w)
    assert not permit.allows(HeadingObservation(0,1.1,'de_dust2'),1.5,w)
    assert not permit.allows(HeadingObservation(0,1.5,'de_mirage'),1.51,w)
    assert not permit.allows(None,1.5,w)
    assert CorridorPermit.create(pose,w,w.norm((75,128))) is None
    blocked=np.full((256,256),255,np.uint8);blocked[:,85:95]=0
    assert CorridorPermit.create(pose,WalkableMap(blocked,clearance_px=6),w.norm((230,128))) is None


def test_controller_bridges_live_heading_gap_but_stops_on_expiry_and_death(csgobot_module_path):
    from nav.visual_controller import VisualNavController
    from nav.walkable import WalkableMap
    from nav.pose import PoseResult
    from nav.motion_continuity import HeadingObservation
    goal=SimpleNamespace(id='test',x=230/255,y=128/255,arrive_radius=.009)
    pack=SimpleNamespace(map_id='de_dust2',goal=goal,goals=(goal,),strategy='single',
        route=SimpleNamespace(dwell_at_goal_sec=0),humanize=SimpleNamespace(turn_rate_deg_per_sec=360))
    keys=set();w=WalkableMap(np.full((256,256),255,np.uint8),clearance_px=6)
    c=VisualNavController(pack,SimpleNamespace(fov=SimpleNamespace(x360=3600)),
        keys.add,keys.discard,lambda *_:None,walkable=w,watchdog=False,free_roam=True)
    # Fixed straight mission removes random goal choice from the dropout test.
    c._needs_attach=False;c._path=(w.norm((50,128)),w.norm((230,128)));c._path_index=1
    c._route_goal=goal
    pose=lambda t:PoseResult(50/255,128/255,0,.95,True,40,'visual',None,t)
    hint=lambda t:HeadingObservation(0,t,'de_dust2')
    try:
        c.tick(pose(1.),now=1.,paused=False,motion_hint=hint(1.))
        assert keys=={'w'} and c._corridor_permit is not None
        for t in (1.1,1.2,1.3,1.4,1.5,1.6,1.7):
            result=c.tick(PoseResult.invalid(),now=t,paused=False,motion_hint=hint(t))
            assert keys=={'w'} and result.reason=='bounded_corridor_continuity'
            assert not result.pose_valid and result.pose_mode=='corridor_permit'
            assert abs(result.pose_age_sec-(t-1.))<1e-8
        c.tick(PoseResult.invalid(),now=1.76,paused=False,motion_hint=hint(1.76));assert not keys
        c.tick(pose(2.),now=2.,paused=False,motion_hint=hint(2.));assert keys
        c.tick(PoseResult.invalid(),now=2.1,paused=False,motion_hint=None);assert not keys
        c.tick(pose(3.),now=3.,paused=False,motion_hint=hint(3.));assert keys
        c.tick(pose(3.1),now=3.1,paused=True,motion_hint=hint(3.1));assert not keys
    finally:c.close()


def test_repeated_short_dropouts_do_not_interrupt_open_corridor_run(csgobot_module_path):
    from nav.visual_controller import VisualNavController
    from nav.walkable import WalkableMap
    from nav.pose import PoseResult
    from nav.motion_continuity import HeadingObservation
    w=WalkableMap(np.full((512,1024),255,np.uint8),clearance_px=6)
    goal=SimpleNamespace(id='straight',x=950/1023,y=256/511,arrive_radius=.009)
    pack=SimpleNamespace(map_id='de_dust2',goal=goal,goals=(goal,),strategy='single',
        route=SimpleNamespace(dwell_at_goal_sec=0),humanize=SimpleNamespace(turn_rate_deg_per_sec=360))
    results=[]
    for continuity in (False,True):
        keys=set();c=VisualNavController(pack,SimpleNamespace(fov=SimpleNamespace(x360=3600)),
            keys.add,keys.discard,lambda *_:None,walkable=w,watchdog=False,free_roam=True)
        c._needs_attach=False;c._path=(w.norm((50,256)),w.norm((950,256)));c._path_index=1;c._route_goal=goal
        moving=0;stops=0;was_moving=False;x=50.
        try:
            for i in range(120):
                t=1+i*.05
                p=PoseResult(x/1023,256/511,0,.95,True,40,'visual',None,t) if i%12<4 else PoseResult.invalid()
                c.tick(p,now=t,paused=False,motion_hint=HeadingObservation(0,t,'de_dust2') if continuity else None)
                moving+=bool(keys);stops+=was_moving and not keys;was_moving=bool(keys)
                nx=x+(55*.05 if 'w' in keys else 0)
                assert w.visible(w.norm((x,256)),w.norm((nx,256)))
                x=nx
            results.append((moving,stops))
        finally:c.close()
    assert results[0]==(40,10)
    assert results[1]==(120,0)


def test_extended_key_lease_still_obeys_capture_freshness(csgobot_module_path):
    from nav.input_lease import KeyLease
    from nav.visual_controller import VisualNavController
    keys=set();clock=[1.]
    lease=KeyLease(keys.add,keys.discard,clock=lambda:clock[0],allowed=lambda:clock[0]-1.<=.25)
    c=object.__new__(VisualNavController);c._lease=lease
    lease.renew(.75);lease.set_keys({'w'});assert keys and c.input_active
    clock[0]=1.26
    assert not c.input_active
    lease.expire();assert not keys
    lease.close()
