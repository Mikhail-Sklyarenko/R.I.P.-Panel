"""Loopback-only game-state receiver; never reads another process's memory."""
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread, Lock
import hmac
import json
import math
import time
import logging
from .engine import Observation, Phase


@dataclass(frozen=True)
class Snapshot:
    observation: Observation
    weapons: tuple[str, ...]
    active_weapon: str
    armor: int
    helmet: bool
    defusekit: bool
    provider_time: float
    grenade_count: int = 0


class GameState:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = Lock()
        self.latest = None
        self.sequence = 0
        self.epoch = 1
        self.player_id = None
        self.last_round = None
        self.current_map = None
        self.last_provider_time = -1
        self.ended = False
        self.last_status = None

    def accept(self, payload):
        with self.lock:
            return self._accept(payload)

    def _accept(self, payload):
        try:
            provider = payload["provider"]
            player = payload.get("player", {})
            game_map = payload.get("map", {})
            game_round = payload.get("round", {})
            if provider.get("appid") != 730:
                raise ValueError("wrong_game")
            timestamp = provider["timestamp"]
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int,float)) or not math.isfinite(timestamp):
                raise ValueError("invalid_provider_time")
            if timestamp < self.last_provider_time or abs(time.time()-timestamp) > 10:
                raise ValueError("stale_provider_time")
            identity = str(provider.get("steamid", ""))
            if not identity.isdigit() or len(identity) != 17:
                raise ValueError("missing_player_identity")
            if self.player_id is not None and self.player_id != identity:
                raise ValueError("account_changed")
            self.player_id = identity
            number = game_map.get("round", -1)
            if type(number) is not int:
                raise ValueError("invalid_round")
            mode_ok = game_map.get("mode") == "scrimcomp2v2"
            from .maps import map_ready
            map_id = game_map.get("name")
            map_ok = map_ready(map_id)
            map_phase = game_map.get("phase")
            phase = ({"freezetime":Phase.FREEZE,"live":Phase.LIVE,"over":Phase.OVER}.get(game_round.get("phase"),Phase.UNKNOWN))
            if map_phase == "gameover": phase = Phase.FINISHED
            elif map_phase == "warmup": phase = Phase.WARMUP
            # GSI increments map.round at OVER, before the next FREEZE.
            # Normalize OVER to the round that actually just ended.
            if phase == Phase.OVER and number >= 0:
                number = max(0, number - 1)
            map_changed = self.current_map is not None and map_id!=self.current_map
            if map_changed:
                self.epoch += 1
                self.ended = False
            if not map_changed and self.last_round is not None and number >= 0 and number < self.last_round:
                if self.ended or phase == Phase.WARMUP:
                    self.epoch += 1
                    self.ended = False
                else:
                    raise ValueError("round_regression")
            status = (game_map.get("mode"), game_map.get("name"), phase.value)
            if status != self.last_status:
                logging.getLogger("CS2Bot.wingman").info("gsi mode=%r map=%r phase=%s supported=%s",*status,mode_ok and map_ok)
                self.last_status = status
            own = player.get("steamid") == identity and player.get("activity") == "playing"
            state = player.get("state", {}) if own else {}
            health = state.get("health")
            alive = type(health) is int and health > 0
            money = state.get("money")
            if type(money) is not int or not 0 <= money <= 16000:money = None
            team = player.get("team", "") if own else ""
            weapons = player.get("weapons", {}) if own else {}
            names = tuple(v["name"] for v in weapons.values() if isinstance(v,dict) and isinstance(v.get("name"),str))
            from .economy import GRENADE_NAMES
            grenade_count = 0
            for weapon in weapons.values():
                if not isinstance(weapon,dict) or weapon.get("name") not in GRENADE_NAMES:
                    continue
                # GSI represents two flashes as one weapon entry with reserve=2.
                reserve = weapon.get("ammo_reserve",1)
                limit = 2 if weapon.get("name") == "weapon_flashbang" else 1
                grenade_count += min(limit,max(1,reserve)) if type(reserve) is int else 1
            active = next((v.get("name", "") for v in weapons.values() if isinstance(v,dict) and v.get("state") == "active"), "")
            bomb = game_round.get("bomb", "unknown")
            if bomb not in ("planted", "defused", "exploded"):
                bomb = "carried_self" if "weapon_c4" in names else "not_carried_self"
            self.sequence += 1
            now = self.clock()
            observation = Observation(self.sequence, now, f"gsi-{self.epoch}", number,
                map_id if mode_ok and map_ok else "unsupported",
                phase, own, alive, team, money,
                buy_allowed=own and alive and phase == Phase.FREEZE, bomb=bomb,
                connected=mode_ok and map_ok)
            armor = state.get("armor", 0)
            armor = armor if type(armor) is int and 0 <= armor <= 100 else 0
            self.latest = Snapshot(observation,names,active,armor,state.get("helmet") is True,
                                   state.get("defusekit") is True,timestamp,grenade_count)
            self.current_map = map_id
            self.last_provider_time = timestamp
            if number >= 0:self.last_round = number
            if phase == Phase.FINISHED:self.ended = True
            return True
        except (KeyError,TypeError,ValueError,AttributeError):
            self.latest = None
            return False

    def snapshot(self):
        with self.lock:
            value = self.latest
            if value is None or not 0 <= self.clock()-value.observation.observed_at <= .6:
                return None
            return value


class Receiver:
    def __init__(self, *, token, port=4019, state=None):
        if not isinstance(token,str) or len(token) < 24:
            raise ValueError("GSI token must contain at least 24 characters")
        self.state = state or GameState()
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                self.connection.settimeout(1.)
                status = 400
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if self.path != "/wingman" or not 0 < length <= 65536:
                        raise ValueError("bad_request")
                    payload = json.loads(self.rfile.read(length))
                    candidate = payload.get("auth",{}).get("token", "")
                    if not isinstance(candidate,str) or not hmac.compare_digest(candidate,token):
                        status = 403
                    else:
                        status = 200 if owner.state.accept(payload) else 422
                except (ValueError,TypeError,AttributeError,TimeoutError,OSError): pass
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.end_headers()
        self.server = HTTPServer(("127.0.0.1",port),Handler)
        self.thread = Thread(target=self.server.serve_forever,kwargs={"poll_interval":.1},daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
