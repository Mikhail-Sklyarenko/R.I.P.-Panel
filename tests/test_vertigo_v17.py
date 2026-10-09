"""Vertigo recorded spawn/corner evidence and route/controller regression cases."""
import math
from pathlib import Path
from types import SimpleNamespace
import cv2
import numpy as np
import pytest


def recorded(stamp):
    band=cv2.imread(str(Path(__file__).parent/f'fixtures/nav_vertigo_v17/radar_{stamp}.png'))
    image=np.zeros((720,1280,3),np.uint8)
    image[:band.shape[0],:band.shape[1]]=cv2.cvtColor(band,cv2.COLOR_BGR2RGB)
    return image


@pytest.mark.parametrize('stamp',[26,32,36])
def test_t_spawn_glare_reacquires_current_lower_floor(csgobot_module_path,stamp):
    from nav.async_perception import AsyncVisualPerception
    from nav.calibration import load_calibration
    from nav.paths import resolve_calibration_path
    from nav.minimap_reader import MinimapReader
    p=AsyncVisualPerception(MinimapReader(load_calibration(resolve_calibration_path())),SimpleNamespace(map_id='de_vertigo',ready=False))
    try:
        p.update(recorded(stamp),now=1.)
        pose=p.update(recorded(stamp),now=1.1).pose
        assert pose.valid and pose.layer_id=='lower' and pose.observed_at==1.1
        assert 350<pose.x_norm*1023<385 and 695<pose.y_norm*1023<735
        p.reload_map('de_inferno')
        assert p._dense_fast is None and p._accepted is None
    finally:p.close()


def grounds():
    from nav.walkable import WalkableMap
    return {l:WalkableMap.load(m)for l,m in [('upper','de_vertigo'),('lower','de_vertigo_lower')]}


@pytest.mark.parametrize('pixel',[(350,560),(358,551),(349,557),(350,563)])
def test_recorded_occupied_corner_can_rejoin_passage(csgobot_module_path,pixel):
    g=grounds()['lower'];p=g.norm(pixel)
    assert g.contains(p)
    path=g.plan(p,g.norm((367,500)))
    assert path and all(g.visible(a,b) for a,b in zip(path,path[1:]))
    # The edit is local; upper-floor occupancy and adjacent solid wall remain separate.
    assert not g.contains(g.norm((350,530)))


def test_ramp_routes_around_restored_top_barrier(csgobot_module_path):
    g=grounds()['upper']
    assert not g.visible(g.norm((607,625)),g.norm((607,657)))
    assert not g.contains(g.norm((550,620))) # crate overwritten by old broad fill
    path=g.plan(g.norm((607,625)),g.norm((609,759)))
    assert path and all(g.visible(a,b)for a,b in zip(path,path[1:]))
    assert any(x*1023<531 or x*1023>689 for x,y in path)


def controller(layer='lower',start=(350,560),end=(367,500)):
    from nav.visual_controller import VisualNavController
    goal=SimpleNamespace(id='test_exit',x=end[0]/1023,y=end[1]/1023,arrive_radius=.003)
    pack=SimpleNamespace(map_id='de_vertigo',goal=goal,goals=(goal,),strategy='single',route=SimpleNamespace(dwell_at_goal_sec=0),humanize=SimpleNamespace(turn_rate_deg_per_sec=300))
    keys=set();mouse=[]
    c=VisualNavController(pack,SimpleNamespace(fov=SimpleNamespace(x360=3600)),keys.add,keys.discard,lambda dx,dy:mouse.append(dx/10),watchdog=False,free_roam=True)
    c.reload_pack(pack,layer_id=layer);c._roaming=None;c._needs_attach=False
    return c,keys,mouse


