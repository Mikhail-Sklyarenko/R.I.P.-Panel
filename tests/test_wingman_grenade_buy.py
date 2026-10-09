import time
import pytest
from modules.wingman.economy import plan_grenades
from modules.wingman.telemetry import GameState
from tests.test_wingman_live import runtime,observe,payload


@pytest.mark.parametrize('money,names',[(0,[]),(199,[]),(200,['weapon_flashbang']),
    (300,['weapon_smokegrenade']),(600,['weapon_smokegrenade','weapon_hegrenade']),
    (800,['weapon_smokegrenade','weapon_hegrenade','weapon_flashbang']),
    (1200,['weapon_smokegrenade','weapon_hegrenade','weapon_flashbang','weapon_molotov'])])
def test_remaining_budget(money,names):
    result=plan_grenades(money=money,team='T',weapons=())
    assert [i.name for i in result]==names
    assert sum(i.price for i in result)<=money


def test_team_and_retained_inventory_capacity():
    result=plan_grenades(money=16000,team='CT',weapons=())
    assert result[-1].name=='weapon_incgrenade' and len(result)==4
    result=plan_grenades(money=16000,team='CT',
        weapons=('weapon_flashbang','weapon_smokegrenade','weapon_decoy'),grenade_count=4)
    assert not result
    result=plan_grenades(money=16000,team='CT',weapons=('weapon_molotov','weapon_flashbang'))
    assert [i.name for i in result]==['weapon_smokegrenade','weapon_hegrenade']
    assert not plan_grenades(money=None,team='T',weapons=())


def test_gsi_counts_two_flashes_and_does_not_read_spectated_inventory():
    weapons={'weapon_0':{'name':'weapon_flashbang','ammo_reserve':2},
             'weapon_1':{'name':'weapon_smokegrenade','ammo_reserve':1}}
    s=GameState();assert s.accept(payload(player={'weapons':weapons}))
    assert s.snapshot().grenade_count==3
    assert s.accept(payload(player={'weapons':weapons,'steamid':'76561198000000002'}))
    assert s.snapshot().grenade_count==0


def test_runtime_core_first_then_confirmed_grenades(runtime,monkeypatch):
    from modules.ui_nav import cs2_console,window
    r,s,events,focus,c=runtime;commands=[]
    monkeypatch.setattr(window,'find_cs2_hwnd',lambda:123)
    monkeypatch.setattr(cs2_console,'run_cs2_console_commands',lambda hwnd,cmd:commands.append(cmd))
    weapons={};money=4550;armor=0
    def feed():
        observe(r,s,payload(round={'phase':'freezetime'},player={
            'state':{'health':100,'money':money,'armor':armor},'weapons':dict(weapons)}))
    feed();now=time.monotonic()
    for n,(alias,price) in enumerate([('vest',650),('ak47',2700),('smokegrenade',300),
                                     ('hegrenade',300),('flashbang',200),('molotov',400)]):
        r._buy(now+n*.2)
        assert commands[-1]=='buy '+alias and len(commands)==n+1
        # No new telemetry: never advance or send a second purchase.
        r._buy(now+n*.2+.01);assert len(commands)==n+1
        money-=price
        if alias=='vest':armor=100
        else:weapons['weapon_'+str(n)]={'name':'weapon_'+alias,'state':'holstered'}
        feed()
    r._buy(now+1.3)
    assert money==0 and len(commands)==6 and not r.purchase.failed
    # Surviving round: do not rebuy retained grenades.
    observe(r,s,payload(map={'round':1},round={'phase':'freezetime'},player={
        'state':{'health':100,'money':5000,'armor':100},'weapons':weapons}))
    r._buy(now+1.4)
    assert len(commands)==6


def test_failed_core_purchase_never_spends_budget_on_grenades(runtime,monkeypatch):
    from modules.ui_nav import cs2_console,window
    r,s,events,focus,c=runtime;commands=[]
    monkeypatch.setattr(window,'find_cs2_hwnd',lambda:123)
    monkeypatch.setattr(cs2_console,'run_cs2_console_commands',lambda hwnd,cmd:commands.append(cmd))
    observe(r,s,payload(round={'phase':'freezetime'},player={'state':{'health':100,'money':8000}}))
    now=time.monotonic();r._buy(now);r._buy(now+2.1);r._buy(now+3.)
    assert commands==['buy vest'] and r.purchase.failed


def test_ct_defuse_kit_precedes_grenades(runtime,monkeypatch):
    from modules.ui_nav import cs2_console,window
    r,s,events,focus,c=runtime
    monkeypatch.setattr(window,'find_cs2_hwnd',lambda:123)
    monkeypatch.setattr(cs2_console,'run_cs2_console_commands',lambda *args:None)
    observe(r,s,payload(round={'phase':'freezetime'},player={'team':'CT',
        'state':{'health':100,'money':4750},'weapons':{}}))
    r._buy(time.monotonic())
    assert [r.purchase.pending.name]+[i.name for i in r.purchase.items]==[
        'vest','weapon_m4a1_silencer','defuser','weapon_smokegrenade','weapon_hegrenade','weapon_flashbang']
