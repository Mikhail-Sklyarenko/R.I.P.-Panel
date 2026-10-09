"""Recorded Inferno glare/door regressions and bounded runtime interaction."""
import math
from pathlib import Path
from types import SimpleNamespace
import cv2
import numpy as np
import pytest

FIXTURES=Path(__file__).parent/'fixtures/nav_inferno_v16'


def frame(stamp):
    return cv2.cvtColor(cv2.imread(str(FIXTURES/f'{stamp}.jpg')),cv2.COLOR_BGR2RGB)


def matching(map_id='de_inferno',inferno=True):
    from nav.calibration import load_calibration
    from nav.minimap_reader import MinimapReader
    from nav.paths import resolve_calibration_path,resolve_map_radar_path
    from nav.dense_localizer import DenseMapMatcher
    radar=cv2.cvtColor(cv2.imread(str(resolve_map_radar_path(map_id))),cv2.COLOR_BGR2RGB)
    return MinimapReader(load_calibration(resolve_calibration_path())),DenseMapMatcher(radar,translucent=True,inferno_hud=inferno)


def locate(reader,matcher,rgb):
    from nav.hud_mask import exclude_range_ring
    icon=reader.read(rgb)
    if not icon.valid:return None
    crop,cx,cy,r=reader._crop_from_circle(rgb,reader.last_circle)
    yy,xx=np.ogrid[:crop.shape[0],:crop.shape[1]];d=(xx-cx)**2+(yy-cy)**2
    mask=np.uint8((d<(r-7)**2)&(d>22**2))*255
    mask[cv2.dilate(np.uint8(cv2.cvtColor(crop,cv2.COLOR_RGB2HSV)[:,:,1]>160),np.ones((7,7),np.uint8))>0]=0
    exclude_range_ring(mask,cx,cy,r)
    reg=matcher.match_at_scale(crop,mask,.355)
    return None if reg is None else reg[0]@np.array([*reader.last_icon_xy,1])


@pytest.mark.parametrize('stamp,xy',[(119,(764,223)),(125,(764,223)),(140,(764,223)),(190,(492,859)),(195,(492,859))])
def test_recorded_stops_reacquire_glare_and_masked_door(csgobot_module_path,stamp,xy):
    reader,matcher=matching()
    measured=locate(reader,matcher,frame(stamp))
    assert measured is not None
    assert np.linalg.norm(measured-xy)<8
    from nav.farm_runtime import load_ground
    ground=load_ground('de_inferno')
    assert ground.contains(ground.norm(measured))
    assert ground.plan(ground.norm(measured),ground.norm((900,350)))


@pytest.mark.parametrize('stamp',[119,190])
def test_recorded_failures_reject_wrong_map(csgobot_module_path,stamp):
    for map_id in ('de_dust2','de_mirage','de_cache'):
        reader,matcher=matching(map_id)
        assert locate(reader,matcher,frame(stamp)) is None


def test_blank_and_single_wall_never_supply_position(csgobot_module_path):
    _,m=matching();mask=np.ones((224,224),np.uint8)*255
    for rgb in (np.full((224,224,3),155,np.uint8),np.random.default_rng(3).integers(140,165,(224,224,3),dtype=np.uint8)):
        assert m.match_at_scale(rgb,mask,.355) is None
    rgb=np.full((224,224,3),150,np.uint8);rgb[:,110:]=166
    assert m.match_at_scale(rgb,mask,.355) is None


@pytest.mark.parametrize('stamp,closed',[(119,False),(190,True),(195,True),(198,False)])
def test_real_scene_door_evidence(csgobot_module_path,stamp,closed):
    from nav.door_actions import observe_door
    assert observe_door(frame(stamp),'de_inferno',1).red_panel==closed
    assert observe_door(frame(stamp),'de_mirage',1) is None


def action():
    from nav.traversal_actions import TraversalActions
    return TraversalActions.load('de_inferno')


def cue(now=1,map_id='de_inferno',red=True):
    return SimpleNamespace(observed_at=now,map_id=map_id,red_panel=red)


def apply(a,now=1,point=(492,859),yaw=-90,keys=None,observation=None,target=(490,837)):
    return a.apply({'w'} if keys is None else keys,tuple(v/1023 for v in point),now=now,yaw=yaw,
        target=tuple(v/1023 for v in target),observation=cue(now) if observation is None else observation)


