"""Deterministic simulated Steam/CS2 world for fleet tests and dry runs.

Models what the real backends observe: lobbies, invites, friendship, the
matchmaking outcome of a wave (`same`, `split`, `lone`), the match confirm
dialog, loading, GSI, console `status` fingerprints, match end and faults.
"""
from __future__ import annotations

import itertools
from collections import deque
from dataclasses import dataclass, field

from core.wingman_fleet import MVP_MAP, MVP_MODE, PROTOCOL_VERSION
from core.wingman_fleet.models import (
    MENU_SCREENS, Command, CommandResult, CommandType, GsiView, Identity, LobbyView,
    MatchFingerprint, Observation, ResultStatus, Screen,
)

CONFIRM_LAPSE_SEC = 20.0
LOAD_SEC = 3.0


@dataclass
class SimClient:
    agent_id: str
    steam_id64: str
    name: str
    steam_running: bool = True
    cs2_running: bool = True
    logged_in_as: str = ""
    screen: Screen = Screen.MAIN_MENU
    party_leader: str = ""
    lobby_mode: str = ""
    lobby_map: str = ""
    invite_from: str = ""
    friends: set[str] = field(default_factory=set)
    outgoing_requests: set[str] = field(default_factory=set)
    match_id: str = ""
    accepted: bool = False
    fingerprint: MatchFingerprint | None = None
    worker_running: bool = False
    worker_exit: str = ""
    preflight_ok: bool = True
    cooldown: bool = False
    screen_since: float = 0.0
    online: bool = True

    def __post_init__(self):
        self.party_leader = self.party_leader or self.agent_id
        self.logged_in_as = self.logged_in_as or self.steam_id64


@dataclass
class SimMatch:
    match_id: str
    members: list[str]
    bots: list[str]
    found_at: float
    loaded_at: float = 0.0
    duration: float = 60.0
    finished: bool = False


