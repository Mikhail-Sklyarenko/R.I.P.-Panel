"""Wire and domain models shared by coordinator and agents (stdlib only)."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field, fields, is_dataclass, replace
from enum import Enum
from typing import Any

from core.wingman_fleet import MVP_MAP, MVP_MODE, PROTOCOL_VERSION


class Role(str, Enum):
    LEADER = "leader"
    FOLLOWER = "follower"


class Link(str, Enum):
    HEALTHY = "healthy"
    SUSPECT = "suspect"
    OFFLINE = "offline"


class Screen(str, Enum):
    UNKNOWN = "unknown"
    NO_STEAM = "no_steam"
    STEAM_ONLY = "steam_only"
    MAIN_MENU = "main_menu"
    PLAY_MENU = "play_menu"
    SEARCHING = "searching"
    MATCH_CONFIRM = "match_confirm"
    LOADING = "loading"
    IN_MATCH = "in_match"
    MATCH_RESULT = "match_result"
    MODAL = "modal"


MENU_SCREENS = frozenset({Screen.MAIN_MENU, Screen.PLAY_MENU})


class Identity(str, Enum):
    UNCONFIRMED = "unconfirmed"
    STEAM_LOCAL = "steam_local"
    GSI = "gsi"
    MISMATCH = "mismatch"


class CommandType(str, Enum):
    PREFLIGHT = "preflight"
    SEND_FRIEND_REQUEST = "send_friend_request"
    LEAVE_LOBBY = "leave_lobby"
    CONFIGURE_LOBBY = "configure_lobby"
    INVITE = "invite"
    ACCEPT_INVITE = "accept_invite"
    START_SEARCH = "start_search"
    CANCEL_SEARCH = "cancel_search"
    ACCEPT_MATCH = "accept_match"
    PROBE_MATCH = "probe_match"
    START_GAMEPLAY = "start_gameplay"
    STOP_GAMEPLAY = "stop_gameplay"
    LEAVE_MATCH = "leave_match"
    RETURN_TO_MENU = "return_to_menu"
    RECONNECT_MATCH = "reconnect_match"
    RESTART_CS2 = "restart_cs2"
    RESTART_STEAM = "restart_steam"
    SCREENSHOT = "screenshot"
    SAFE_STOP = "safe_stop"
    PREPARE_ASSIGNMENT = "prepare_assignment"
    COMMIT_ASSIGNMENT = "commit_assignment"
    RELEASE_ASSIGNMENT = "release_assignment"
    VERIFY_ASSIGNMENT = "verify_assignment"
    RECONCILE_ASSIGNMENT = "reconcile_assignment"


ASSIGNMENT_COMMANDS = frozenset({
    CommandType.PREPARE_ASSIGNMENT,
    CommandType.COMMIT_ASSIGNMENT,
    CommandType.RELEASE_ASSIGNMENT,
    CommandType.VERIFY_ASSIGNMENT,
    CommandType.RECONCILE_ASSIGNMENT,
})


class ResultStatus(str, Enum):
    ACCEPTED = "accepted"
    ALREADY_APPLIED = "already_applied"
    REJECTED = "rejected"
    EXPIRED = "expired"
    COMPLETED = "completed"
    FAILED = "failed"
    # Clicks or console text were issued. The effect was not observed.
    UNCONFIRMED = "unconfirmed"


TERMINAL_RESULTS = frozenset({
    ResultStatus.ALREADY_APPLIED, ResultStatus.REJECTED, ResultStatus.EXPIRED,
    ResultStatus.COMPLETED, ResultStatus.FAILED, ResultStatus.UNCONFIRMED,
})


def new_id(prefix: str) -> str:
    return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return to_dict(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (frozenset, set)):
        return sorted(_plain(v) for v in value)
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def to_dict(obj: Any) -> dict[str, Any]:
    return {f.name: _plain(getattr(obj, f.name)) for f in fields(obj)}


def dumps(obj: Any) -> str:
    return json.dumps(to_dict(obj), ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class AccountProfile:
    account_id: str
    steam_id64: str
    display_name: str
    friend_code: str
    agent_id: str
    pair_id: str
    role: Role

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AccountProfile":
        steam_id = str(d["steam_id64"])
        if not steam_id.isdigit() or len(steam_id) != 17:
            raise ValueError(f"invalid steam_id64 for {d.get('account_id')}")
        return cls(str(d["account_id"]), steam_id, str(d["display_name"]),
                   str(d.get("friend_code", "")), str(d["agent_id"]),
                   str(d["pair_id"]), Role(d["role"]))


@dataclass(frozen=True)
class PairProfile:
    pair_id: str
    slot: int
    leader: AccountProfile
    follower: AccountProfile

    def member(self, role: Role) -> AccountProfile:
        return self.leader if role is Role.LEADER else self.follower

    @property
    def agents(self) -> tuple[str, str]:
        return self.leader.agent_id, self.follower.agent_id


@dataclass(frozen=True)
class RetryPolicy:
    stage_attempts: int = 2
    reinvites: int = 2
    lobby_recreates: int = 2
    cs2_restarts: int = 2
    steam_restarts: int = 1
    restart_window_sec: float = 1800.0
    failed_waves_per_hour: int = 8
    search_confirm_window_sec: float = 4.0
    search_start_lead_sec: float = 2.0
    search_timeout_sec: float = 600.0
    match_load_timeout_sec: float = 240.0
    match_proof_timeout_sec: float = 90.0
    post_match_timeout_sec: float = 180.0
    reconnect_wait_sec: float = 120.0
    roster_stable_sec: float = 2.0
    command_timeout_sec: float = 45.0
    max_cycles: int = 0  # 0 = until operator stop

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "RetryPolicy":
        d = d or {}
        known = {f.name for f in fields(cls)}
        return cls(**{k: type(getattr(cls(), k))(v) for k, v in d.items() if k in known})


@dataclass(frozen=True)
class RunPlan:
    """Immutable snapshot of one run; edits to the roster affect only the next run."""
    run_id: str
    created_at: float
    pairs: tuple[PairProfile, ...]
    build_version: str
    resource_manifest: str
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    map_id: str = MVP_MAP
    mode: str = MVP_MODE
    protocol: int = PROTOCOL_VERSION

    def pair(self, pair_id: str) -> PairProfile:
        return next(p for p in self.pairs if p.pair_id == pair_id)

    def account_for_agent(self, agent_id: str) -> AccountProfile | None:
        for p in self.pairs:
            for a in (p.leader, p.follower):
                if a.agent_id == agent_id:
                    return a
        return None

    @property
    def agent_ids(self) -> tuple[str, ...]:
        return tuple(a for p in self.pairs for a in p.agents)

    def to_json(self) -> str:
        return json.dumps(_plain(asdict(self)), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> "RunPlan":
        d = json.loads(raw)
        pairs = tuple(PairProfile(p["pair_id"], int(p["slot"]),
                                  AccountProfile.from_dict(p["leader"]),
                                  AccountProfile.from_dict(p["follower"])) for p in d["pairs"])
        return cls(d["run_id"], float(d["created_at"]), pairs, d["build_version"],
                   d["resource_manifest"], RetryPolicy.from_dict(d.get("retry")),
                   d.get("map_id", MVP_MAP), d.get("mode", MVP_MODE),
                   int(d.get("protocol", PROTOCOL_VERSION)))


@dataclass(frozen=True)
class LobbyView:
    members: tuple[str, ...] = ()
    self_is_leader: bool = False
    mode: str = ""
    map_id: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "LobbyView":
        d = d or {}
        return cls(tuple(str(m) for m in d.get("members", ())), bool(d.get("self_is_leader")),
                   str(d.get("mode", "")), str(d.get("map_id", "")))


@dataclass(frozen=True)
class GsiView:
    age_sec: float = float("inf")
    steam_id64: str = ""
    mode: str = ""
    map_id: str = ""
    map_phase: str = ""
    round_phase: str = ""
    team: str = ""
    round_number: int = -1
    alive: bool = False

    @property
    def fresh(self) -> bool:
        return self.age_sec <= 2.0

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "GsiView":
        d = d or {}
        age = d.get("age_sec")
        return cls(float(age) if age is not None else float("inf"), str(d.get("steam_id64", "")),
                   str(d.get("mode", "")), str(d.get("map_id", "")), str(d.get("map_phase", "")),
                   str(d.get("round_phase", "")), str(d.get("team", "")),
                   int(d.get("round_number", -1)), bool(d.get("alive")))


@dataclass(frozen=True)
class MatchFingerprint:
    server_token: str = ""
    players: tuple[str, ...] = ()
    observed_age_sec: float = float("inf")

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "MatchFingerprint | None":
        if not d:
            return None
        age = d.get("observed_age_sec")
        return cls(str(d.get("server_token", "")), tuple(str(p) for p in d.get("players", ())),
                   float(age) if age is not None else float("inf"))


@dataclass(frozen=True)
class Observation:
    """What one agent actually saw; absent evidence is never treated as success."""
    agent_id: str
    sequence: int
    protocol: int = PROTOCOL_VERSION
    build_version: str = ""
    resource_manifest: str = ""
    steam_running: bool = False
    cs2_running: bool = False
    steam_id64: str = ""
    identity: Identity = Identity.UNCONFIRMED
    screen: Screen = Screen.UNKNOWN
    screen_confidence: float = 0.0
    screen_stable_sec: float = 0.0
    modal: str = ""
    lobby: LobbyView = field(default_factory=LobbyView)
    invite_from: str = ""
    friends: frozenset[str] = frozenset()
    gsi: GsiView = field(default_factory=GsiView)
    fingerprint: MatchFingerprint | None = None
    capture_age_sec: float = float("inf")
    input_owner: str = "none"
    worker_running: bool = False
    worker_exit: str = ""
    preflight_ok: bool = False
    preflight_failures: tuple[str, ...] = ()
    cooldown: bool = False
    update_required: bool = False
    active_command: str = ""
    age_sec: float = 0.0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Observation":
        def f(name, default):
            return d.get(name, default)
        return cls(
            agent_id=str(d["agent_id"]), sequence=int(d["sequence"]),
            protocol=int(f("protocol", 0)), build_version=str(f("build_version", "")),
            resource_manifest=str(f("resource_manifest", "")),
            steam_running=bool(f("steam_running", False)), cs2_running=bool(f("cs2_running", False)),
            steam_id64=str(f("steam_id64", "")), identity=Identity(f("identity", "unconfirmed")),
            screen=Screen(f("screen", "unknown")), screen_confidence=float(f("screen_confidence", 0)),
            screen_stable_sec=float(f("screen_stable_sec", 0)), modal=str(f("modal", "")),
            lobby=LobbyView.from_dict(f("lobby", None)), invite_from=str(f("invite_from", "")),
            friends=frozenset(str(x) for x in f("friends", ())),
            gsi=GsiView.from_dict(f("gsi", None)),
            fingerprint=MatchFingerprint.from_dict(f("fingerprint", None)),
            capture_age_sec=float(f("capture_age_sec", float("inf")) if f("capture_age_sec", None) is not None else float("inf")),
            input_owner=str(f("input_owner", "none")), worker_running=bool(f("worker_running", False)),
            worker_exit=str(f("worker_exit", "")), preflight_ok=bool(f("preflight_ok", False)),
            preflight_failures=tuple(str(x) for x in f("preflight_failures", ())),
            cooldown=bool(f("cooldown", False)), update_required=bool(f("update_required", False)),
            active_command=str(f("active_command", "")), age_sec=float(f("age_sec", 0.0)),
        )

    def aged(self, extra: float) -> "Observation":
        return replace(self, age_sec=self.age_sec + max(0.0, extra))


@dataclass(frozen=True)
class Command:
    command_id: str
    run_id: str
    agent_id: str
    type: CommandType
    params: dict[str, Any] = field(default_factory=dict)
    pair_id: str = ""
    attempt: int = 1
    deadline_sec: float = 45.0
    issued_at: float = 0.0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Command":
        return cls(str(d["command_id"]), str(d["run_id"]), str(d["agent_id"]),
                   CommandType(d["type"]), dict(d.get("params") or {}), str(d.get("pair_id", "")),
                   int(d.get("attempt", 1)), float(d.get("deadline_sec", 45.0)),
                   float(d.get("issued_at", 0.0)))


@dataclass(frozen=True)
class CommandResult:
    command_id: str
    status: ResultStatus
    reason: str = ""
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CommandResult":
        return cls(str(d["command_id"]), ResultStatus(d["status"]), str(d.get("reason", "")),
                   str(d.get("detail", "")), dict(d.get("evidence") or {}))

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_RESULTS

    @property
    def succeeded(self) -> bool:
        return self.status in (ResultStatus.COMPLETED, ResultStatus.ALREADY_APPLIED)
