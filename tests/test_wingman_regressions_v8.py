import json
import math
from pathlib import Path
import random
from types import SimpleNamespace as NS
import time
import cv2
import numpy as np
import pytest
from tests.test_wingman_live import runtime, payload, observe

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('active',['weapon_c4','weapon_knife','weapon_flashbang'])
def test_restore_owned_primary_without_buying(runtime,active):
    r,s,events,focus,c=runtime
    p=payload(player={'weapons':{'a':{'name':active,'state':'active'},
                               'b':{'name':'weapon_ak47','state':'holstered'}}})
    observe(r,s,p)
    assert events==[('press','1')] and r.purchase is None
    observe(r,s,p)
    assert events==[('press','1')]


def test_equipment_acknowledgement_retry_bound_and_pistol_fallback(csgobot_path):
    from nav.wingman_recovery import WeaponSelection
    w=WeaponSelection();s=NS(active_weapon='weapon_c4',weapons=('weapon_c4','weapon_glock'))
    assert w.choose(s,now=1,allowed=False) is None
    assert [w.choose(s,now=t,allowed=True) for t in (1,1.2,1.7,2.4,4)]==['2',None,'2','2',None]
    s.active_weapon='weapon_glock';assert w.choose(s,now=5,allowed=True) is None
    s.active_weapon='weapon_c4';assert w.choose(s,now=6,allowed=True)=='2'


def test_no_weapon_switch_during_plant_or_defuse(runtime):
    r,s,events,focus,c=runtime;observe(r,s,payload())
    p=payload(player={'weapons':{'a':{'name':'weapon_c4','state':'active'},
                               'b':{'name':'weapon_ak47','state':'holstered'}}})
    for action in ('plant','defuse'):
        r.interaction=action;observe(r,s,p)
    assert not events


def test_blind_heading_scan_removed_from_live_worker():
    # Superseded by current-image C4/tip separation in fix 9.
    source=(ROOT/'vendor/csgobot/main.py').read_text()
    assert 'recover_heading(' not in source


def test_garage_door_requires_lower_bend_and_failed_entry_retreats(csgobot_path):
    from tests.test_wingman_ingress_v6 import make
    from nav.pose import PoseResult
    c,i,g,held,yaw=make();i.counts.update(long=5,short=5)
    try:
        def pose(xy,t):return PoseResult(*g.norm(xy),0,.99,True,20,'visual',None,t)
        c.last_pose=pose((529,677),1)
        assert i.update(c,c.last_pose,team='T',bomb='carried_self',now=1)[0]=='started'
        route,ground,points=i.routes['apartments']
        assert ground.contains(ground.norm((631,921)))
        assert not ground.visible(ground.norm((611,890)),ground.norm((671,905)))
        assert ground.pixel((c._route_goal.x,c._route_goal.y))==pytest.approx((611,917))
        c.reason='recovery_exhausted';p=pose((611,890),10)
        assert i.update(c,p,team='T',bomb='carried_self',now=10)[0]=='active'
        assert i.update(c,p,team='T',bomb='carried_self',now=11.1)[0]=='retreating'
        assert i.retreating and c._route_goal.id.endswith('retreat')
        assert i.update(c,pose((529,677),12),team='T',bomb='carried_self',now=12)[0]=='aborted'
        assert c.walkable is g and i.used and not held
    finally:c.close()


@pytest.mark.parametrize('seed',[2,17,41])
def test_ct_patrol_visits_short_and_long(csgobot_path,seed):
    from nav.wingman_missions import MissionPlanner
    from nav.wingman_runtime import load_ground
    g=load_ground('de_inferno');p=MissionPlanner(json.loads((ROOT/'resources/wingman/inferno/objectives.json').read_text()),rng=random.Random(seed))
    current=g.norm((882,644));incoming=None;visited=[]
    for _ in range(18):
        mission=p.choose(g,current,team='CT',bomb='not_carried_self',incoming=incoming)
        assert mission and g.plan(current,g.norm(mission.point))
        xy=g.pixel(current);incoming=(mission.point[0]-xy[0],mission.point[1]-xy[1])
        visited.append(mission.point);current=g.norm(mission.point);p.complete()
    assert any(y>750 for x,y in visited) and any(y<620 for x,y in visited)


