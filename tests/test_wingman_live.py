"""Contract tests with synthetic own-player telemetry and isolated input backends."""
import copy
import json
import time
from types import SimpleNamespace as NS
from dataclasses import replace
import pytest
from modules.wingman.telemetry import GameState, Receiver
from modules.wingman.engine import Phase, Decision, RoundEngine
from modules.wingman.visual import VisualEvidence


def payload(**changes):
    p = {'provider':{'appid':730,'timestamp':time.time(),'steamid':'76561198000000001'},
         'map':{'mode':'scrimcomp2v2','name':'de_inferno','round':0,'phase':'live'},
         'round':{'phase':'live'},
         'player':{'steamid':'76561198000000001','activity':'playing','team':'T',
                   'state':{'health':100,'money':800,'armor':0},
                   'weapons':{'weapon_0':{'name':'weapon_c4','state':'active'}}}}
    for section, values in changes.items():p[section].update(values)
    return p


def test_own_state_age_and_bomb():
    clock=[10.];s=GameState(clock=lambda:clock[0]);assert s.accept(payload())
    o=s.snapshot().observation
    assert o.own_player and o.alive and o.money==800 and o.bomb=='carried_self'
    clock[0]=10.61;assert s.snapshot() is None


@pytest.mark.parametrize('changes',[
    {'player':{'steamid':'76561198000000002'}},
    {'player':{'activity':'menu'}}, {'map':{'mode':'deathmatch'}},
    {'map':{'name':'de_dust2'}}, {'player':{'state':{'health':0}}},
    {'player':{'state':{'health':True}}}])
def test_foreign_dead_or_wrong_game_never_authorizes_combat(changes):
    s=GameState();assert s.accept(payload(**changes))
    assert not RoundEngine().update(s.snapshot().observation,now=time.monotonic()).combat


def test_spectated_inventory_money_never_leaks_into_own_state():
    s=GameState();assert s.accept(payload(player={'steamid':'76561198000000002'}))
    v=s.snapshot();assert not v.weapons and v.observation.money is None and v.observation.team==''


@pytest.mark.parametrize('mutate',[
    lambda p:p['provider'].update(timestamp=time.time()-20),
    lambda p:p['provider'].update(appid=123),
    lambda p:p['provider'].update(timestamp=float('nan')),
    lambda p:p.update(player=None),lambda p:p.update(provider=None),
    lambda p:p['player'].update(weapons=None),lambda p:p['map'].update(round=True)])
def test_malformed_state_invalidates_prior_state(mutate):
    s=GameState();assert s.accept(payload());p=payload();mutate(p)
    assert not s.accept(p) and s.snapshot() is None


def test_round_regression_and_account_change_rejected():
    s=GameState();assert s.accept(payload(map={'round':2}))
    assert not s.accept(payload(map={'round':1}))
    assert not s.accept(payload(provider={'steamid':'76561198000000002'}))


def test_terminal_then_new_match_epoch():
    s=GameState();assert s.accept(payload(map={'round':9,'phase':'gameover'}))
    previous=s.snapshot().observation.match_id
    assert s.accept(payload(map={'round':0,'phase':'warmup'}))
    assert s.snapshot().observation.match_id!=previous


def test_lingering_round_banner_does_not_close_new_freeze_round():
    s=GameState();s.accept(payload(round={'phase':'freezetime'}));o=s.snapshot().observation
    e=RoundEngine();now=time.monotonic()
    assert not e.update_with_visual(o,VisualEvidence('round_over',1,'recognized_hud_text',now),now=now).combat
    o=replace(o,sequence=2,phase=Phase.LIVE)
    assert e.update_with_visual(o,VisualEvidence('unknown',0,'no_verified_overlay',now),now=now).combat


def test_receiver_auth_and_lifecycle():
    from http.client import HTTPConnection
    receiver=Receiver(token='a'*48,port=0)
    try:
        port=receiver.server.server_address[1]
        def send(token):
            p=payload();p['auth']={'token':token}
            c=HTTPConnection('127.0.0.1',port,timeout=2)
            c.request('POST','/wingman',body=json.dumps(p));res=c.getresponse();res.read();c.close();return res.status
        assert send('wrong')==403 and receiver.state.snapshot() is None
        assert send('a'*48)==200 and receiver.state.snapshot() is not None
    finally:receiver.close()
    assert not receiver.thread.is_alive()


