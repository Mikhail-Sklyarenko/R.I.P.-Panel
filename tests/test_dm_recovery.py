from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from modules.dm_runner import recovery as m


def monitor(monkeypatch):
    nav=SimpleNamespace(config=SimpleNamespace(map_load_delay_sec=65),coords=None,driver=SimpleNamespace(capture=lambda:'loading'))
    monkeypatch.setattr(m,'past_team_select_screen',lambda img,c:img=='spawn')
    monkeypatch.setattr(m,'detect_probe_key',lambda img,*a:img=='team')
    monkeypatch.setattr(m,'detect_state',lambda img,*a:img=='menu')
    return nav,m.MatchRecovery(nav)


def test_normal_death_and_load_do_not_restart(monkeypatch):
    nav,r=monitor(monkeypatch)
    assert all(r.observe(t) is None for t in range(90))
    nav.driver.capture=lambda:'spawn'
    assert r.observe(90) is None
    nav.driver.capture=lambda:'loading'
    assert r.observe(150) is None
    assert r.observe(220)=='load_timeout'


@pytest.mark.parametrize('state',['team','menu'])
def test_only_stable_transition_recovers(monkeypatch,state):
    nav,r=monitor(monkeypatch);nav.driver.capture=lambda:state
    assert r.observe(1) is None and r.observe(2) is None
    assert r.observe(3)==state


def test_capture_glitch_does_not_end_session(monkeypatch):
    nav,r=monitor(monkeypatch);nav.driver.capture=Mock(side_effect=OSError('capture'))
    for t in range(4):assert r.observe(t) is None
    with pytest.raises(OSError):r.observe(4)


def test_team_recovery_joins_without_search_and_resets_buy(monkeypatch):
    nav,r=monitor(monkeypatch)
    for name in ('_abort_if_stopped','_ensure_team_joined','_finish_spawn_phase','_reset_search','navigate_to_dm_with_retries'):setattr(nav,name,Mock())
    nav._startup_buy_done=True
    r.recover('team')
    assert not nav._startup_buy_done
    nav._ensure_team_joined.assert_called_once()
    nav._finish_spawn_phase.assert_called_once_with(soft_peek=False)
    nav._reset_search.assert_not_called()


def test_failed_team_load_restarts_search(monkeypatch):
    nav,r=monitor(monkeypatch)
    for name in ('_abort_if_stopped','_ensure_team_joined','_finish_spawn_phase','_reset_search','navigate_to_dm_with_retries'):setattr(nav,name,Mock())
    nav._ensure_team_joined.side_effect=RuntimeError('load failed')
    r.recover('team')
    nav._reset_search.assert_called_once()
    nav.navigate_to_dm_with_retries.assert_called_once()


def test_stop_during_recovery_prevents_input(monkeypatch):
    nav,r=monitor(monkeypatch)
    nav._abort_if_stopped=Mock(side_effect=RuntimeError('stopped'));nav._reset_search=Mock()
    with pytest.raises(RuntimeError):r.recover('menu')
    nav._reset_search.assert_not_called()


def test_buy_and_combat_start_follow_spawn_confirmation(monkeypatch):
    from modules.dm_runner.navigate import DmNavigator
    n=DmNavigator.__new__(DmNavigator);events=[]
    n._startup_buy_done=False
    n._ensure_team_joined=lambda:events.append('spawn')
    n._abort_if_stopped=lambda:None
    n._console_buy_once=lambda **kw:events.append('buy')
    n._start_combat_preload=lambda:events.append('combat')
    n._e=lambda *a:None
    n._in_dm_detail=lambda **kw:'ready'
    n._finish_spawn_phase(soft_peek=False)
    assert events==['spawn','buy','combat']
    n._ensure_team_joined=Mock(side_effect=RuntimeError('loading'))
    events.clear()
    with pytest.raises(RuntimeError):n._finish_spawn_phase(soft_peek=False)
    assert not events


def test_unexpected_worker_error_stops_watch_and_child(monkeypatch):
    from modules.combat import factory
    from config.schema import AppConfig,BotMode
    monkeypatch.setattr(factory.csgobot_ai,'start_ai',Mock(side_effect=RuntimeError('lost window')))
    stop=Mock();monkeypatch.setattr(factory.csgobot_ai,'stop_ai',stop)
    ctx={'config':AppConfig(bot_mode=BotMode.AI),'emit':Mock()}
    factory._run_bot_loop(ctx)
    assert ctx['stop_requested'] and stop.call_count==1


