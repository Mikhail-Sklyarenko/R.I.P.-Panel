from pathlib import Path
from types import SimpleNamespace as NS
import math
import numpy as np
import cv2
from tests.test_wingman_live import runtime

ROOT=Path(__file__).resolve().parents[1]
NAMES={0:'c',1:'ch',2:'t',3:'th'}


def box(cls,xy,conf=.9):return {'cls':cls,'xyxy':xy,'conf':conf}


def test_visible_edge_enemy_from_recording_can_acquire_combat(runtime,csgobot_path):
    from config import AimConfig,CaptureRegion,Team
    from aiming.target_selector import TargetSelector
    from aiming.wingman_target import WingmanTargetLock
    from aiming.wingman_teams import filter_detections
    r,s,e,f,c=runtime
    frame=cv2.cvtColor(cv2.imread(str(ROOT/'tests/fixtures/wingman/regression_v7/44.jpg')),cv2.COLOR_BGR2RGB)
    eligible,_=filter_detections({'c':[box(0,[90,335,172,476])]},frame,NAMES,'T')
    selector=TargetSelector(AimConfig(current_team=Team.T),CaptureRegion(width=1280,height=720))
    assert selector.select_best_target(eligible,max_distance=320) is None
    selector.config.max_assist_distance=c.aim.max_assist_distance
    target=WingmanTargetLock().select(selector,eligible,now=1)
    assert target is not None and target.distance>500


def test_body_lock_ignores_head_confidence_flicker_and_nearer_second_player(csgobot_path):
    from config import AimConfig,CaptureRegion,Team
    from aiming.target_selector import TargetSelector
    from aiming.wingman_target import WingmanTargetLock
    selector=TargetSelector(AimConfig(current_team=Team.T,max_assist_distance=735),CaptureRegion(width=1280,height=720))
    lock=WingmanTargetLock()
    ys=[]
    for n in range(8):
        detections={'c':[box(0,[620,345,670,480])], 'ch':[box(1,[628,340,658,375],.95 if n%2 else .51)]}
        if n>0:detections['c'].append(box(0,[630,330,650,420]))
        target=lock.select(selector,detections,now=1+n*.04)
        assert not target.is_head and target.width==50
        ys.append(target.aim_y)
    assert max(ys)==min(ys)
    assert lock.select(selector,{},now=1.33) is None
    assert lock.select(selector,{'c':[box(0,[700,300,760,450])]},now=2).x1==700


def test_target_lock_transports_previous_box_through_camera_motion(csgobot_path):
    from config import AimConfig,CaptureRegion,Team
    from aiming.target_selector import TargetSelector
    from aiming.wingman_target import WingmanTargetLock
    selector=TargetSelector(AimConfig(current_team=Team.T,max_assist_distance=735),CaptureRegion(width=1280,height=720))
    lock=WingmanTargetLock();lock.select(selector,{'c':[box(0,[760,300,810,480])]},now=1)
    t=lock.select(selector,{'c':[box(0,[660,300,710,480]),box(0,[630,310,650,430])]},now=1.05,
        project=lambda x,y,start,end:(x-100,y))
    assert t.x1==660


def test_filtered_full_frame_does_not_disable_roi_and_rgb_is_converted(csgobot_path):
    from detectors.wingman_detect import detect_wingman
    image=np.zeros((720,1280,3),np.uint8);image[:]=(30,20,10)
    cv2.putText(image,'BOT',(425,187),cv2.FONT_HERSHEY_SIMPLEX,.5,(90,220,240),1)
    seen=[]
    class Fake:
        model=NS(names=NAMES)
        def detect(self,im):
            seen.append(im.copy())
            if len(seen)==1:return {'c':[box(0,[400,200,500,450])]}
            return {'c':[box(0,[640,160,690,310])]}
    cfg=NS(class_confidence_thresholds={},roi_enabled=True,roi_fraction=.75)
    detections,used,reason,counts=detect_wingman(Fake(),image,cfg,'T')
    assert used and len(seen)==2 and counts['c']==2
    assert seen[0][0,0].tolist()==[10,20,30] and image[0,0].tolist()==[30,20,10]
    assert detections['c'][0]['xyxy']==[800,250,850,400] and len(detections['c'])==1


def test_wrong_model_classes_never_retry_or_authorize_target(csgobot_path):
    from detectors.wingman_detect import detect_wingman
    seen=[]
    detector=NS(model=NS(names={0:'person'}),detect=lambda im:seen.append(1) or {'person':[box(0,[1,1,20,100])]})
    result=detect_wingman(detector,np.zeros((720,1280,3),np.uint8),NS(class_confidence_thresholds={},roi_enabled=True,roi_fraction=.75),'T')
    assert not result[0] and not result[1] and len(seen)==1


