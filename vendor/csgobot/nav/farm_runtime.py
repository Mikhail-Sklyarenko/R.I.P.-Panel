"""Configuration and exclusive camera ownership for the integrated farm runtime."""
import os
import threading
import time
from collections import deque
from nav.paths import resolve_nav_root
from nav.walkable import WalkableMap


def expanded_mode():
    return os.environ.get('CSGOBOT_GAME_MODE')=='wingman' or os.environ.get('CSGOBOT_NAV_MODE','').strip().lower()=='expanded_roam'


def load_ground(map_id):
    if map_id=='de_dust2':
        ground=WalkableMap.load(map_id,resolve_nav_root()/'experimental/de_dust2')
        if ground is None:
            raise ValueError('Expanded Dust2 profile missing')
        return ground
    return WalkableMap.load(map_id)


class CameraOwnership:
    """Serialize ownership changes with emitted deltas from both mouse threads."""
    def __init__(self, move, allowed, *, clock=time.monotonic, objective_allowed=None):
        self._move,self._allowed=move,allowed
        self._objective_allowed=objective_allowed
        self._owner=None
        self._clock=clock
        self._sent=deque(maxlen=512)
        self._lock=threading.RLock()

    def allowed(self):
        try:return bool(self._allowed())
        except Exception:return False

    def select(self, owner):
        if owner not in (None,'nav','combat','objective'):raise ValueError('Unknown camera owner')
        with self._lock:self._owner=owner

    def _allowed_for(self,owner):
        if owner != "objective":return self.allowed()
        try:return bool(self._objective_allowed and self._objective_allowed())
        except Exception:return False

    def permitted(self, owner):
        with self._lock:return self._owner==owner and self._allowed_for(owner)

    def emit(self, owner, dx, dy):
        with self._lock:
            if self._owner == owner and self._allowed_for(owner):
                accepted=self._move(dx, dy)
                if accepted is False:return False
                self._sent.append((self._clock(),dx,dy))
                return True
            return False

    def commands_since(self, observed_at, until=None):
        """Accepted deltas from both owners; a handoff never erases history."""
        with self._lock:
            return tuple((t,dx,dy) for t,dx,dy in self._sent
                         if t>=observed_at and (until is None or t<until))


def create_navigation(pack, fov, key_down, key_up, ownership, *, expanded=False,
                      logger=None, watchdog=True):
    from nav.visual_controller import VisualNavController
    wingman = os.environ.get('CSGOBOT_GAME_MODE') == 'wingman'
    if wingman:
        from nav.wingman_runtime import load_ground as wingman_ground
    return VisualNavController(pack,fov,key_down,key_up,
        lambda dx,dy:ownership.emit('nav',dx,dy),
        free_roam=expanded and not wingman,adaptive_goal=wingman,camera_rate=360. if expanded else None,
        walkable_loader=wingman_ground if wingman else load_ground if expanded else None,
        logger=logger,watchdog=watchdog,
        input_allowed=lambda:ownership.permitted('nav'))
