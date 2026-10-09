import importlib
from types import SimpleNamespace
import numpy as np
import pytest

@pytest.fixture
def modules(csgobot_module_path):
    return [importlib.import_module('nav.'+n) for n in ('roaming','walkable','visual_controller','pose','camera_servo')]

def test_goals_stay_in_spawn_component_and_change(modules):
    roaming, walk, *_ = modules
    mask=np.full((160,160),255,np.uint8); mask[:,76:84]=0
    ground=walk.WalkableMap(mask,clearance_px=2)
    chooser=roaming.RoamingGoals(ground,seed=3)
    targets=[]
    for point in ((.2,.3),(.8,.6),(.2,.3)):
        goal,path=chooser.choose(point)
        assert (goal.x<.5)==(point[0]<.5)
        assert all(ground.visible(a,b) for a,b in zip(path,path[1:]))
        targets.append((goal.x,goal.y))
    assert targets[0]!=targets[2]
    assert chooser.choose((.5,.5)) is None

def controller(modules):
    _,walk,ctrl,pose,_=modules
    goal=SimpleNamespace(id='old',x=.8,y=.8,arrive_radius=.01)
    pack=SimpleNamespace(map_id='test',goal=goal,goals=(goal,),strategy='single',humanize=SimpleNamespace(turn_rate_deg_per_sec=100),route=SimpleNamespace(dwell_at_goal_sec=1))
    keys=set(); mask=np.full((200,200),255,np.uint8)
    c=ctrl.VisualNavController(pack,SimpleNamespace(fov=SimpleNamespace(x360=3600)),keys.add,keys.discard,lambda *_:None,walkable=walk.WalkableMap(mask,clearance_px=2),free_roam=True,camera_rate=300)
    return c,keys,pose.PoseResult

def test_spawn_requires_distinct_measurements_and_reselects(modules):
    c,keys,Pose=controller(modules)
    def tick(x,y,t):
        return c.tick(Pose(x,y,0,.9,True,20,'visual',None,t),now=t,paused=False)
    try:
        assert tick(.2,.2,1).reason=='confirm_spawn_position'
        assert tick(.2,.2,1).reason=='confirm_spawn_position'
        assert tick(.2,.2,1.05).reason=='confirm_spawn_position'
        tick(.2,.2,1.1); first=c.goal_id
        assert first.startswith('roam_')
        assert tick(.8,.8,1.15).reason=='confirm_spawn_position'
        assert not keys
        tick(.8,.8,1.2); tick(.8,.8,1.25)
        assert c.goal_id!=first
        goal=c._route_goal
        # Simulate arrival after relocation confirmation if needed.
        for t in (1.3,1.35,1.4): tick(goal.x,goal.y,t)
        assert c.goal_id!=first
    finally:c.close()

def test_short_loss_releases_input_but_preserves_mission(modules):
    c,keys,Pose=controller(modules)
    try:
        for t in (1.,1.05,1.1):c.tick(Pose(.2,.2,0,.9,True,20,'visual',None,t),now=t,paused=False)
        selected=c.goal_id
        c.tick(Pose(.2,.2,0,0,False,0,'visual',None,1.2),now=1.2,paused=False)
        assert not keys
        result=c.tick(Pose(.2,.2,0,.9,True,20,'visual',None,1.25),now=1.25,paused=False)
        assert result.reason!='confirm_spawn_position' and c.goal_id==selected
    finally:c.close()

def test_fast_turn_with_latency_settles_under_1_3_seconds(modules):
    Servo=modules[-1].CameraServo
    now=[1.];yaw=[0.];deltas=[];observations=[]
    def move(dx,dy):yaw[0]+=dx/10;deltas.append(dx/10)
    servo=Servo(move,3600,clock=lambda:now[0])
    for i in range(156):
        now[0]=1+i/120; observations.append((now[0],yaw[0]))
        if i>=6 and i%6==0:
            stamp,value=observations[i-6]
            servo.submit(180-value,stamp,limit=300)
        servo.advance()
    assert abs(yaw[0]-180)<2
    assert max(map(abs,deltas))<=2.6
    before=yaw[0];now[0]+=1;servo.advance();assert yaw[0]==before
    servo.close()


def test_arrival_selects_next_goal_without_scripted_dwell(modules):
    c,keys,Pose=controller(modules)
    try:
        for t in (1.,1.05,1.1):c.tick(Pose(.2,.2,0,.9,True,20,'visual',None,t),now=t,paused=False)
        c._route_goal=SimpleNamespace(id='arriving',x=.2,y=.2,arrive_radius=.01)
        result=c.tick(Pose(.2,.2,0,.9,True,20,'visual',None,1.15),now=1.15,paused=False)
        assert result.goal_switch_event and c.goal_id!='arriving'
    finally:c.close()
