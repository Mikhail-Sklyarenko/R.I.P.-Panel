"""Match lifecycle supervision, independent of combat/level-up detection."""
from collections import deque
import time
from modules.ui_nav.detectors import ScreenState, detect_state, detect_probe_key
from modules.dm_runner.team_join import past_team_select_screen


class MatchRecovery:
    def __init__(self, nav):
        self.nav=nav
        self.next_poll=0.
        self.pending=None
        self.streak=0
        self.last_hud=None
        self.restarts=deque()
        self.capture_failures=0

    def observe(self, now):
        if now<self.next_poll:return None
        self.next_poll=now+1.
        if self.last_hud is None:self.last_hud=now
        try:
            img=self.nav.driver.capture()
            self.capture_failures=0
        except Exception:
            self.capture_failures+=1
            if self.capture_failures>=5:raise
            return None
        if past_team_select_screen(img,self.nav.coords):
            self.last_hud=now
            self.pending=None
            self.streak=0
            return None
        state=('team' if detect_probe_key(img,self.nav.coords,'team_select') else
               'menu' if detect_state(img,ScreenState.MAIN_MENU,self.nav.coords) else None)
        self.streak=self.streak+1 if state and state==self.pending else 1
        self.pending=state
        if state and self.streak>=3:return state
        if now-self.last_hud>=max(120.,self.nav.config.map_load_delay_sec*2):return 'load_timeout'
        return None

    def recover(self, state):
        """Caller must stop combat before handing input ownership to this method."""
        now=time.monotonic()
        while self.restarts and now-self.restarts[0]>600:self.restarts.popleft()
        if len(self.restarts)>=3:
            raise RuntimeError('Repeated match recovery failed: three recoveries within ten minutes')
        self.restarts.append(now)
        n=self.nav
        n._search_requested=state!='menu'
        n._team_done_mono=None
        n._startup_buy_done=False
        n._combat_preload_started=False
        n._abort_if_stopped()
        if state=='team':
            try:
                n._ensure_team_joined()
                n._finish_spawn_phase(soft_peek=False)
            except Exception:
                n._abort_if_stopped()
                n._reset_search()
                n.navigate_to_dm_with_retries()
        else:
            n._reset_search()
            n.navigate_to_dm_with_retries()
        self.last_hud=time.monotonic()
        self.pending=None
        self.streak=0