def test_planted_transition_releases_attack_and_schedules_guard(runtime):
    from tests.test_wingman_ingress_v6 import make
    from nav.pose import PoseResult
    r,s,events,focus,config=runtime;c,i,g,held,yaw=make()
    try:
        observe(r,s,payload());r.interaction='plant';r.interaction_at=time.monotonic()
        r.idle_tick(c,now=time.monotonic());assert r.lease.keys
        observe(r,s,payload(round={'bomb':'planted'}))
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            now=time.monotonic();c.last_pose=PoseResult(*g.norm((832,734)),0,.99,True,20,'visual',None,now)
            r.set_objective(c,now=now)
            if r.mission:break
            time.sleep(.005)
        assert r.interaction is None and not r.lease.keys
        assert r.mission.action=='guard' and math.dist(r.mission.point,(832,734))>=28
    finally:c.close()


def test_recorded_c4_location_is_consistent_without_player_heading(csgobot_path):
    from nav.wingman_bomb import BombReader,BombTracker
    from nav.paths import resolve_map_radar_path
    radar=cv2.cvtColor(cv2.imread(str(resolve_map_radar_path('de_inferno'))),cv2.COLOR_BGR2RGB)
    reader=BombReader(radar);tracker=BombTracker(reader)
    try:
        for t in (532,534,536):
            image=cv2.cvtColor(cv2.imread(str(ROOT/f'tests/fixtures/wingman/regression_v8/{t}.jpg')),cv2.COLOR_BGR2RGB)
            point=reader.read(image);assert point is not None
            assert math.dist(point,(838,716))<4
            tracker.accept(point)
        assert tracker.point is not None and math.dist(tracker.point,(838,716))<3
        tracker.update(np.zeros((720,1280,3),np.uint8),context=('new_round',),now=1)
        assert tracker.point is None
    finally:tracker.close()


def test_bomb_glyph_rejects_enemy_circle_and_ambiguous_candidates(csgobot_path):
    from nav.wingman_bomb import BombReader
    rgb=np.zeros((224,224,3),np.uint8)
    cv2.circle(rgb,(95,95),5,(255,0,0),-1)
    assert not BombReader.glyphs(rgb,112,112,106)
    cv2.rectangle(rgb,(108,108),(117,115),(255,0,0),-1)
    assert len(BombReader.glyphs(rgb,112,112,106))==1


def test_defuse_approaches_observed_bomb_before_grid_and_failed_probe_moves(csgobot_path):
    from nav.wingman_missions import MissionPlanner
    from nav.wingman_runtime import load_ground
    g=load_ground('de_inferno');p=MissionPlanner(json.loads((ROOT/'resources/wingman/inferno/objectives.json').read_text()))
    p.bomb_point=(838,716)
    first=p.choose(g,g.norm((832,750)),team='CT',bomb='planted')
    assert first.action=='defuse' and math.dist(first.point,p.bomb_point)<=6
    p.complete()
    second=p.choose(g,g.norm(first.point),team='CT',bomb='planted')
    assert second.point!=first.point


def test_defuse_probe_waits_for_hud_then_latches(runtime):
    from modules.wingman.visual import VisualEvidence
    r,s,events,focus,c=runtime;observe(r,s,payload(player={'team':'CT'},round={'bomb':'planted'}))
    now=time.monotonic();r.interaction='defuse';r.interaction_at=now
    r.idle_tick(None,now=now+1)
    assert r.interaction=='defuse' and r.lease.keys=={'e'}
    r.last_hud=VisualEvidence('defusing',1.,'recognized_hud_text',now+1.1)
    r.idle_tick(None,now=now+1.1)
    r.last_hud=VisualEvidence('unknown',0.,'no_verified_overlay',now+2)
    r.idle_tick(None,now=now+2)
    assert r.interaction=='defuse' and r.defuse_confirmed and r.lease.keys=={'e'}
