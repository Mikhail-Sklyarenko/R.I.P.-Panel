"""Recorded-state sequences: no actions until UI/spawn is stable."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from modules.dm_runner import team_join as m
from modules.ui_nav.coords import load_nav_coords
from modules.ui_nav.errors import UiNavTimeoutError


def run_sequence(monkeypatch, states, *, callback=None):
    clock=[0.];frames=iter(states);current=['loading'];events=[]
    def capture():
        current[0]=next(frames,'loading');return current[0]
    monkeypatch.setattr(m.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(m.time,'sleep',lambda dt:clock.__setitem__(0,clock[0]+dt))
    monkeypatch.setattr(m,'past_team_select_screen',lambda img,c:img=='spawn')
    monkeypatch.setattr(m,'detect_probe_key',lambda img,*a,**k:img=='team')
    driver=SimpleNamespace(capture=capture,click=lambda p:events.append((clock[0],current[0])))
    result=m.wait_team_select_done(driver,load_nav_coords('1280x720'),timeout_sec=30,
        on_team_random_clicked=callback)
    return result,events


def test_slow_load_clicks_only_stable_team_and_buy_after_spawn(monkeypatch):
    buys=[]
    count,events=run_sequence(monkeypatch,['loading']*70+['team']*3+['loading']*8+['spawn']*3,callback=lambda:buys.append(True))
    assert count==1 and events[0][0]>=18 and events[0][1]=='team'
    assert buys==[True]


def test_transient_team_match_never_clicks(monkeypatch):
    count,events=run_sequence(monkeypatch,['team','loading','team','loading']+['spawn']*3)
    assert count==0 and not events


def test_loading_timeout_never_clicks_or_buys(monkeypatch):
    buy=Mock()
    with pytest.raises(UiNavTimeoutError):run_sequence(monkeypatch,['loading']*150,callback=buy)
    buy.assert_not_called()


def test_spawn_confirmation_resets_when_loading_returns(monkeypatch):
    count,events=run_sequence(monkeypatch,['spawn']*2+['loading']*10+['team']*3+['spawn']*3)
    assert count==1