def test_child_is_stopped_before_menu_recovery_and_restarted_after(monkeypatch):
    from modules.combat import csgobot_ai as c
    from config.schema import AppConfig
    events=[];ctx={'config':AppConfig(),'session_id':'lifecycle'}
    proc=SimpleNamespace(poll=lambda:None)
    monkeypatch.setattr(c.sys,'platform','win32')
    monkeypatch.setattr(c,'_PROCESS',proc);monkeypatch.setattr(c,'_PROCESS_PRELOADED',True)
    monkeypatch.setattr(c,'is_installed',lambda:True)
    monkeypatch.setattr(c,'python_executable',lambda:True)
    monkeypatch.setattr(c,'_nav_env_summary',lambda ctx:None)
    monkeypatch.setattr(c,'_ingest_nav_metrics_from_stderr',lambda *a:None)
    def stop():events.append('stop');c._PROCESS=None
    def spawn(ctx):events.append('spawn');c._PROCESS=proc;return True
    def sleep(dt):ctx['stop_requested']=True
    supervisor=SimpleNamespace(observe=lambda now:'team',recover=lambda action:events.append('recover'))
    monkeypatch.setattr(c,'_make_match_recovery',lambda *a:supervisor)
    monkeypatch.setattr(c,'stop_ai',stop);monkeypatch.setattr(c,'_spawn_subprocess',spawn)
    monkeypatch.setattr(c.time,'sleep',sleep)
    assert c.start_ai(ctx)
    assert events==['stop','recover','spawn','stop']


def test_repeated_recovery_is_bounded(monkeypatch):
    nav,r=monitor(monkeypatch)
    for name in ('_abort_if_stopped','_ensure_team_joined','_finish_spawn_phase','_reset_search','navigate_to_dm_with_retries'):setattr(nav,name,Mock())
    monkeypatch.setattr(m.time,'monotonic',lambda:100.)
    for _ in range(3):r.recover('menu')
    with pytest.raises(RuntimeError,match='three recoveries'):r.recover('menu')
    assert nav.navigate_to_dm_with_retries.call_count==3


def test_watch_exception_always_stops_combat(monkeypatch):
    from modules.combat import phase
    from config.schema import AppConfig
    monkeypatch.setattr(phase,'_run_bot_loop',lambda ctx:None)
    monkeypatch.setattr(phase,'watch',Mock(side_effect=RuntimeError('capture failed')))
    stop=Mock();monkeypatch.setattr(phase,'stop_combat',stop)
    ctx={'config':AppConfig()}
    with pytest.raises(RuntimeError):phase.run_combat_phase(ctx)
    assert ctx['stop_requested'] and stop.call_count==1


def test_release_only_sends_keyups_without_stealing_focus(monkeypatch):
    import sys
    from modules.ui_nav import actions,window
    api=SimpleNamespace(keybd_event=Mock(),MapVirtualKey=lambda vk,mode:vk,mouse_event=Mock())
    monkeypatch.setitem(sys.modules,'win32api',api)
    monkeypatch.setitem(sys.modules,'win32con',SimpleNamespace(KEYEVENTF_KEYUP=2,MOUSEEVENTF_LEFTUP=4))
    monkeypatch.setitem(sys.modules,'win32gui',SimpleNamespace(GetForegroundWindow=lambda:99))
    monkeypatch.setattr(window,'find_cs2_hwnd',lambda:99)
    monkeypatch.setattr(sys,'platform','win32')
    actions.release_combat_inputs()
    assert api.keybd_event.call_count==8
    assert all(call.args[2]==2 for call in api.keybd_event.call_args_list)
    api.mouse_event.assert_called_once_with(4,0,0,0,0)
    monkeypatch.setattr(window,'find_cs2_hwnd',lambda:100)
    actions.release_combat_inputs()
    assert api.keybd_event.call_count==8


def test_menu_wait_stop_is_immediate_before_capture():
    from modules.ui_nav.detectors import wait_for_state,ScreenState
    from modules.ui_nav.errors import UiNavTimeoutError
    driver=Mock()
    with pytest.raises(UiNavTimeoutError,match='stopped'):
        wait_for_state(driver,ScreenState.MAIN_MENU,None,Mock(),timeout_sec=60,should_stop=lambda:True)
    driver.capture.assert_not_called()