@pytest.fixture
def runtime(csgobot_path,monkeypatch,tmp_path):
    import sys
    from nav import wingman_runtime as module
    from nav.input_lease import KeyLease
    state=GameState();events=[];focus=[True]
    monkeypatch.setitem(sys.modules,'pydirectinput',NS(keyDown=lambda k:events.append(('down',k)),keyUp=lambda k:events.append(('up',k)),press=lambda k:events.append(('press',k))))
    monkeypatch.setattr(module,'Receiver',lambda **kw:NS(state=state,close=lambda:None))
    monkeypatch.setattr(module,'KeyLease',lambda down,up,**kw:KeyLease(down,up,background=False,allowed=kw['allowed']))
    monkeypatch.setattr(module,'HudReader',lambda root:NS(read=lambda im,now:VisualEvidence('unknown',0,'no_verified_overlay',now)))
    path=tmp_path/'receiver.json';path.write_text(json.dumps({'token':'a'*48}));monkeypatch.setenv('CSGOBOT_WINGMAN_GSI',str(path))
    config=NS(**{name:NS() for name in ('patrol','autobuy','team_detect','map_detect','look','aim','nav')})
    config.capture_region=NS(width=1280,height=720)
    r=module.WingmanRuntime(config,NS(press=lambda k:events.append(('mouse_down',k)),release=lambda k:events.append(('mouse_up',k))),lambda:focus[0])
    r.radar_configured=True
    yield r,state,events,focus,config
    r.close()


def observe(r,s,p):
    import numpy as np
    assert s.accept(p)
    return r.observe(np.zeros((720,1280,3),dtype=np.uint8),None,now=time.monotonic())


def test_runtime_disables_dm_and_buy_never_bypasses_hud(runtime):
    r,s,events,focus,c=runtime
    assert not c.autobuy.enabled and not c.patrol.enabled and c.aim.target_mode=='team'
    now=time.monotonic();r.last_hud=VisualEvidence('unknown',0,'uncalibrated_resolution',now)
    assert observe(r,s,payload(round={'phase':'freezetime'})).state=='waiting'
    r.last_hud=VisualEvidence('round_over',1,'recognized_hud_text',time.monotonic())
    assert observe(r,s,payload(round={'phase':'freezetime'})).state=='round_over'


def test_runtime_plant_holds_without_repeating_equipment_then_death_releases(runtime):
    r,s,events,focus,c=runtime;observe(r,s,payload())
    r.interaction='plant';r.interaction_at=time.monotonic()
    r.idle_tick(None,now=time.monotonic());r.idle_tick(None,now=time.monotonic())
    assert events==[('mouse_down','left')]
    observe(r,s,payload(player={'state':{'health':0}}))
    assert events[-1]==('mouse_up','left') and r.interaction is None


def test_runtime_equips_bomb_once_before_holding(runtime):
    r,s,events,focus,c=runtime
    p=payload(player={'weapons':{'a':{'name':'weapon_c4','state':'holstered'},'b':{'name':'weapon_glock','state':'active'}}})
    observe(r,s,p);r.interaction='plant';r.interaction_at=time.monotonic()
    r.idle_tick(None,now=time.monotonic());r.idle_tick(None,now=time.monotonic())
    assert events==[('press','5')]
    observe(r,s,payload());r.idle_tick(None,now=time.monotonic())
    assert events[-1]==('mouse_down','left')


def test_runtime_defuse_released_on_focus_loss(runtime):
    r,s,events,focus,c=runtime;observe(r,s,payload(player={'team':'CT'},round={'bomb':'planted'}))
    r.interaction='defuse';r.interaction_at=time.monotonic();r.idle_tick(None,now=time.monotonic())
    assert events==[('down','e')]
    focus[0]=False;r.lease.expire();assert events[-1]==('up','e')


def test_runtime_stale_receiver_releases_interaction(runtime):
    r,s,events,focus,c=runtime;observe(r,s,payload());r.interaction='plant';r.interaction_at=time.monotonic();r.idle_tick(None,now=time.monotonic())
    s.latest=None
    import numpy as np
    d=r.observe(np.zeros((720,1280,3),dtype=np.uint8),None,now=time.monotonic())
    assert d.state=='waiting' and not r.lease.keys and events[-1]==('mouse_up','left')


def test_wingman_ground_routes_and_no_dm_fallback(csgobot_path,monkeypatch):
    from nav.wingman_runtime import load_ground
    ground=load_ground('de_inferno');site=ground.norm((820,710))
    for start in ((525,677),(889,653)):
        assert ground.plan(ground.norm(start),site)
    assert not ground.contains(ground.norm((650,250)))
    with pytest.raises(ValueError):load_ground('de_dust2')


