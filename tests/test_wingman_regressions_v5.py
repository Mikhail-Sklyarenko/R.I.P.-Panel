import math
from pathlib import Path
import numpy as np
import cv2
from tests.test_wingman_live import runtime
from tests.test_wingman_navigation_v3 import make_controller


def test_cyan_scenery_is_not_a_teammate_name(csgobot_path):
    from aiming.wingman_teams import filter_detections
    frame=np.zeros((720,1280,3),np.uint8);frame[160:190,420:480]=(90,220,240)
    boxes={'c':[{'cls':0,'xyxy':[400,200,500,450]}]}
    assert filter_detections(boxes,frame,{0:'c',1:'ch',2:'t',3:'th'},'T')[0]


def test_recorded_friendly_is_blocked_and_enemy_retained(csgobot_path):
    from aiming.wingman_teams import filter_detections
    root=Path(__file__).parent/'fixtures/wingman/regression_v5'
    for stamp,box,friendly in [(90,[705,299,834,475],True),(270,[610,320,665,444],False)]:
        frame=cv2.cvtColor(cv2.imread(str(root/f'{stamp}.jpg')),cv2.COLOR_BGR2RGB)
        result,_=filter_detections({'c':[{'cls':0,'xyxy':box}]},frame,{0:'c',1:'ch',2:'t',3:'th'},'T')
        assert bool(result) is not friendly


def test_moving_target_ema_lag_fits_small_body_gate(runtime):
    from aiming.aim_point_smoother import AimPointSmoother,AimSmoothConfig
    r,s,e,f,c=runtime
    old=AimPointSmoother(AimSmoothConfig(alpha=.45))
    new=AimPointSmoother(AimSmoothConfig(alpha=c.aim.aim_smooth_alpha))
    for n in range(30):
        t=n/14;x=200+200*t
        old_x,_=old.update(x,360,t);new_x,_=new.update(x,360,t)
    assert x-old_x>15 and x-new_x<3
    assert c.aim.smoothing_factor<=1.5 and not c.aim.adaptive_smoothing


def test_fixed_mission_moves_through_turn_and_releases_on_pose_loss(csgobot_path):
    from nav.pose import PoseResult
    c,g,held,yaw=make_controller();yaw[0]=90;point=np.array([30.,100.]);turning_motion=0;collisions=0
    try:
        for n in range(300):
            t=n*.05;before=yaw[0]
            c.tick(PoseResult(*g.norm(point),before,.99,True,20,'visual',None,t),now=t,paused=False)
            if abs(before)>25 and held:turning_motion+=1
            f=('w'in held)-('s'in held);side=('d'in held)-('a'in held);a=math.radians(yaw[0]);length=max(1.,math.hypot(f,side))
            end=point+np.array([f*math.cos(a)-side*math.sin(a),f*math.sin(a)+side*math.cos(a)])/length
            if g.visible(g.norm(point),g.norm(end)):point=end
            else:collisions+=1
            if c.reason=='goal_reached':break
        assert turning_motion>2 and collisions==0 and c.reason=='goal_reached'
        c.tick(PoseResult.invalid(),now=20,paused=False);assert not held
    finally:c.close()


def test_responsive_servo_finishes_earlier_without_overshoot(csgobot_path):
    from nav.camera_servo import CameraServo
    def duration(responsive):
        clock=[0.];sent=[];c=CameraServo(lambda dx,dy:sent.append(dx/10),3600,clock=lambda:clock[0])
        for n in range(120):
            clock[0]=n/120
            if n%6==0:c.submit(90-sum(sent),clock[0],limit=360,responsive=responsive)
            c.advance()
            assert sum(sent)<=90.1
            if 90-sum(sent)<=1.5:return clock[0]
        raise AssertionError('did not settle')
    assert duration(True)<duration(False)


def test_patrol_prefers_continuing_over_unnecessary_reversal(csgobot_path):
    from nav.wingman_missions import MissionPlanner
    from nav.walkable import WalkableMap
    import random
    g=WalkableMap(np.full((200,200),255,np.uint8),clearance_px=2)
    p=MissionPlanner({'patrol_points':[(40,100),(160,100)]},rng=random.Random(4))
    m=p.choose(g,g.norm((100,100)),team='CT',bomb='not_carried_self',incoming=(20,0))
    assert m.point==(160,100)