class SimWorld:
    def __init__(self, accounts: list[tuple[str, str, str]], *, build: str = "test-build",
                 manifest: str = "test-manifest", match_delay: float = 5.0, match_duration: float = 60.0):
        self.now = 1_000_000.0
        self.build, self.manifest = build, manifest
        self.clients = {a: SimClient(a, sid, name) for a, sid, name in accounts}
        self.match_delay, self.match_duration = match_delay, match_duration
        self.outcomes: deque[str] = deque()  # scripted per wave: same | split | lone
        self.drop_invites = 0                 # next N invites never arrive
        self.matches: dict[str, SimMatch] = {}
        self.search_started: dict[str, float] = {}  # party leader -> time
        self.starved: set[str] = set()              # keeps searching without a match this wave
        self._ids = itertools.count(1)
        self._seq = itertools.count(1)
        self.log: list[str] = []

    # ----- topology ------------------------------------------------------------------
    def party(self, agent_id: str) -> list[str]:
        leader = self.clients[agent_id].party_leader
        return sorted(a for a, c in self.clients.items() if c.party_leader == leader)

    def _set_screen(self, c: SimClient, screen: Screen) -> None:
        if c.screen is not screen:
            c.screen, c.screen_since = screen, self.now

    def _leave_party(self, c: SimClient) -> None:
        old_leader = c.party_leader
        c.party_leader = c.agent_id
        if old_leader == c.agent_id:
            for other in self.clients.values():
                if other is not c and other.party_leader == c.agent_id:
                    other.party_leader = other.agent_id
                    other.lobby_mode, other.lobby_map = "", ""
        self.search_started.pop(old_leader, None)

    # ----- observation ---------------------------------------------------------------
    def observe(self, agent_id: str) -> Observation:
        c = self.clients[agent_id]
        leader = self.clients[c.party_leader]
        lobby = LobbyView(tuple(self.clients[a].name for a in self.party(agent_id)) if c.cs2_running else (),
                          c.party_leader == agent_id, leader.lobby_mode, leader.lobby_map)
        match = self.matches.get(c.match_id)
        gsi = GsiView()
        if c.cs2_running and match and match.loaded_at and c.screen in (Screen.IN_MATCH, Screen.MATCH_RESULT):
            gsi = GsiView(0.2, c.logged_in_as, MVP_MODE, MVP_MAP,
                          "gameover" if match.finished else "live", "live", "CT", 1, True)
        identity = Identity.STEAM_LOCAL if c.steam_running else Identity.UNCONFIRMED
        screen = c.screen if c.cs2_running else (Screen.STEAM_ONLY if c.steam_running else Screen.NO_STEAM)
        return Observation(
            agent_id=agent_id, sequence=next(self._seq), protocol=PROTOCOL_VERSION,
            build_version=self.build, resource_manifest=self.manifest,
            steam_running=c.steam_running, cs2_running=c.cs2_running,
            steam_id64=c.logged_in_as if c.steam_running else "", identity=identity,
            screen=screen, screen_confidence=1.0, screen_stable_sec=self.now - c.screen_since,
            lobby=lobby if screen in MENU_SCREENS | {Screen.SEARCHING} else LobbyView(),
            invite_from=c.invite_from, friends=frozenset(c.friends), gsi=gsi,
            fingerprint=c.fingerprint, capture_age_sec=0.1,
            input_owner="gameplay" if c.worker_running else "none",
            worker_running=c.worker_running, worker_exit=c.worker_exit,
            preflight_ok=c.preflight_ok and c.cs2_running, cooldown=c.cooldown)

    # ----- commands ------------------------------------------------------------------
    def execute(self, agent_id: str, cmd: Command) -> CommandResult:
        c = self.clients[agent_id]
        handler = getattr(self, f"_do_{cmd.type.value}")
        ok, reason, detail = handler(c, cmd.params)
        self.log.append(f"{self.now:.1f} {agent_id} {cmd.type.value} -> {ok} {reason}")
        return CommandResult(cmd.command_id, ResultStatus.COMPLETED if ok else ResultStatus.FAILED,
                             reason, detail)

    def _need_menu(self, c: SimClient):
        if not c.cs2_running or c.screen not in MENU_SCREENS:
            return False, "unknown_screen", c.screen.value
        return None

    def _do_preflight(self, c, p):
        return c.preflight_ok, "" if c.preflight_ok else "preflight_failed", ""

    def _do_send_friend_request(self, c, p):
        target = next((o for o in self.clients.values() if o.steam_id64 == p["steam_id64"]), None)
        if target is None:
            return False, "friendship_not_confirmed", "unknown account"
        c.outgoing_requests.add(target.steam_id64)
        if c.steam_id64 in target.outgoing_requests:
            c.friends.add(target.steam_id64)
            target.friends.add(c.steam_id64)
        return True, "", ""

    def _do_leave_lobby(self, c, p):
        if (r := self._need_menu(c)):
            return r
        self._leave_party(c)
        return True, "", ""

    def _do_configure_lobby(self, c, p):
        if (r := self._need_menu(c)):
            return r
        if c.party_leader != c.agent_id:
            return False, "lobby_wrong_roster", "not leader"
        c.lobby_mode, c.lobby_map = p["mode"], p["map_id"]
        return True, "", ""

    def _do_invite(self, c, p):
        if (r := self._need_menu(c)):
            return r
        target = next(o for o in self.clients.values() if o.steam_id64 == p["steam_id64"])
        if c.steam_id64 not in target.friends:
            return False, "friendship_not_confirmed", ""
        if self.drop_invites > 0:
            self.drop_invites -= 1
            return True, "", "sent (dropped by fault injection)"
        target.invite_from = c.steam_id64
        return True, "", ""

    def _do_accept_invite(self, c, p):
        if (r := self._need_menu(c)):
            return r
        if c.invite_from != p["steam_id64"]:
            return False, "invite_not_received", ""
        leader = next(o for o in self.clients.values() if o.steam_id64 == c.invite_from)
        self._leave_party(c)
        c.party_leader, c.invite_from = leader.agent_id, ""
        return True, "", ""

    def _do_start_search(self, c, p):
        if (r := self._need_menu(c)):
            return r
        if c.party_leader != c.agent_id:
            return False, "search_not_started", "not leader"
        if c.cooldown:
            return False, "cooldown", ""
        self.search_started[c.agent_id] = self.now
        self.starved.discard(c.agent_id)
        for a in self.party(c.agent_id):
            self._set_screen(self.clients[a], Screen.SEARCHING)
        return True, "", ""

    def _do_cancel_search(self, c, p):
        self.search_started.pop(c.party_leader, None)
        for a in self.party(c.agent_id):
            if self.clients[a].screen is Screen.SEARCHING:
                self._set_screen(self.clients[a], Screen.MAIN_MENU)
        return True, "", ""

    def _do_accept_match(self, c, p):
        if c.screen is not Screen.MATCH_CONFIRM:
            return False, "unknown_screen", c.screen.value
        c.accepted = True
        return True, "", ""

    def _do_probe_match(self, c, p):
        m = self.matches.get(c.match_id)
        if m is None or not m.loaded_at:
            c.fingerprint = None
            return False, "match_proof_unavailable", "not in a match"
        names = [self.clients[a].name for a in m.members] + m.bots
        c.fingerprint = MatchFingerprint(m.match_id, tuple(names), 0.0)
        return True, "", ""

    def _do_start_gameplay(self, c, p):
        if c.screen is not Screen.IN_MATCH:
            return False, "unknown_screen", c.screen.value
        c.worker_running, c.worker_exit = True, ""
        return True, "", ""

    def _do_stop_gameplay(self, c, p):
        c.worker_running = False
        return True, "", ""

    _do_safe_stop = _do_stop_gameplay

    def _do_leave_match(self, c, p):
        c.worker_running, c.worker_exit = False, ""
        if not c.cs2_running:
            return False, "cs2_not_running", ""
        if c.screen is Screen.MATCH_CONFIRM:
            return True, "", "confirm left to lapse"
        c.match_id, c.fingerprint, c.accepted = "", None, False
        self._set_screen(c, Screen.MAIN_MENU)
        self._leave_party(c)
        return True, "", ""

    def _do_return_to_menu(self, c, p):
        c.worker_running, c.worker_exit = False, ""
        if c.screen in (Screen.MATCH_RESULT, Screen.IN_MATCH, Screen.MODAL):
            m = self.matches.get(c.match_id)
            if c.screen is Screen.IN_MATCH and m and not m.finished:
                return False, "unknown_screen", "match still running"
            c.match_id, c.fingerprint, c.accepted = "", None, False
            self._set_screen(c, Screen.MAIN_MENU)
        return True, "", ""

    def _do_reconnect_match(self, c, p):
        m = next((m for m in self.matches.values() if c.agent_id in m.members and not m.finished), None)
        if m is None:
            return False, "match_proof_unavailable", "no match to reconnect"
        c.match_id = m.match_id
        self._set_screen(c, Screen.IN_MATCH)
        return True, "", ""

    def _do_restart_cs2(self, c, p):
        if not c.steam_running:
            return False, "steam_not_running", ""
        c.cs2_running, c.worker_running = True, False
        c.match_id, c.fingerprint = "", None
        self._leave_party(c)
        self._set_screen(c, Screen.MAIN_MENU)
        return True, "", ""

    def _do_restart_steam(self, c, p):
        c.steam_running = True
        return self._do_restart_cs2(c, p)

    def _do_screenshot(self, c, p):
        return True, "", "sim"

    # ----- faults --------------------------------------------------------------------
    def crash_cs2(self, agent_id: str) -> None:
        c = self.clients[agent_id]
        c.cs2_running, c.worker_running = False, False
        self._leave_party(c)
        self._set_screen(c, Screen.UNKNOWN)

    def drop_to_menu(self, agent_id: str) -> None:
        c = self.clients[agent_id]
        c.worker_running = False
        self._set_screen(c, Screen.MAIN_MENU)

    # ----- time ----------------------------------------------------------------------
    def advance(self, dt: float) -> None:
        self.now += dt
        self._matchmaking()
        self._confirm_and_load()
        self._finish()

    def _matchmaking(self) -> None:
        ready = [l for l, t in self.search_started.items()
                 if self.now - t >= self.match_delay and l not in self.starved]
        if not ready:
            return
        outcome = self.outcomes.popleft() if self.outcomes else "same"
        groups: list[list[str]]
        if outcome == "same" and len(self.search_started) >= 2:
            groups = [list(self.search_started)]
        elif outcome == "lone":
            groups = [[ready[0]]]
            self.starved |= set(self.search_started) - {ready[0]}
        else:
            groups = [[l] for l in ready]
        for leaders in groups:
            members = [a for l in leaders for a in self.party(l)]
            mid = f"srv-{next(self._ids)}"
            bots = [] if len(members) >= 4 else [f"Stranger{next(self._ids)}" for _ in range(4 - len(members))]
            self.matches[mid] = SimMatch(mid, members, bots, self.now, duration=self.match_duration)
            for l in leaders:
                self.search_started.pop(l, None)
            for a in members:
                c = self.clients[a]
                c.match_id, c.accepted = mid, False
                self._set_screen(c, Screen.MATCH_CONFIRM)

    def _confirm_and_load(self) -> None:
        for m in self.matches.values():
            if m.finished or m.loaded_at:
                continue
            clients = [self.clients[a] for a in m.members]
            if all(c.accepted for c in clients):
                for c in clients:
                    self._set_screen(c, Screen.LOADING)
                m.loaded_at = -1.0
            elif self.now - m.found_at > CONFIRM_LAPSE_SEC:
                m.finished = True
                for c in clients:
                    c.match_id, c.accepted = "", False
                    self._set_screen(c, Screen.MAIN_MENU)
        for m in self.matches.values():
            if m.loaded_at == -1.0 and self.now - m.found_at >= LOAD_SEC:
                m.loaded_at = self.now
                for a in m.members:
                    if self.clients[a].match_id == m.match_id:
                        self._set_screen(self.clients[a], Screen.IN_MATCH)

    def backend(self, agent_id: str) -> "SimBackend":
        return SimBackend(self, agent_id)

    def _finish(self) -> None:
        for m in self.matches.values():
            if m.loaded_at > 0 and not m.finished and self.now - m.loaded_at >= m.duration:
                m.finished = True
                for a in m.members:
                    c = self.clients[a]
                    if c.match_id == m.match_id and c.screen is Screen.IN_MATCH:
                        c.worker_exit = "match_finished" if c.worker_running else c.worker_exit
                        c.worker_running = False
                        self._set_screen(c, Screen.MATCH_RESULT)


class SimBackend:
    """GameBackend over a SimWorld client, with the same lease rules as the real one."""

    def __init__(self, world: SimWorld, agent_id: str):
        self.world, self.agent_id = world, agent_id
        self.lease = ""
        self.stops: list[str] = []
        self.executed: list[str] = []

    @property
    def client(self) -> SimClient:
        return self.world.clients[self.agent_id]

    def observe(self) -> Observation:
        return self.world.observe(self.agent_id)

    def execute(self, cmd: Command, ctx) -> CommandResult:
        if cmd.type is CommandType.START_GAMEPLAY and ctx.gameplay_attempt() != cmd.params.get("attempt_id"):
            return CommandResult(cmd.command_id, ResultStatus.REJECTED, "gameplay_not_admitted",
                                 f"lease={ctx.gameplay_attempt()!r}")
        self.executed.append(cmd.command_id)
        return self.world.execute(self.agent_id, cmd)

    def set_gameplay(self, attempt_id: str, generation: int = 0) -> None:
        self.lease = attempt_id
        if not attempt_id and self.client.worker_running:
            self.client.worker_running = False
            self.stops.append("lease revoked")

    def safe_stop(self, reason: str) -> None:
        self.client.worker_running = False
        self.stops.append(reason)