def test_setup_is_idempotent_and_preserves_other_configs(monkeypatch,tmp_path):
    from modules.wingman.setup import prepare
    import config.paths as paths
    import modules.launcher.cs2 as launcher
    cfg=tmp_path/'cfg';cfg.mkdir();(cfg/'user.cfg').write_text('keep')
    monkeypatch.setattr(paths,'get_data_dir',lambda:tmp_path/'data')
    monkeypatch.setattr(launcher,'resolve_cs2_exe',lambda config:tmp_path/'cs2.exe')
    monkeypatch.setattr(launcher,'find_csgo_cfg_dir',lambda exe:cfg)
    state,changed=prepare(None);assert changed
    token=json.loads(state.read_text())['token'];assert len(token)==48
    assert prepare(None)==(state,False)
    assert (cfg/'user.cfg').read_text()=='keep'
    assert token in (cfg/'gamestate_integration_farm_panel_wingman.cfg').read_text()


def test_child_mode_isolation_and_no_dm_recovery(monkeypatch):
    from modules.combat import csgobot_ai as ai
    from config.schema import AppConfig
    env={};ctx={'config':AppConfig(),'wingman_gsi_path':'local.json'}
    ai._apply_child_env_from_ctx(ctx,env)
    assert env['CSGOBOT_GAME_MODE']=='wingman' and env['CSGOBOT_NAV_PACK']=='inferno_visual'
    assert ai._make_match_recovery(ctx,100) is None
    ai._apply_child_env_from_ctx({'config':AppConfig()},env)
    assert 'CSGOBOT_GAME_MODE' not in env and 'CSGOBOT_WINGMAN_GSI' not in env


def test_real_controller_receives_wingman_objective(runtime,monkeypatch):
    from nav.farm_runtime import create_navigation,CameraOwnership
    from nav.pack import load_nav_pack
    from nav.paths import resolve_nav_pack_path
    from nav.pose import PoseResult
    r,s,events,focus,c=runtime;monkeypatch.setenv('CSGOBOT_GAME_MODE','wingman')
    ctrl=create_navigation(load_nav_pack(resolve_nav_pack_path('inferno_visual')),
        NS(fov=NS(x360=3600)),lambda k:None,lambda k:None,
        CameraOwnership(lambda *args:None,lambda:True),expanded=True,watchdog=False)
    try:
        observe(r,s,payload());r.set_objective(ctrl,now=time.monotonic())
        assert r.mission is None and not ctrl._free_roam
        point=ctrl.walkable.norm((889,653))
        ctrl.last_pose=PoseResult(*point,0,.95,True,20,'visual',None,time.monotonic())
        deadline=time.monotonic()+5
        while r.mission is None and time.monotonic()<deadline:
            ctrl.last_pose=replace(ctrl.last_pose,observed_at=time.monotonic())
            r.set_objective(ctrl,now=time.monotonic())
            time.sleep(.005)
        assert ctrl._route_goal.id.startswith('wingman-0-')
        for _ in range(3):
            deadline=time.monotonic()+5
            while r.mission is None and time.monotonic()<deadline:
                ctrl.last_pose=replace(ctrl.last_pose,observed_at=time.monotonic())
                r.set_objective(ctrl,now=time.monotonic())
                time.sleep(.005)
            point=ctrl.walkable.norm(r.mission.point)
            ctrl.last_pose=PoseResult(*point,0,.95,True,20,'visual',None,time.monotonic())
            r.set_objective(ctrl,now=time.monotonic())
            if r.interaction:break
        assert r.interaction=='plant'
    finally:ctrl.close()


def test_buy_waits_for_inventory_confirmation_and_never_repeats(runtime,monkeypatch):
    from modules.ui_nav import cs2_console,window
    r,s,events,focus,c=runtime;commands=[]
    monkeypatch.setattr(window,'find_cs2_hwnd',lambda:123)
    monkeypatch.setattr(cs2_console,'run_cs2_console_commands',lambda hwnd,cmd:commands.append(cmd))
    observe(r,s,payload(round={'phase':'freezetime'},player={'state':{'health':100,'money':800}}))
    r.idle_tick(None,now=time.monotonic());r.idle_tick(None,now=time.monotonic())
    assert commands==['buy vest']
    observe(r,s,payload(round={'phase':'live'}));r.idle_tick(None,now=time.monotonic())
    assert commands==['buy vest']


def test_child_imports_console_with_vendor_config_loaded():
    import subprocess,sys
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    code="import sys; sys.path.insert(0,'vendor/csgobot'); import config; from nav.wingman_runtime import load_ground; from modules.ui_nav.cs2_console import run_cs2_console_commands; assert load_ground('de_inferno') is not None"
    result=subprocess.run([sys.executable,'-c',code],cwd=root,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
