import importlib
from types import SimpleNamespace
import numpy as np
import pytest

@pytest.fixture
def env(csgobot_module_path):
    return {n:importlib.import_module('nav.'+n) for n in ('roaming','walkable','pose','visual_controller')}

def make(env):
    goal=SimpleNamespace(id='old',x=.8,y=.8,arrive_radius=.01)
    pack=SimpleNamespace(map_id='test',goal=goal,goals=(goal,),strategy='single',humanize=SimpleNamespace(turn_rate_deg_per_sec=100),route=SimpleNamespace(dwell_at_goal_sec=1))
    ground=env['walkable'].WalkableMap(np.full((400,400),255,np.uint8),clearance_px=3)
    keys=set()
    ctrl=env['visual_controller'].VisualNavController(pack,SimpleNamespace(fov=SimpleNamespace(x360=3600)),keys.add,keys.discard,lambda *_:None,walkable=ground,free_roam=True)
    def tick(t,x=.3,y=.3,yaw=0,valid=True):
        return ctrl.tick(env['pose'].PoseResult(x,y,yaw,.9,valid,20,'visual',None,t),now=t,paused=False)
    for t in (1.,1.05,1.1):tick(t)
    return ctrl,keys,tick

def test_short_repeated_dropouts_never_churn_goal(env):
    c,keys,tick=make(env)
    try:
        selected=c.goal_id
        for i in range(10):
            t=1.2+i*.2
            tick(t,valid=False);assert not keys
            tick(t+.1)
            assert c.goal_id==selected
        tick(5,valid=False)
        assert tick(6.1).reason=='confirm_spawn_position'
        assert not keys
    finally:c.close()

def test_obstacle_replan_only_removes_space_and_is_bounded(env):
    c,_,tick=make(env)
    try:
        c._target=(.8,.3)
        assert c._avoid_failed_direction((.3,.3),2)
        assert not (c.walkable.free & ~c._base_walkable.free).any()
        assert c.walkable.contains((.3,.3))
        for a,b in zip(c._path,c._path[1:]):assert c.walkable.visible(a,b)
        assert c._obstacles
        c._reroutes.extend([2.1,2.2])
        assert not c._avoid_failed_direction((.3,.3),2.3)
        c._restore_ground();assert np.array_equal(c.walkable.free,c._base_walkable.free)
    finally:c.close()

def test_stationary_roaming_cannot_retry_forever(env):
    c,keys,tick=make(env)
    try:
        switched=0
        for i in range(900):
            t=1.15+i*.05
            # Observed yaw follows target, but position never moves.
            import math
            target=c.face_target()
            yaw=math.degrees(math.atan2(target[1]-.3,target[0]-.3))
            switched+=tick(t,yaw=yaw).goal_switch_event
        assert len(c._reroutes)<=3
        assert c.state.value=='blocked' and not keys
    finally:c.close()

def test_large_area_goals_are_not_short_local_hops(env):
    ground=env['walkable'].WalkableMap(np.full((600,600),255,np.uint8),clearance_px=3)
    choose=env['roaming'].RoamingGoals(ground,seed=5)
    origin=(.5,.5)
    choose.observe(origin,10)
    for _ in range(5):
        goal,_=choose.choose(origin,11)
        assert np.linalg.norm(np.array(ground.pixel(origin))-ground.pixel((goal.x,goal.y)))>=100

def test_cached_edges_do_not_cross_thin_wall(env):
    mask=np.full((100,100),255,np.uint8);mask[:,50]=0
    ground=env['walkable'].WalkableMap(mask,clearance_px=1,grid_step=8)
    assert not ground.plan((.3,.5),(.7,.5))
    assert not ground.plan((.3,.5),(.7,.5))


def test_boundary_exit_never_crosses_wall_or_moves_deeper(env):
    mask=np.zeros((100,100),np.uint8);mask[20:80,20:80]=255
    ground=env['walkable'].WalkableMap(mask,clearance_px=6)
    point=(22/99,50/99)
    assert not ground.contains(point)
    target=ground.boundary_exit(point)
    assert target and ground.contains(target)
    assert ground.increasing_clearance(point,target)
    assert not ground.increasing_clearance(point,(19/99,50/99))
    assert ground.boundary_exit((19/99,50/99)) is None


def test_boundary_exit_moves_away_from_wall_and_times_out(env):
    c,keys,tick=make(env)
    try:
        # Raw floor exists at x=2, but the 3px hull clearance is not met.
        c._needs_attach=False
        assert tick(1.9,x=2/399,y=.3,yaw=0).reason=="confirm_boundary_position"
        tick(1.95,x=2/399,y=.3,yaw=0)
        result=tick(2,x=2/399,y=.3,yaw=0)
        assert result.reason=='exit_boundary_toward_clearance' and keys=={'w'}
        result=tick(2.1,x=2/399,y=.3,yaw=180)
        assert keys=={'s'} and result.reason=='exit_boundary_toward_clearance'
        for i in range(65):
            result=tick(2.15+i*.05,x=2/399,y=.3,yaw=0)
        assert result.reason=='boundary_exit_exhausted' and not keys
        result=tick(5.5,x=0,y=.3,yaw=0)
        assert result.reason=='pose_outside_verified_ground' and not keys
    finally:c.close()