def test_camera_handoff_accounts_nav_and_combat_once_and_rejected_never(csgobot_path):
    from nav.farm_runtime import CameraOwnership
    from aiming.aim_mouse_controller import AimMouseController
    from aiming.fov_mouse import FOVMouseMovement
    from config import AimConfig,CaptureRegion,FOVConfig
    clock=[10.];accepted=[];gate=CameraOwnership(lambda x,y:accepted.append((x,y)),lambda:True,clock=lambda:clock[0])
    fov=FOVMouseMovement(CaptureRegion(width=1280,height=720),FOVConfig(x360=3600))
    ctrl=AimMouseController(config=AimConfig(),fov_mouse=fov,command_history=gate.commands_since)
    gate.select('nav');gate.emit('nav',100,0)
    clock[0]=10.05;gate.select('combat');assert not gate.emit('nav',500,0);gate.emit('combat',50,20)
    ctrl._sent.append((10.05,50,20)) # local echo must not count twice
    actual=ctrl.project_point(800,400,9.99)
    ax,ay=fov.screen_to_angle(800,400)
    expected=(fov._center_x+fov._focal_x*math.tan(math.radians(ax-15)),
              fov._center_y+fov._focal_y*math.tan(math.radians(ay-2)))
    assert np.allclose(actual,expected)
    assert gate.commands_since(9.99,10.01)==((10.,100,0),)
    rejected=CameraOwnership(lambda x,y:False,lambda:True);rejected.select('combat')
    assert not rejected.emit('combat',30,0) and not rejected.commands_since(0)


def test_second_mid_route_does_not_use_rejected_short_stair(csgobot_path):
    from nav.wingman_ingress import WingmanIngress
    i=WingmanIngress(ROOT/'resources/wingman/inferno');route,g,points=i.routes['apartments']
    path=g.plan(g.norm((529,677)),points[0]);assert path
    assert not g.contains(g.norm((695,730)))
    assert g.contains(g.norm((605,894))) and g.contains(g.norm((671,905)))
    assert points[0][0]<.6 and route['via'].startswith('T spawn -> second mid')


def test_combat_output_precedes_navigation_wait_in_worker():
    import ast
    tree=ast.parse((ROOT/'vendor/csgobot/main.py').read_text())
    worker=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='detection_process')
    calls=[n for n in ast.walk(worker) if isinstance(n,ast.Call)]
    send=next(n.lineno for n in calls if isinstance(n.func,ast.Attribute) and n.func.attr=='set_target')
    wait=next(n.lineno for n in calls if isinstance(n.func,ast.Attribute) and n.func.attr=='result' and isinstance(n.func.value,ast.Name) and n.func.value.id=='nav_job')
    assert send<wait


def test_faster_acquisition_remains_bounded_and_settles_without_vertical_reversal(csgobot_path,monkeypatch):
    from aiming.aim_mouse_controller import AimMouseController
    from aiming.fov_mouse import FOVMouseMovement
    from config import AimConfig,CaptureRegion,FOVConfig
    from aiming import aim_mouse_controller as module
    def run(near,far,y_scale):
        clock=[10.];moves=[]
        monkeypatch.setattr(module.time,'monotonic',lambda:clock[0])
        cfg=AimConfig(mouse_hz=120,mouse_step_max_delta=far,aim_near_step_max_delta=near,
            aim_near_y_scale=y_scale,aim_settle_px=1.5,aim_unlock_px=3,
            aim_dead_zone_high=2,aim_dead_zone_low=1,mouse_min_delta=0,mouse_coast=False)
        ctrl=AimMouseController(config=cfg,fov_mouse=FOVMouseMovement(
            CaptureRegion(width=1280,height=720),FOVConfig(x360=7792)))
        ctrl._apply_mouse=lambda x,y:moves.append((x,y))
        ctrl.set_target(740,400,smoothing=1.4,now=10)
        class Stop:
            def wait(self,period):
                clock[0]+=period
                return ctrl.is_settled or clock[0]>10.24
        ctrl._thread_stop=Stop();ctrl._mouse_loop()
        assert ctrl.last_pixel_distance<=2 and moves
        assert all(abs(x)<=far and abs(y)<=far and y>=0 for x,y in moves)
        return clock[0]-10
    old=run(8,32,.85);new=run(16,48,1.)
    assert new<old