def test_door_single_pulse_crossing_and_no_retoggle_on_pause(csgobot_module_path):
    a=action()
    assert apply(a)=={'w','e'}
    assert a.phase=='door_opening'
    assert apply(a,1.1)=={'w','e'}
    assert apply(a,1.2)=={'w'}
    a.reset()
    assert apply(a,1.3)=={'w'}
    assert apply(a,5)=={'w'}
    assert apply(a,5.1,point=(490,840))=={'w'}
    assert a.phase=='door_crossed'
    apply(a,6,point=(490,790))
    assert apply(a,8)=={'w','e'}


@pytest.mark.parametrize('kwargs',[
    {'point':(492,880)}, {'yaw':90}, {'keys':{'s'}}, {'keys':set()},
    {'observation':cue(0)}, {'observation':cue(2)},
    {'observation':cue(map_id='de_mirage')}, {'observation':cue(red=False)},
    {'target':(490,885)}, {'point':(900,350)},
])
def test_door_never_uses_without_fresh_nearby_entering_intent(csgobot_module_path,kwargs):
    assert 'e' not in apply(action(),**kwargs)


def test_lost_scene_cannot_resume_same_pulse(csgobot_module_path):
    a=action();assert 'e' in apply(a)
    assert 'e' not in apply(a,1.03,observation=cue(1.03,red=False))
    assert 'e' not in apply(a,1.06)


def test_controller_opens_then_crosses_synthetic_door_and_releases(csgobot_module_path):
    from nav.visual_controller import VisualNavController
    from nav.pose import PoseResult
    goal=SimpleNamespace(id='exit',x=490/1023,y=837/1023,arrive_radius=.003)
    pack=SimpleNamespace(map_id='de_inferno',goal=goal,goals=(goal,),strategy='single',
        route=SimpleNamespace(dwell_at_goal_sec=0),humanize=SimpleNamespace(turn_rate_deg_per_sec=300))
    keys=set();mouse=[];presses=[]
    def down(k):keys.add(k);presses.append(k)
    c=VisualNavController(pack,SimpleNamespace(fov=SimpleNamespace(x360=3600)),down,keys.discard,
        lambda dx,dy:mouse.append(dx/10),watchdog=False)
    x,y,yaw=492.,873.,-90.;opened_at=None;collisions=0
    try:
        for i in range(160):
            now=1+i*.05
            pose=PoseResult(x/1023,y/1023,yaw,.95,True,60,'visual',None,now)
            c.tick(pose,now=now,paused=False,door_observation=cue(now,red=opened_at is None or now<opened_at+.35))
            if 'e' in keys and opened_at is None:opened_at=now
            yaw+=sum(mouse);mouse.clear();angle=math.radians(yaw)
            f=int('w' in keys)-int('s' in keys);side=int('d' in keys)-int('a' in keys)
            nx=x+(f*math.cos(angle)-side*math.sin(angle))*45*.05
            ny=y+(f*math.sin(angle)+side*math.cos(angle))*45*.05
            if y>850>=ny and (opened_at is None or now<opened_at+.35):collisions+=1
            elif c.walkable.visible((x/1023,y/1023),(nx/1023,ny/1023)):x,y=nx,ny
            if y<841:break
        assert y<841,(x,y,keys,c.reason,presses)
        assert presses.count('e')==1
        assert collisions<10
        c.tick(PoseResult.invalid(),now=10,paused=True,door_observation=cue(10))
        assert not keys
    finally:c.close()


def test_reverse_approach_requires_same_current_door_evidence(csgobot_module_path):
    a=action()
    assert apply(a,point=(490,841),yaw=90,target=(490,866))=={'w','e'}
    assert apply(action(),point=(490,841),yaw=-90,target=(490,866))=={'w'}


def test_door_use_expires_with_shared_input_lease(csgobot_module_path):
    from nav.input_lease import KeyLease
    keys=set();clock=[1.]
    lease=KeyLease(keys.add,keys.discard,clock=lambda:clock[0])
    lease.renew(.25);lease.set_keys(apply(action()))
    assert keys=={'w','e'}
    clock[0]=1.251;lease.expire()
    assert not keys
