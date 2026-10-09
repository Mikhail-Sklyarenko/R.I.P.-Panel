"""Pair FSM: friendship and lobby preparation for one fixed leader/follower pair.

Every tick re-derives progress from fresh observations; the machine only returns
commands (effects), it never touches the OS. Matchmaking is owned by RunFSM,
which locks READY pairs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from core.wingman_fleet import MVP_MAP
from core.wingman_fleet.budget import Budget
from core.wingman_fleet.models import (
    MENU_SCREENS, Command, CommandResult, CommandType, Identity, Link, Observation,
    PairProfile, ResultStatus, Role, RunPlan, Screen,
)
from core.wingman_fleet.reasons import MANUAL_ONLY, Reason

LOBBY_MODE = "wingman"
UNKNOWN_SCREEN_RECOVERY_SEC = 60.0
FRIEND_CONFIRM_SEC = 30.0
MAX_CORRECTIONS = 3
_CORRECTIVE = frozenset({CommandType.CANCEL_SEARCH.value, CommandType.RETURN_TO_MENU.value,
                         CommandType.LEAVE_MATCH.value})


class PairState(str, Enum):
    WAITING = "waiting"
    IDENTITY = "identity"
    PREFLIGHT = "preflight"
    FRIENDSHIP = "friendship"
    LOBBY_RESET = "lobby_reset"
    LOBBY_CONFIGURE = "lobby_configure"
    LOBBY_INVITE = "lobby_invite"
    LOBBY_ACCEPT = "lobby_accept"
    LOBBY_VERIFY = "lobby_verify"
    READY = "ready"
    MATCH = "match"
    RECOVER_CS2 = "recover_cs2"
    RECOVER_STEAM = "recover_steam"
    PAUSED = "paused"
    MANUAL = "manual"
    STOPPED = "stopped"


HALTED = frozenset({PairState.PAUSED, PairState.MANUAL, PairState.STOPPED})
GATE_STATES = frozenset({PairState.WAITING, PairState.IDENTITY, PairState.PREFLIGHT})


def norm(name: str) -> str:
    return " ".join(name.casefold().split())


@dataclass
class ActiveCommand:
    command_id: str
    agent_id: str
    type: str
    issued_at: float
    stage: str

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class PairCtx:
    state: PairState = PairState.WAITING
    entered_at: float = 0.0
    reason: str = Reason.WAITING_AGENT.value
    detail: str = ""
    seq: int = 0
    cycle: int = 0
    stage_attempts: int = 0
    step_index: int = 0
    confirm_until: float = 0.0
    stable_since: float = 0.0
    unknown_since: float = 0.0
    lobby_formed: bool = False
    corrections: int = 0
    active: ActiveCommand | None = None
    last_failure: str = ""
    recover_roles: list[str] = field(default_factory=list)
    budget_state: dict[str, list[float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "active"}
        d["state"] = self.state.value
        d["active"] = self.active.to_dict() if self.active else None
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PairCtx":
        d = dict(d)
        active = d.pop("active", None)
        ctx = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        ctx.state = PairState(ctx.state)
        ctx.active = ActiveCommand(**active) if active else None
        return ctx


@dataclass(frozen=True)
class Stage:
    commands: Callable[["PairMachine", Observation, Observation], list[tuple[Role, CommandType, dict]]]
    done: Callable[["PairMachine", Observation, Observation], PairState | None]
    on_exhausted: Callable[["PairMachine", float], None]
    failure_reason: Reason
    attempts: int = 2
    confirm_sec: float = 6.0


class PairMachine:
    def __init__(self, plan: RunPlan, pair: PairProfile, ctx: PairCtx | None = None,
                 on_transition: Callable[..., None] | None = None):
        self.plan, self.pair = plan, pair
        r = plan.retry
        self.budget = Budget({
            "reinvite": (r.reinvites, 1e12),
            "recreate": (r.lobby_recreates, 1e12),
            "cs2": (r.cs2_restarts, r.restart_window_sec),
            "steam": (r.steam_restarts, r.restart_window_sec),
        })
        self.ctx = ctx or PairCtx()
        self.budget.load_state(self.ctx.budget_state)
        self.on_transition = on_transition or (lambda **_: None)
        self.known_friends = False
        self.expected = {norm(pair.leader.display_name), norm(pair.follower.display_name)}

    # ----- persistence / transitions -------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        self.ctx.budget_state = self.budget.to_state()
        return self.ctx.to_dict()

    @property
    def state(self) -> PairState:
        return self.ctx.state

    def goto(self, state: PairState, now: float, reason: Reason | str = Reason.OK, detail: str = "") -> None:
        before = self.ctx.state
        reason = Reason(reason) if not isinstance(reason, Reason) else reason
        if before == state and self.ctx.reason == reason.value and self.ctx.detail == detail:
            return
        if before != state:
            self.ctx.entered_at = now
            self.ctx.stage_attempts = 0
            self.ctx.step_index = 0
            self.ctx.confirm_until = 0.0
            self.ctx.stable_since = 0.0
            self.ctx.active = None
            self.ctx.recover_roles = []
        self.ctx.state, self.ctx.reason, self.ctx.detail = state, reason.value, detail
        self.on_transition(pair_id=self.pair.pair_id, before=before.value, after=state.value,
                           reason=reason.value, detail=detail)

    def hold(self, reason: Reason, detail: str = "") -> None:
        if self.ctx.reason != reason.value or self.ctx.detail != detail:
            self.ctx.reason, self.ctx.detail = reason.value, detail
            self.on_transition(pair_id=self.pair.pair_id, before=self.ctx.state.value,
                               after=self.ctx.state.value, reason=reason.value, detail=detail)

    # ----- operator ------------------------------------------------------------------
    def pause(self, now: float, reason: Reason = Reason.OPERATOR_PAUSE) -> None:
        self.goto(PairState.PAUSED, now, reason)

    def resume(self, now: float) -> None:
        if self.state in (PairState.PAUSED, PairState.MANUAL):
            self.budget.reset()
            self.goto(PairState.WAITING, now, Reason.WAITING_AGENT, "resumed by operator")

    def retry_stage(self, now: float) -> None:
        self.ctx.stage_attempts = 0
        self.ctx.active = None
        self.ctx.confirm_until = 0.0

    def force_recreate(self, now: float) -> None:
        if self.state not in HALTED and self.state is not PairState.MATCH:
            self.ctx.lobby_formed = False
            self.goto(PairState.LOBBY_RESET, now, Reason.LOBBY_RECREATE, "operator")

    def stop(self, now: float) -> None:
        self.goto(PairState.STOPPED, now, Reason.OPERATOR_STOP)

    def lock_for_match(self, now: float) -> None:
        self.goto(PairState.MATCH, now, Reason.OK, "matchmaking")

    def release_from_match(self, now: float, *, recreate: bool, reason: Reason = Reason.OK) -> None:
        if self.state is PairState.MATCH:
            self.ctx.cycle += 1
            if recreate:
                self.ctx.lobby_formed = False
            self.goto(PairState.LOBBY_RESET if recreate else PairState.LOBBY_VERIFY, now, reason)

    # ----- predicates ----------------------------------------------------------------
    def roster_ok(self, o: Observation, role: Role) -> bool:
        return ({norm(m) for m in o.lobby.members} == self.expected and len(o.lobby.members) == 2
                and o.lobby.self_is_leader == (role is Role.LEADER))

    def solo(self, o: Observation, role: Role) -> bool:
        own = norm(self.pair.member(role).display_name)
        return len(o.lobby.members) == 1 and norm(o.lobby.members[0]) == own

    @staticmethod
    def configured(o: Observation) -> bool:
        return o.lobby.mode == LOBBY_MODE and o.lobby.map_id == MVP_MAP

    def friends(self, L: Observation, F: Observation) -> bool:
        if self.known_friends:
            return True
        return self.pair.follower.steam_id64 in L.friends and self.pair.leader.steam_id64 in F.friends

    def invite_seen(self, F: Observation) -> bool:
        leader = self.pair.leader
        return bool(F.invite_from) and (F.invite_from == leader.steam_id64
                                        or norm(F.invite_from) == norm(leader.display_name))

    def lobby_complete(self, L: Observation, F: Observation) -> bool:
        return (self.roster_ok(L, Role.LEADER) and self.roster_ok(F, Role.FOLLOWER)
                and self.configured(L) and self.configured(F)
                and L.screen in MENU_SCREENS and F.screen in MENU_SCREENS)

    # ----- command issue -------------------------------------------------------------
    def _command(self, role: Role, ctype: CommandType, params: dict, now: float) -> Command:
        self.ctx.seq += 1
        agent = self.pair.member(role).agent_id
        cid = (f"{self.plan.run_id}/{self.pair.pair_id}/c{self.ctx.cycle}/"
               f"{self.ctx.state.value}/{self.ctx.seq}/{role.value}")
        self.ctx.active = ActiveCommand(cid, agent, ctype.value, now, self.ctx.state.value)
        return Command(cid, self.plan.run_id, agent, ctype, params, self.pair.pair_id,
                       self.ctx.stage_attempts, self.plan.retry.command_timeout_sec, now)

    # ----- main step -----------------------------------------------------------------
    def step(self, now: float, obs: dict[str, Observation], links: dict[str, Link],
             results: dict[str, CommandResult]) -> list[Command]:
        if self.state in HALTED or self.state is PairState.MATCH:
            return []
        L = obs.get(self.pair.leader.agent_id)
        F = obs.get(self.pair.follower.agent_id)
        gate = self._gates(now, L, F, links)
        if gate is not None:
            return gate
        assert L is not None and F is not None
        if self.state in GATE_STATES:
            self.goto(PairState.FRIENDSHIP, now, Reason.OK)
        if self.state in (PairState.RECOVER_CS2, PairState.RECOVER_STEAM):
            return self._recover(now, L, F, results)
        normalize = self._normalize(now, L, F, results)
        if normalize is not None:
            return normalize
        if self.state is PairState.LOBBY_VERIFY:
            self._verify(now, L, F)
            return []
        if self.state is PairState.READY:
            if not self.lobby_complete(L, F):
                self.escalate_lobby(now, Reason.LOBBY_WRONG_ROSTER)
            return []
        return self._run_stage(STAGES[self.state], now, L, F, results)

    def _verify(self, now: float, L: Observation, F: Observation) -> None:
        if self.lobby_complete(L, F):
            if not self.ctx.stable_since:
                self.ctx.stable_since = now
            if now - self.ctx.stable_since >= self.plan.retry.roster_stable_sec:
                self.ctx.lobby_formed = True
                self.budget.reset("reinvite")
                self.goto(PairState.READY, now, Reason.OK)
            return
        self.ctx.stable_since = 0.0
        if self.roster_ok(L, Role.LEADER) and self.roster_ok(F, Role.FOLLOWER):
            if not (self.configured(L) and self.configured(F)):
                self.goto(PairState.LOBBY_CONFIGURE, now, Reason.LOBBY_NOT_CONFIGURED)
            return
        if self.ctx.lobby_formed:
            self.escalate_lobby(now, Reason.LOBBY_WRONG_ROSTER)
        else:
            self.goto(PairState.LOBBY_RESET, now, Reason.LOBBY_WRONG_ROSTER)

    def _gates(self, now, L, F, links) -> list[Command] | None:
        recovering = self.state in (PairState.RECOVER_CS2, PairState.RECOVER_STEAM)
        for account, o in ((self.pair.leader, L), (self.pair.follower, F)):
            link = links.get(account.agent_id, Link.OFFLINE)
            if o is None or link is Link.OFFLINE:
                self._gate(PairState.WAITING, now, Reason.AGENT_OFFLINE if o else Reason.WAITING_AGENT,
                           account.agent_id)
                return []
            if link is Link.SUSPECT:
                self.hold(Reason.AGENT_SUSPECT, account.agent_id)
                return []
            if o.protocol != self.plan.protocol:
                self.goto(PairState.MANUAL, now, Reason.PROTOCOL_MISMATCH, account.agent_id)
                return self._safe_stop_both(now)
            if o.build_version != self.plan.build_version:
                self.goto(PairState.MANUAL, now, Reason.BUILD_MISMATCH,
                          f"{account.agent_id}: {o.build_version} != {self.plan.build_version}")
                return []
            if o.resource_manifest != self.plan.resource_manifest:
                self.goto(PairState.MANUAL, now, Reason.RESOURCE_MISMATCH, account.agent_id)
                return []
            if o.identity is Identity.MISMATCH or (o.steam_id64 and o.steam_id64 != account.steam_id64):
                self.goto(PairState.MANUAL, now, Reason.ACCOUNT_MISMATCH,
                          f"{account.agent_id}: ожидался {account.steam_id64}, обнаружен {o.steam_id64 or '?'}")
                return self._safe_stop_both(now)
            if o.update_required:
                self.goto(PairState.MANUAL, now, Reason.CS2_UPDATE_REQUIRED, account.agent_id)
                return []
            if o.cooldown:
                self.goto(PairState.MANUAL, now, Reason.COOLDOWN, account.agent_id)
                return []
            if recovering:
                continue
            if not o.steam_running:
                return self._enter_recovery(now, PairState.RECOVER_STEAM, Reason.STEAM_NOT_RUNNING, account.agent_id)
            if o.identity is Identity.UNCONFIRMED:
                self._gate(PairState.IDENTITY, now, Reason.IDENTITY_UNCONFIRMED, account.agent_id)
                return []
            if not o.cs2_running:
                return self._enter_recovery(now, PairState.RECOVER_CS2, Reason.CS2_NOT_RUNNING, account.agent_id)
            if not o.preflight_ok:
                self._gate(PairState.PREFLIGHT, now, Reason.PREFLIGHT_FAILED,
                           f"{account.agent_id}: {', '.join(o.preflight_failures) or 'pending'}")
                return []
        return None

    def _gate(self, state: PairState, now: float, reason: Reason, detail: str) -> None:
        if self.state is not state:
            self.goto(state, now, reason, detail)
        else:
            self.hold(reason, detail)

    def _safe_stop_both(self, now: float) -> list[Command]:
        cmds = []
        for role in (Role.LEADER, Role.FOLLOWER):
            agent = self.pair.member(role).agent_id
            self.ctx.seq += 1
            cid = f"{self.plan.run_id}/{self.pair.pair_id}/safe_stop/{self.ctx.seq}/{role.value}"
            cmds.append(Command(cid, self.plan.run_id, agent, CommandType.SAFE_STOP, {},
                                self.pair.pair_id, 1, 10.0, now))
        return cmds

    def _normalize(self, now, L, F, results) -> list[Command] | None:
        """Bring both clients back to a menu before any lobby step; unknown means wait."""
        for role, o in ((Role.LEADER, L), (Role.FOLLOWER, F)):
            if o.screen in MENU_SCREENS:
                continue
            if o.screen in (Screen.UNKNOWN, Screen.MODAL, Screen.STEAM_ONLY, Screen.NO_STEAM):
                if not self.ctx.unknown_since:
                    self.ctx.unknown_since = now
                if now - self.ctx.unknown_since >= UNKNOWN_SCREEN_RECOVERY_SEC:
                    self.ctx.unknown_since = 0.0
                    return self._enter_recovery(now, PairState.RECOVER_CS2, Reason.UNKNOWN_SCREEN,
                                                self.pair.member(role).agent_id)
                self.hold(Reason.BLOCKING_MODAL if o.screen is Screen.MODAL else Reason.UNKNOWN_SCREEN,
                          f"{self.pair.member(role).agent_id}: {o.modal or o.screen.value}")
                return []
            ctype = {Screen.SEARCHING: CommandType.CANCEL_SEARCH,
                     Screen.MATCH_RESULT: CommandType.RETURN_TO_MENU,
                     Screen.IN_MATCH: CommandType.LEAVE_MATCH,
                     Screen.LOADING: CommandType.LEAVE_MATCH}.get(o.screen)
            if ctype is None:  # MATCH_CONFIRM: never accept outside of RunFSM; let it lapse
                return []
            return self._single(now, role, ctype, {}, results)
        self.ctx.unknown_since = 0.0
        if self.ctx.corrections and self.ctx.active is None:
            self.ctx.corrections = 0
        if self.ctx.active is not None and self.ctx.active.type in _CORRECTIVE:
            self.ctx.active = None
        return None

    def _single(self, now, role, ctype, params, results) -> list[Command]:
        """Corrective command outside the stage table: one at a time and counted."""
        active = self.ctx.active
        if active is not None:
            res = results.get(active.command_id)
            if (res is None or not res.terminal) and now - active.issued_at < self.plan.retry.command_timeout_sec:
                return []
            self.ctx.active = None
            self.ctx.confirm_until = now + 3.0
            return []
        if now < self.ctx.confirm_until:
            return []
        if self.ctx.corrections >= MAX_CORRECTIONS:
            self.ctx.corrections = 0
            return self._enter_recovery(now, PairState.RECOVER_CS2, Reason.COMMAND_FAILED,
                                        f"{ctype.value} did not restore the menu")
        self.ctx.corrections += 1
        return [self._command(role, ctype, params, now)]

    def _run_stage(self, spec: Stage, now, L, F, results) -> list[Command]:
        nxt = spec.done(self, L, F)
        if nxt is not None:
            self.ctx.active = None
            if nxt is not self.state:
                self.goto(nxt, now, Reason.OK)
            return []
        active = self.ctx.active
        if active is not None:
            res = results.get(active.command_id)
            timed_out = now - active.issued_at >= self.plan.retry.command_timeout_sec
            if res is None or not res.terminal:
                if not timed_out:
                    return []
                res = CommandResult(active.command_id, ResultStatus.EXPIRED, Reason.COMMAND_TIMEOUT.value)
            self.ctx.active = None
            if res.reason in {r.value for r in MANUAL_ONLY}:
                self.goto(PairState.MANUAL, now, Reason(res.reason), res.detail)
                return []
            if res.status is ResultStatus.UNCONFIRMED:
                # Issued, not verified. Wait for a fresh observation; do not spend a failure.
                self.ctx.confirm_until = now + spec.confirm_sec
                return []
            if res.succeeded:
                self.ctx.step_index += 1
                plan = spec.commands(self, L, F)
                if self.ctx.step_index < len(plan):
                    return self._issue_step(plan, now)
                self.ctx.confirm_until = now + spec.confirm_sec
                return []
            self.ctx.last_failure = res.reason or Reason.COMMAND_FAILED.value
            self.hold(spec.failure_reason, f"{res.reason} {res.detail}".strip())
            self.ctx.confirm_until = now + 2.0
            self.ctx.step_index = 0
            return []
        if now < self.ctx.confirm_until:
            return []
        if self.ctx.confirm_until:
            # Commands succeeded but the expected state never appeared.
            self.ctx.confirm_until = 0.0
            self.hold(spec.failure_reason, "result not observed")
        if self.ctx.stage_attempts >= spec.attempts:
            spec.on_exhausted(self, now)
            return []
        plan = spec.commands(self, L, F)
        if not plan:
            return []
        self.ctx.stage_attempts += 1
        self.ctx.step_index = 0
        return self._issue_step(plan, now)

    def _issue_step(self, plan, now) -> list[Command]:
        role, ctype, params = plan[self.ctx.step_index]
        return [self._command(role, ctype, params, now)]

    # ----- recovery ladder -----------------------------------------------------------
    def _enter_recovery(self, now, state: PairState, reason: Reason, detail: str) -> list[Command]:
        if self.state is state:
            return []
        if state is PairState.RECOVER_CS2 and not self.budget.try_consume("cs2", now):
            state = PairState.RECOVER_STEAM
        if state is PairState.RECOVER_STEAM and not self.budget.try_consume("steam", now):
            self.goto(PairState.PAUSED, now, Reason.BUDGET_EXHAUSTED, f"{reason.value}: {detail}")
            return []
        self.goto(state, now, reason, detail)
        return []

    def escalate_lobby(self, now: float, reason: Reason) -> None:
        self.ctx.lobby_formed = False
        if self.budget.try_consume("recreate", now):
            self.goto(PairState.LOBBY_RESET, now, Reason.LOBBY_RECREATE, reason.value)
        else:
            self._enter_recovery(now, PairState.RECOVER_CS2, Reason.BUDGET_EXHAUSTED, reason.value)

    def _recover(self, now, L, F, results) -> list[Command]:
        ctype = CommandType.RESTART_CS2 if self.state is PairState.RECOVER_CS2 else CommandType.RESTART_STEAM

        def ok(o: Observation) -> bool:
            return o.steam_running and o.cs2_running and o.screen in MENU_SCREENS

        if not self.ctx.recover_roles:
            # Restart only the broken client; escalation to Steam restarts whoever is still broken.
            broken = [r.value for r, o in ((Role.LEADER, L), (Role.FOLLOWER, F)) if not ok(o)]
            self.ctx.recover_roles = broken or [Role.LEADER.value, Role.FOLLOWER.value]
        plan = [(Role(r), ctype, {}) for r in self.ctx.recover_roles]
        healthy = ok(L) and ok(F)
        if healthy and self.ctx.step_index >= len(plan):
            self.goto(PairState.FRIENDSHIP, now, Reason.OK, "recovered")
            return []
        active = self.ctx.active
        if active is not None:
            res = results.get(active.command_id)
            if (res is None or not res.terminal) and now - active.issued_at < 180.0:
                return []
            self.ctx.active = None
            if res is not None and res.reason in {r.value for r in MANUAL_ONLY}:
                self.goto(PairState.MANUAL, now, Reason(res.reason), res.detail)
                return []
            self.ctx.step_index += 1
            self.ctx.confirm_until = now + 20.0
            return []
        if self.ctx.step_index < len(plan):
            return self._issue_step(plan, now)
        if now >= self.ctx.confirm_until:
            nxt = PairState.RECOVER_STEAM if self.state is PairState.RECOVER_CS2 else None
            if nxt is not None and self.budget.try_consume("steam", now):
                self.goto(nxt, now, Reason.CS2_NOT_RUNNING, "cs2 restart did not recover")
            else:
                self.goto(PairState.PAUSED, now, Reason.BUDGET_EXHAUSTED, "restart did not recover")
        return []


# ----- stage table -------------------------------------------------------------------

def _friend_cmds(m: PairMachine, L, F):
    return [(Role.LEADER, CommandType.SEND_FRIEND_REQUEST,
             {"steam_id64": m.pair.follower.steam_id64, "friend_code": m.pair.follower.friend_code}),
            (Role.FOLLOWER, CommandType.SEND_FRIEND_REQUEST,
             {"steam_id64": m.pair.leader.steam_id64, "friend_code": m.pair.leader.friend_code})]


def _friend_done(m: PairMachine, L, F):
    return PairState.LOBBY_RESET if m.friends(L, F) else None


def _friend_exhausted(m: PairMachine, now):
    m.goto(PairState.MANUAL, now, Reason.FRIENDSHIP_NOT_CONFIRMED,
           f"{m.pair.leader.agent_id} ↔ {m.pair.follower.agent_id}")


def _reset_cmds(m: PairMachine, L, F):
    cmds = []
    # An empty roster was not observed. It is not a party that must be left.
    if L.lobby.members and not m.solo(L, Role.LEADER):
        cmds.append((Role.LEADER, CommandType.LEAVE_LOBBY, {}))
    if F.lobby.members and not m.solo(F, Role.FOLLOWER):
        cmds.append((Role.FOLLOWER, CommandType.LEAVE_LOBBY, {}))
    return cmds


def _reset_done(m: PairMachine, L, F):
    if m.roster_ok(L, Role.LEADER) and m.roster_ok(F, Role.FOLLOWER) and m.ctx.lobby_formed:
        return PairState.LOBBY_VERIFY
    if m.solo(L, Role.LEADER) and m.solo(F, Role.FOLLOWER):
        return PairState.LOBBY_CONFIGURE
    return None


def _configure_cmds(m: PairMachine, L, F):
    return [(Role.LEADER, CommandType.CONFIGURE_LOBBY, {"mode": LOBBY_MODE, "map_id": MVP_MAP})]


def _configure_done(m: PairMachine, L, F):
    if not L.lobby.members:
        return None
    if not m.solo(L, Role.LEADER) and not m.roster_ok(L, Role.LEADER):
        return PairState.LOBBY_RESET
    return PairState.LOBBY_INVITE if m.configured(L) else None


def _invite_cmds(m: PairMachine, L, F):
    f = m.pair.follower
    return [(Role.LEADER, CommandType.INVITE,
             {"steam_id64": f.steam_id64, "display_name": f.display_name,
              "replace_stale": m.ctx.stage_attempts > 0 or m.budget.remaining("reinvite", 0) < m.plan.retry.reinvites})]


def _invite_done(m: PairMachine, L, F):
    if m.roster_ok(L, Role.LEADER) and m.roster_ok(F, Role.FOLLOWER):
        return PairState.LOBBY_VERIFY
    return PairState.LOBBY_ACCEPT if m.invite_seen(F) else None


def _accept_cmds(m: PairMachine, L, F):
    l = m.pair.leader
    return [(Role.FOLLOWER, CommandType.ACCEPT_INVITE,
             {"steam_id64": l.steam_id64, "display_name": l.display_name})]


def _accept_done(m: PairMachine, L, F):
    if m.roster_ok(L, Role.LEADER) and m.roster_ok(F, Role.FOLLOWER):
        return PairState.LOBBY_VERIFY
    return None


def _accept_exhausted(m: PairMachine, now):
    if m.budget.try_consume("reinvite", now):
        m.goto(PairState.LOBBY_INVITE, now, Reason.INVITE_NOT_ACCEPTED, "reinvite")
    else:
        m.escalate_lobby(now, Reason.INVITE_NOT_ACCEPTED)


STAGES: dict[PairState, Stage] = {
    PairState.FRIENDSHIP: Stage(_friend_cmds, _friend_done, _friend_exhausted,
                                Reason.FRIENDSHIP_NOT_CONFIRMED, attempts=2, confirm_sec=FRIEND_CONFIRM_SEC),
    PairState.LOBBY_RESET: Stage(_reset_cmds, _reset_done, lambda m, now: m._enter_recovery(
        now, PairState.RECOVER_CS2, Reason.LOBBY_WRONG_ROSTER, "leave lobby failed"),
        Reason.LOBBY_WRONG_ROSTER),
    PairState.LOBBY_CONFIGURE: Stage(_configure_cmds, _configure_done,
                                     lambda m, now: m.escalate_lobby(now, Reason.LOBBY_NOT_CONFIGURED),
                                     Reason.LOBBY_NOT_CONFIGURED),
    PairState.LOBBY_INVITE: Stage(_invite_cmds, _invite_done,
                                  lambda m, now: m.escalate_lobby(now, Reason.INVITE_NOT_RECEIVED),
                                  Reason.INVITE_NOT_RECEIVED, confirm_sec=10.0),
    PairState.LOBBY_ACCEPT: Stage(_accept_cmds, _accept_done, _accept_exhausted,
                                  Reason.INVITE_NOT_ACCEPTED, confirm_sec=10.0),
}
