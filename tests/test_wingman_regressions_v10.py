"""Recorded Sep 23 stalls: dark marker, offset C4 and balcony landing."""
import math
from pathlib import Path
from types import SimpleNamespace as NS
import cv2
import numpy as np
import pytest
from tests.test_wingman_live import runtime

ROOT=Path(__file__).resolve().parents[1]


def frame(t):
    # Lossless radar pixels from the original recording, never re-encoded JPEG.
    crop=cv2.cvtColor(cv2.imread(str(ROOT/f'tests/fixtures/wingman/regression_v10/{t}.png')),cv2.COLOR_BGR2RGB)
    im=np.zeros((720,1280,3),np.uint8);im[:260,:260]=crop
    return im


def reader(planted=False):
    from nav.minimap_reader import MinimapReader
    from nav.calibration import load_calibration
    from nav.paths import resolve_calibration_path
    r=MinimapReader(load_calibration(resolve_calibration_path()))
    r.competitive_markers=True;r.objective_overlay_allowed=planted
    return r


@pytest.mark.parametrize('t,heading',[(35,-60),(220,-20),(275,-157),(300,-157),(330,-155)])
def test_dark_purple_body_preserves_visible_heading(csgobot_path,t,heading):
    r=reader();pose=r.read(frame(t))
    assert pose.valid and abs((pose.yaw_deg-heading+180)%360-180)<12
    x,y,_,_=r.last_circle.rect
    assert math.dist((r.last_icon_xy[0]+x,r.last_icon_xy[1]+y),(130,130))<3


@pytest.mark.parametrize('t,heading',[(145,-12),(407,-68),(452,-14)])
def test_offset_bomb_display_does_not_replace_own_tip(csgobot_path,t,heading):
    r=reader(True);pose=r.read(frame(t))
    assert pose.valid and abs((pose.yaw_deg-heading+180)%360-180)<15


def test_nearby_teammate_without_own_tip_is_rejected(csgobot_path):
    # Keep the northern teammate, erase the actual own SOUTH tip; a purple
    # body alone must never authorize a heading or take the teammate's tip.
    p=ROOT/'tests/fixtures/wingman/regression_v6/218.png'
    im=cv2.cvtColor(cv2.imread(str(p)),cv2.COLOR_BGR2RGB)
    im[133:144,120:139]=[90,75,65]
    assert not reader().read(im).valid
    assert not reader(True).read(im).valid


@pytest.mark.parametrize('t,xy,planted',[(275,(832,685),False),(145,(842,727),True),(452,(841,684),True)])
def test_stall_frames_recover_current_world_position(csgobot_path,t,xy,planted):
    from nav.async_perception import AsyncVisualPerception
    r=reader(planted);p=AsyncVisualPerception(r,NS(map_id='de_inferno'))
    try:
        im=frame(t);p.update(im,now=1.)
        pose=p.update(im,now=1.1).pose
        assert pose.valid and math.dist((pose.x_norm*1023,pose.y_norm*1023),xy)<8
        assert not p.update(np.zeros_like(im),now=1.2).pose.valid
    finally:p.close()


def test_landing_requires_new_measurements_and_restores_base(csgobot_path):
    from tests.test_wingman_ingress_v6 import make
    from nav.pose import PoseResult
    c,i,g,held,yaw=make()
    try:
        i.counts.update({'long':5,'short':5})
        pose=PoseResult(*g.norm((529,677)),0,.99,True,20,'visual',None,1.)
        assert i.update(c,pose,team='T',bomb='carried_self',now=1.)==('started','apartments')
        i.stage=3
        landing=PoseResult(*g.norm((880,808)),-63,.9,True,20,'visual',None,2.)
        assert not c.walkable.contains((landing.x_norm,landing.y_norm))
        assert i.update(c,landing,team='T',bomb='carried_self',now=2.)[0]=='active'
        # Reusing a stale pose for a whole second is not a second measurement.
        assert i.update(c,landing,team='T',bomb='carried_self',now=3.)[0]=='active'
        landing=PoseResult(*g.norm((880,807)),-63,.9,True,20,'visual',None,3.1)
        assert i.update(c,landing,team='T',bomb='carried_self',now=3.1)==('finished','apartments')
        assert c.walkable is g and g.plan(g.norm((880,807)),g.norm((848,702)))
    finally:c.close()


@pytest.mark.parametrize('point,stage',[((835,824),3),((880,808),1),((700,800),3)])
def test_upper_floor_or_unconfirmed_stage_does_not_handoff(csgobot_path,point,stage):
    from tests.test_wingman_ingress_v6 import make
    from nav.pose import PoseResult
    c,i,g,held,yaw=make()
    try:
        i.counts.update({'long':5,'short':5})
        pose=PoseResult(*g.norm((529,677)),0,.99,True,20,'visual',None,1.)
        i.update(c,pose,team='T',bomb='carried_self',now=1.);i.stage=stage
        for stamp in (2.,3.,4.):
            pose=PoseResult(*g.norm(point),0,.99,True,20,'visual',None,stamp)
            assert i.update(c,pose,team='T',bomb='carried_self',now=stamp)[0]=='active'
        assert c.walkable is not g
    finally:c.close()


def test_recorded_postplant_pose_drives_movement_not_only_a_guard_label(runtime):
    import time
    from tests.test_wingman_live import observe,payload
    from tests.test_wingman_ingress_v6 import make
    from nav.async_perception import AsyncVisualPerception
    r,s,events,focus,config=runtime;c,i,g,held,yaw=make()
    p=AsyncVisualPerception(reader(True),NS(map_id='de_inferno'))
    try:
        observe(r,s,payload(round={'bomb':'planted'}))
        t=time.monotonic();p.update(frame(145),now=t)
        measured=p.update(frame(145),now=t+.1).pose
        assert measured.valid
        deadline=time.monotonic()+3
        from dataclasses import replace
        while time.monotonic()<deadline:
            now=time.monotonic();c.last_pose=replace(measured,observed_at=now)
            r.set_objective(c,now=now)
            if r.mission:break
            time.sleep(.005)
        assert r.mission is not None and r.mission.action=='guard'
        # Actual controller must issue a movement key, not just select a goal.
        for n in range(20):
            now=time.monotonic();pose=replace(measured,observed_at=now,yaw_deg=yaw[0])
            c.tick(pose,now=now+n*.05,paused=False)
            if held & {'w','a','s','d'}:break
        assert held & {'w','a','s','d'},c.reason
    finally:p.close();c.close()