@pytest.mark.parametrize('start,end',[((350,560),(367,500)),((367,500),(330,574)),((357,551),(330,574))])
def test_controller_narrow_passage_with_measurement_jitter(csgobot_module_path,start,end):
    from nav.pose import PoseResult
    c,keys,mouse=controller(start=start,end=end);x,y=map(float,start);yaw=-90.;collisions=0
    try:
        for i in range(360):
            now=1+i*.05
            p=PoseResult((x+.65*math.sin(i))/1023,(y+.65*math.cos(i))/1023,yaw,.9,True,radar_mode='visual',observed_at=now,layer_id='lower')
            c.tick(p,now=now,paused=False);yaw+=sum(mouse);mouse.clear()
            f=int('w'in keys)-int('s'in keys);side=int('d'in keys)-int('a'in keys);size=max(1,math.hypot(f,side));a=math.radians(yaw)
            nx=x+(f*math.cos(a)-side*math.sin(a))*45*.05/size
            ny=y+(f*math.sin(a)+side*math.cos(a))*45*.05/size
            if c.walkable.visible((x/1023,y/1023),(nx/1023,ny/1023)):x,y=nx,ny
            elif f or side:collisions+=1
            if math.dist((x,y),end)<4:break
        assert math.dist((x,y),end)<4,(x,y,c.reason,keys)
        assert collisions<3
        c.tick(PoseResult.invalid(),now=30,paused=True)
        assert not keys
    finally:c.close()


def test_boundary_target_prefers_interior_over_nearest_pixel(csgobot_module_path):
    from nav.walkable import WalkableMap
    mask=np.zeros((80,80),np.uint8);mask[10:70,20:60]=255
    g=WalkableMap(mask,clearance_px=4)
    p=g.norm((22,40));normal=g.boundary_exit(p);interior=g.boundary_exit(p,prefer_interior=True)
    assert g.clearance_at(interior)>=8
    assert g.clearance_at(interior)>g.clearance_at(normal)
    assert g.increasing_clearance(p,interior)


@pytest.mark.parametrize('old,new,point,end',[('upper','lower',(650,760),(609,759)),('lower','upper',(700,754),(741,722))])
def test_portal_destination_survives_measured_floor_change(csgobot_module_path,old,new,point,end):
    from nav.pose import PoseResult
    c,keys,_=controller(layer=old)
    try:
        c._route_goal=SimpleNamespace(id='portal_a_ramp',x=end[0]/1023,y=end[1]/1023,arrive_radius=.006)
        c._last_measured_point=(point[0]/1023,point[1]/1023)
        p=PoseResult(*c._last_measured_point,0,.9,True,radar_mode='visual',observed_at=1.,layer_id=new)
        c.tick(p,now=1.,paused=False)
        assert c._active_layer==new
        assert c._route_goal.id=='portal_a_ramp'
        assert c._path and not c._needs_attach
        assert not c._obstacles
    finally:c.close()


def test_lower_recorded_ramp_passage_is_not_blocked_by_upper_wall(csgobot_module_path):
    g=grounds()['lower']
    assert g.visible(g.norm((624,590)),g.norm((630,692)))
    assert not grounds()['upper'].visible(g.norm((624,590)),g.norm((630,692)))


@pytest.mark.parametrize('change',[{'score':.72},{'recall':.90},{'precision':.70},{'support':200},{'area':.15}])
def test_geometric_floor_fallback_rejects_weak_floor_evidence(csgobot_module_path,change):
    from nav.layered_localizer import LayeredDenseMatcher
    m=LayeredDenseMatcher.__new__(LayeredDenseMatcher)
    radar=np.zeros((400,400,3),np.uint8);m.radars={'upper':radar,'lower':radar}
    matrix=np.array([[1.,0,0],[0,1.,0]])
    lower=dict(score=.8,uniqueness=.3,recall=.97,precision=.86,area=.4,support=800);lower.update(change)
    upper=dict(lower,score=.65)
    m.matchers={k:SimpleNamespace(last_evidence=e,match_at_scale=lambda *a:(matrix,.9,800)) for k,e in [('upper',upper),('lower',lower)]}
    assert m.match_at_scale(np.full((224,224,3),120,np.uint8),np.full((224,224),255,np.uint8),.355) is None


def test_boundary_does_not_reuse_distant_old_exit(csgobot_module_path):
    from nav.walkable import WalkableMap
    from nav.pose import PoseResult
    c,_,_=controller()
    mask=np.zeros((80,80),np.uint8);mask[10:70,20:60]=255
    g=WalkableMap(mask,clearance_px=4)
    try:
        c.walkable=c._base_walkable=g;c._needs_attach=False
        point=g.norm((22,40));c._boundary_target=g.norm((35,40))
        p=PoseResult(*point,0,.9,True,radar_mode='visual',observed_at=1.,layer_id='lower')
        c.last_pose=p;c._last_tick=1.
        assert c._boundary_step(point,p,1.,.05)
        assert math.dist(g.pixel(point),g.pixel(c._boundary_target))<=12
    finally:c.close()