@pytest.mark.parametrize('step',[3,4,8])
def test_vectorized_edges_match_exact_visibility(env,step):
    rng=np.random.default_rng(9)
    mask=np.uint8(rng.random((64,64))>.06)*255
    ground=env['walkable'].WalkableMap(mask,clearance_px=1,grid_step=step)
    for y in range(1,ground.grid.shape[0]-1):
        for x in range(1,ground.grid.shape[1]-1):
            for dx,dy in ((1,0),(-1,1),(1,1),(0,-1)):
                a,b=(x,y),(x+dx,y+dy)
                assert ground._edge_clear(a,b)==ground.visible(ground.norm((x*step,y*step)),ground.norm(((x+dx)*step,(y+dy)*step)))


def test_roaming_simulation_completes_multiple_goals_without_collisions(env):
    import math
    c,keys,_=make(env);mouse=[]
    c._move=lambda dx,dy:mouse.append(dx/10)
    c._roaming.rng.seed(11)
    x,y,yaw=.3,.3,0.;switches=0;collisions=0
    try:
        for i in range(2200):
            t=1.15+i*.05
            p=env['pose'].PoseResult(x,y,yaw,.9,True,20,'visual',None,t)
            result=c.tick(p,now=t,paused=False)
            yaw+=sum(mouse);mouse.clear()
            speed=24 if 'shift' in keys else 48
            f=int('w' in keys)-int('s' in keys);side=int('d' in keys)-int('a' in keys)
            length=max(1.,math.hypot(f,side));a=math.radians(yaw)
            nx=x+(f*math.cos(a)-side*math.sin(a))/length*speed*.05/399
            ny=y+(f*math.sin(a)+side*math.cos(a))/length*speed*.05/399
            if not c._base_walkable.visible((x,y),(nx,ny)):collisions+=1
            else:x,y=nx,ny
            switches+=int(result.goal_switch_event)
            if switches>=3:break
        assert switches>=3 and collisions==0
    finally:c.close()


def test_temporary_obstacle_expires_even_when_pose_is_inside_it(env):
    c,_,tick=make(env)
    try:
        center=(.32,.3)
        c._obstacles=[(center,10,3.)]
        c.walkable=c._base_walkable.excluding([(center,10)])
        c._roaming.set_ground(c.walkable)
        assert tick(2,x=.32).reason!='pose_outside_verified_ground'
        assert c.walkable.contains(center)
        result=tick(3.1,x=.32)
        assert result.reason!='pose_outside_verified_ground' and not c._obstacles
    finally:c.close()


def test_pulsed_input_and_short_losses_do_not_hide_wall_stall(env):
    import math
    c,keys,tick=make(env)
    try:
        detected=False
        for i in range(200):
            t=1.15+i*.05
            target=c.face_target();yaw=math.degrees(math.atan2(target[1]-.3,target[0]-.3))
            result=tick(t,yaw=yaw,valid=(i%3!=2))
            assert 'shift' not in keys
            detected |= result.stuck_event
        assert detected
    finally:c.close()


def test_temporary_obstacle_cannot_imprison_measured_body(env):
    c,keys,tick=make(env)
    try:
        point=(.3,.3)
        c._obstacles=[(point,10,60.),((.6,.6),10,60.)]
        c.walkable=c._base_walkable.excluding([(p,r) for p,r,_ in c._obstacles])
        assert not c.walkable.contains(point)
        c._refresh_obstacles(point,2.)
        assert c.walkable.contains(point)
        assert not c.walkable.contains((.6,.6))
        assert not (c.walkable.free & ~c._base_walkable.free).any()
        c._refresh_obstacles(point,61.)
        assert not c._obstacles
    finally:c.close()


def test_heading_changes_use_strafe_without_stopping_stride(env):
    import math
    c,keys,tick=make(env)
    try:
        target=c.face_target()
        bearing=math.degrees(math.atan2(target[1]-.3,target[0]-.3))
        tick(1.2,yaw=bearing)
        assert 'w' in keys
        for i,error in enumerate((27,29,27,31)):
            tick(1.25+i*.05,yaw=bearing-error)
            assert 'w' in keys and 'shift' not in keys
        tick(1.5,yaw=bearing-45)
        assert keys=={'w','d'}
        tick(1.55,yaw=bearing-90)
        assert keys=={'d'}
        tick(1.6,yaw=bearing-20)
        assert 'w' in keys
        tick(1.65,valid=False)
        assert not keys
    finally:c.close()
