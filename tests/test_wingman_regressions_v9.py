import math
from pathlib import Path
from types import SimpleNamespace as NS
import time
import cv2
import numpy as np
import pytest
from tests.test_wingman_live import runtime,observe,payload

ROOT=Path(__file__).resolve().parents[1]


def reader():
    from nav.minimap_reader import MinimapReader
    from nav.calibration import load_calibration
    from nav.paths import resolve_calibration_path
    result=MinimapReader(load_calibration(resolve_calibration_path()))
    result.competitive_markers=True
    result.objective_overlay_allowed=True
    return result


def frame(t):
    return cv2.cvtColor(cv2.imread(str(ROOT/f'tests/fixtures/wingman/regression_v9/{t}.jpg')),cv2.COLOR_BGR2RGB)


@pytest.mark.parametrize('seconds,expected',[(30,108),(31,128),(148,-162),(150,-120),(210,120)])
def test_visible_tip_survives_white_c4_overlay(csgobot_path,seconds,expected):
    from nav.wingman_icon import observe_objective_tip
    im=frame(seconds);r=reader();r.objective_overlay_allowed=False
    assert not r.read(im).valid
    heading,display=observe_objective_tip(im[:260,:260],130,130,np.zeros((260,260),bool))
    assert display is not None and heading is not None
    assert abs((heading[0]-expected+180)%360-180)<8
    r.objective_overlay_allowed=True
    assert r.read(im).valid and r.last_heading is not None


def test_fully_occluded_tip_is_not_replaced_by_c4_direction(csgobot_path):
    from nav.wingman_icon import observe_objective_tip
    im=frame(212);h,display=observe_objective_tip(im[:260,:260],130,130,np.zeros((260,260),bool))
    assert display is not None and h is None


def test_centered_objective_does_not_substitute_nearby_teammate(csgobot_path):
    r=reader()
    path=ROOT/'tests/fixtures/wingman/regression_v6/218.png'
    im=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB)
    pose=r.read(im)
    assert pose.valid and 95 < pose.yaw_deg < 120
    x,y,_,_=r.last_circle.rect
    assert math.dist((r.last_icon_xy[0]+x,r.last_icon_xy[1]+y),(130,130))<3


def test_current_geometry_and_overlay_tip_produce_pose_not_stale_heading(csgobot_path):
    from nav.async_perception import AsyncVisualPerception
    r=reader();p=AsyncVisualPerception(r,NS(map_id='de_inferno'))
    try:
        im=frame(30)
        assert not p.update(im,now=1.).pose.valid
        pose=p.update(im,now=1.1).pose
        assert pose.valid and pose.observed_at==1.1 and pose.confidence>=.45
        assert math.dist((pose.x_norm*1023,pose.y_norm*1023),(844,703))<10
        assert not p.update(np.zeros_like(im),now=2).pose.valid
    finally:p.close()


def test_objective_owner_excludes_combat_and_obeys_focus(csgobot_path):
    from nav.farm_runtime import CameraOwnership
    moves=[];focus=[True]
    owner=CameraOwnership(lambda dx,dy:moves.append((dx,dy)),lambda:False,
                          objective_allowed=lambda:focus[0])
    owner.select('objective')
    assert not owner.emit('combat',100,100) and not owner.emit('nav',50,50)
    assert owner.emit('objective',1,2)
    focus[0]=False;assert not owner.emit('objective',3,4)
    assert moves==[(1,2)]
    no_opt_in=CameraOwnership(lambda *a:pytest.fail('not opted in'),lambda:True)
    no_opt_in.select('objective');assert not no_opt_in.emit('objective',1,2)


def test_objective_look_stops_on_confirmation_and_restores_only_accepted_pitch(csgobot_path):
    from nav.wingman_objective_look import ObjectiveLook
    look=ObjectiveLook(10);look.begin(90,now=1);moves=[]
    assert not look.tick(lambda *a:False,now=1.1)
    assert look.pitch_sent==0
    for n in range(2,9):look.tick(lambda x,y:moves.append((x,y)) or True,now=1+n*.1)
    assert 640<=sum(y for x,y in moves)<=650 and 880<=sum(x for x,y in moves)<=900
    assert not look.tick(lambda *a:pytest.fail('must hold still'),now=2,confirmed=True)
    look.restore()
    for n in range(1,10):look.tick(lambda x,y:moves.append((x,y)) or True,now=2+n*.1)
    assert sum(y for x,y in moves)==0 and not look.restoring
    assert all(x==0 for x,y in moves if y<0)


def test_late_hud_confirmation_gets_full_defuse_hold(runtime):
    from modules.wingman.visual import VisualEvidence
    r,s,events,focus,c=runtime;observe(r,s,payload(player={'team':'CT'},round={'bomb':'planted'}))
    t=time.monotonic();r.interaction='defuse';r.interaction_at=t
    r.idle_tick(None,now=t+2)
    assert r.interaction=='defuse'
    r.last_hud=VisualEvidence('defusing',1,'recognized_hud_text',t+2.4)
    r.idle_tick(None,now=t+2.4)
    r.idle_tick(None,now=t+12.1)
    assert r.interaction=='defuse' and r.defuse_confirmed_at==t+2.4
    r.idle_tick(None,now=t+14.5)
    assert r.interaction is None and not r.lease.keys


def test_precise_arrival_prepares_look_and_use_but_not_at_old_radius(runtime):
    from tests.test_wingman_ingress_v6 import make
    from nav.wingman_missions import Mission
    from nav.pose import PoseResult
    from nav.farm_runtime import CameraOwnership
    r,s,events,focus,config=runtime;c,i,g,held,yaw=make()
    try:
        observe(r,s,payload(player={'team':'CT'},round={'bomb':'planted'}))
        r.active_role='defuse';r.bomb_point=(852,677);r.mission=Mission((852,677),'defuse')
        now=time.monotonic()
        c.last_pose=PoseResult(*g.norm((852,683)),0,.9,True,20,'visual',None,now)
        r.set_objective(c,now=now)
        assert r.interaction is None
        c.last_pose=PoseResult(*g.norm((852,680)),0,.9,True,20,'visual',None,now)
        r.set_objective(c,now=now)
        assert r.interaction=='defuse' and r.objective_look.active
        moves=[];owner=CameraOwnership(lambda x,y:moves.append((x,y)),lambda:False,
            objective_allowed=r.objective_camera_allowed)
        r.objective_camera=owner;owner.select('objective')
        r.idle_tick(c,now=now+.1)
        assert moves and moves[0][0]<0 and moves[0][1]>0 and 'e' in r.lease.keys
        focus[0]=False
        before=len(moves);r.idle_tick(c,now=now+.2)
        assert len(moves)==before and not r.lease.keys
    finally:c.close()


def test_lost_telemetry_restores_pitch_on_resume_and_new_round_discards_it(runtime):
    r,s,events,focus,c=runtime;observe(r,s,payload(player={'team':'CT'},round={'bomb':'planted'}))
    t=time.monotonic();r.interaction='defuse';r.objective_look.begin(0,now=t)
    r.objective_look.tick(lambda *a:True,now=t+.1)
    assert r.objective_look.pitch_sent>0
    s.latest=None;r.observe(np.zeros((720,1280,3),np.uint8),None,now=t+.15)
    assert r.restoring_camera and r.interaction is None
    observe(r,s,payload(map={'round':1},round={'phase':'freezetime'},player={'team':'CT'}))
    assert not r.restoring_camera and r.objective_look.pitch_sent==0
