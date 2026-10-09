"""Agent-side GSI feed (loopback :4020), separate from the worker's :4019 feed.

Gives the agent evidence in menus and matches alike: who is signed in, whether a
map is loaded, its mode/name/phase and our team. The token stays on this PC.
"""
from __future__ import annotations

import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from core.wingman_fleet.models import GsiView

FLEET_GSI_PORT = 4020
CFG_NAME = "gamestate_integration_farm_panel_fleet.cfg"


def _settings_path() -> Path:
    from config.paths import get_data_dir
    return get_data_dir() / "fleet_agent" / "gsi.json"


def load_token(path: Path | None = None) -> str:
    path = path or _settings_path()
    if path.is_file():
        token = json.loads(path.read_text(encoding="utf-8")).get("token", "")
        if isinstance(token, str) and len(token) == 48:
            return token
    token = secrets.token_hex(24)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"token": token, "port": FLEET_GSI_PORT}), encoding="utf-8")
    return token


def config_text(token: str, port: int = FLEET_GSI_PORT) -> str:
    return ('"FarmPanel Fleet"\n{\n'
            f' "uri" "http://127.0.0.1:{port}/fleet"\n'
            ' "timeout" "1.0"\n "buffer" "0.1"\n "throttle" "0.25"\n "heartbeat" "1.0"\n'
            ' "auth" { "token" "' + token + '" }\n'
            ' "data" { "provider" "1" "map" "1" "round" "1" "player_id" "1" "player_state" "1"'
            ' "allplayers_id" "1" "allplayers_state" "1" }\n}\n')


def install(cfg_dir: Path, token: str) -> tuple[Path, bool]:
    """Write the cfg; `changed` means CS2 must be restarted once to load it."""
    path = cfg_dir / CFG_NAME
    text = config_text(token)
    changed = not path.is_file() or path.read_text(encoding="utf-8") != text
    if changed:
        path.write_text(text, encoding="utf-8")
    return path, changed


@dataclass
class _Latest:
    received_at: float = 0.0
    steam_id64: str = ""
    activity: str = ""
    mode: str = ""
    map_id: str = ""
    map_phase: str = ""
    round_phase: str = ""
    team: str = ""
    round_number: int = -1
    alive: bool = False
    player_names: tuple[str, ...] = ()
    server_token: str = ""


class FleetGsi:
    def __init__(self, token: str, *, port: int = FLEET_GSI_PORT, clock=time.monotonic):
        if len(token) < 24:
            raise ValueError("GSI token too short")
        self.token, self.clock = token, clock
        self._lock = threading.Lock()
        self._latest = _Latest()
        self.server: HTTPServer | None = None
        self.port = port

    def accept(self, payload: dict) -> bool:
        provider = payload.get("provider") or {}
        if provider.get("appid") != 730:
            return False
        sid = str(provider.get("steamid", ""))
        if not (sid.isdigit() and len(sid) == 17):
            return False
        game_map = payload.get("map") or {}
        player = payload.get("player") or {}
        own = str(player.get("steamid", "")) == sid
        state = player.get("state") or {}
        health = state.get("health")
        names = []
        allplayers = payload.get("allplayers") or {}
        if isinstance(allplayers, dict):
            for entry in allplayers.values():
                if isinstance(entry, dict) and entry.get("name"):
                    names.append(str(entry["name"]))
        if own and player.get("name") and str(player["name"]) not in names:
            names.append(str(player["name"]))
        server = payload.get("provider") or {}
        token = str(server.get("steamid", ""))
        ip = str((payload.get("map") or {}).get("ip", "") or server.get("ip", ""))
        if ip:
            token = ip
        with self._lock:
            self._latest = _Latest(
                self.clock(), sid, str(player.get("activity", "")) if own else "",
                str(game_map.get("mode", "")), str(game_map.get("name", "")), str(game_map.get("phase", "")),
                str((payload.get("round") or {}).get("phase", "")), str(player.get("team", "")) if own else "",
                int(game_map["round"]) if isinstance(game_map.get("round"), int) else -1,
                own and isinstance(health, int) and health > 0,
                tuple(names), token)
        return True

    def view(self) -> GsiView:
        with self._lock:
            l = self._latest
        if not l.received_at:
            return GsiView()
        return GsiView(self.clock() - l.received_at, l.steam_id64, l.mode, l.map_id, l.map_phase,
                       l.round_phase, l.team, l.round_number, l.alive)

    def roster_names(self) -> tuple[str, ...]:
        with self._lock:
            return self._latest.player_names

    def server_token(self) -> str:
        with self._lock:
            return self._latest.server_token

    @property
    def activity(self) -> str:
        with self._lock:
            return self._latest.activity

    def start(self) -> "FleetGsi":
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                status = 400
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if self.path == "/fleet" and 0 < length <= 65536:
                        payload = json.loads(self.rfile.read(length))
                        token = (payload.get("auth") or {}).get("token", "")
                        if isinstance(token, str) and hmac.compare_digest(token, owner.token):
                            status = 200 if owner.accept(payload) else 422
                        else:
                            status = 403
                except (ValueError, TypeError, AttributeError, OSError):
                    pass
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.server = HTTPServer(("127.0.0.1", self.port), Handler)
        self.port = int(self.server.server_address[1])
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.2},
                         daemon=True, name="fleet-gsi").start()
        return self

    def close(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
