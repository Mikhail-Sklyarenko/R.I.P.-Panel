"""Run FSM: synchronized matchmaking of both pairs into one shared Inferno match.

Gameplay leases exist only in IN_MATCH after all four clients proved the same
server. A pair-level confirm that appears for only one pair is a different match:
it is never accepted, the other pair cancels, and a new bounded search wave starts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from core.wingman_fleet import MVP_MAP, MVP_MODE
from core.wingman_fleet.budget import Budget
from core.wingman_fleet.match_proof import Verdict, judge
from core.wingman_fleet.models import (
    MENU_SCREENS, Command, CommandResult, CommandType, Identity, Link, MatchFingerprint,
    Observation, RunPlan, Screen,
)
from core.wingman_fleet.pair_fsm import PairMachine, PairState
from core.wingman_fleet.reasons import Reason

FOUND_SCREENS = frozenset({Screen.MATCH_CONFIRM, Screen.LOADING, Screen.IN_MATCH})
PROBE_INTERVAL_SEC = 8.0
SEARCH_STABLE_SEC = 1.0
MAX_RECONNECTS = 3
FINISH_GRACE_SEC = 30.0
REPLAY_INTERVAL_SEC = 10.0


class RunState(str, Enum):
    IDLE = "idle"
    PREPARING = "preparing"
    SEARCH_ARMED = "search_armed"
    SEARCHING = "searching"
    CONFIRMING = "confirming"
    LOADING = "loading"
    VERIFYING = "verifying"
    IN_MATCH = "in_match"
    LEAVING = "leaving"
    ABORTING_SEARCH = "aborting_search"
    POST_MATCH = "post_match"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"


MATCH_PHASES = frozenset({RunState.SEARCH_ARMED, RunState.SEARCHING, RunState.CONFIRMING,
                          RunState.LOADING, RunState.VERIFYING, RunState.IN_MATCH,
                          RunState.LEAVING, RunState.ABORTING_SEARCH, RunState.POST_MATCH})
FAILED_WAVE = frozenset({RunState.LEAVING, RunState.ABORTING_SEARCH})


@dataclass
class RunCtx:
    state: RunState = RunState.IDLE
    entered_at: float = 0.0
    reason: str = ""
    detail: str = ""
    seq: int = 0
    wave: int = 0
    cycles: int = 0
    attempt_id: str = ""
    found_at: dict[str, float] = field(default_factory=dict)
    accepted: bool = False
    last_probe: float = 0.0
    verdict: str = ""
    seen_in_match: list[str] = field(default_factory=list)
    issued: dict[str, str] = field(default_factory=dict)  # agent -> command id for this phase
    last_issue: float = 0.0
    finished_at: float = 0.0
    reconnects: dict[str, int] = field(default_factory=dict)
    reconnect_at: dict[str, float] = field(default_factory=dict)
    play_at: dict[str, float] = field(default_factory=dict)
    recreate_after: bool = False
    budget_state: dict[str, list[float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["state"] = self.state.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RunCtx":
        ctx = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        ctx.state = RunState(ctx.state)
        return ctx


class RunMachine:
    def __init__(self, plan: RunPlan, pairs: dict[str, PairMachine], ctx: RunCtx | None = None,
                 on_transition: Callable[..., None] | None = None):
        self.plan, self.pairs = plan, pairs
        self.ctx = ctx or RunCtx()
        self.budget = Budget({"waves": (plan.retry.failed_waves_per_hour, 3600.0)})
        self.budget.load_state(self.ctx.budget_state)
        self.on_transition = on_transition or (lambda **_: None)

    @property
    def state(self) -> RunState:
        return self.ctx.state

    def snapshot(self) -> dict[str, Any]:
        self.ctx.budget_state = self.budget.to_state()
        return self.ctx.to_dict()

    def goto(self, state: RunState, now: float, reason: Reason | str = Reason.OK, detail: str = "") -> None:
        before = self.ctx.state
        reason = Reason(reason)
        if before == state and self.ctx.reason == reason.value and self.ctx.detail == detail:
            return
        if before != state:
            self.ctx.entered_at = now
            self.ctx.issued = {}
            if state in FAILED_WAVE and before not in FAILED_WAVE:
                self.budget.try_consume("waves", now)
        self.ctx.state, self.ctx.reason, self.ctx.detail = state, reason.value, detail
        self.on_transition(pair_id="", before=before.value, after=state.value,
                           reason=reason.value, detail=detail)

    # ----- operator ------------------------------------------------------------------
    def start(self, now: float) -> None:
        if self.state in (RunState.IDLE, RunState.PAUSED, RunState.STOPPED):
            if self.state is RunState.PAUSED:
                self.budget.reset()
            self.goto(RunState.PREPARING, now, Reason.OK)

    def stop(self, now: float) -> None:
        if self.state not in (RunState.STOPPED, RunState.STOPPING):
            self.goto(RunState.STOPPING, now, Reason.OPERATOR_STOP)

    def gameplay_admitted(self, agent_id: str, links: dict[str, Link]) -> str:
        """Match attempt id the agent may play in, or empty: the lease is derived each heartbeat."""
        if self.state is not RunState.IN_MATCH or links.get(agent_id) is not Link.HEALTHY:
            return ""
        return self.ctx.attempt_id

    # ----- helpers -------------------------------------------------------------------
    @property
    def agents(self) -> tuple[str, ...]:
        return self.plan.agent_ids

    @property
    def leaders(self) -> tuple[str, ...]:
        return tuple(p.leader.agent_id for p in self.plan.pairs)

    def _cmd(self, agent: str, ctype: CommandType, params: dict, now: float, deadline: float = 0) -> Command:
        self.ctx.seq += 1
        cid = f"{self.plan.run_id}/run/w{self.ctx.wave}/{self.ctx.state.value}/{self.ctx.seq}/{agent}"
        self.ctx.issued[agent] = cid
        return Command(cid, self.plan.run_id, agent, ctype, params, "",
                       1, deadline or self.plan.retry.command_timeout_sec, now)

    def _once(self, agents, ctype, now, params=None) -> list[Command]:
        return [self._cmd(a, ctype, dict(params or {}), now) for a in agents if a not in self.ctx.issued]

    def _release_pairs(self, now: float, *, recreate: bool, reason: Reason = Reason.OK) -> None:
        for m in self.pairs.values():
            m.release_from_match(now, recreate=recreate, reason=reason)

    def _expected_names(self) -> dict[str, str]:
        return {a.agent_id: a.display_name for p in self.plan.pairs for a in (p.leader, p.follower)}

    def _pair_found(self, obs: dict[str, Observation]) -> dict[str, bool]:
        return {p.pair_id: any(obs[a].screen in FOUND_SCREENS for a in p.agents if a in obs)
                for p in self.plan.pairs}

    def _in_correct_match(self, o: Observation) -> bool:
        return (o.gsi.fresh and o.gsi.map_id == MVP_MAP and o.gsi.mode == MVP_MODE
                and o.gsi.steam_id64 == o.steam_id64)

    # ----- main step -----------------------------------------------------------------
    def step(self, now: float, obs: dict[str, Observation], links: dict[str, Link],
             results: dict[str, CommandResult], now_wall: float) -> list[Command]:
        s = self.state
        if s in (RunState.IDLE, RunState.STOPPED, RunState.PAUSED):
            return []
        if s is RunState.STOPPING:
            return self._stopping(now, obs, links, results)
        for agent in self.agents:
            o = obs.get(agent)
            if o is not None and (o.identity is Identity.MISMATCH or o.cooldown or o.update_required):
                reason = (Reason.ACCOUNT_MISMATCH if o.identity is Identity.MISMATCH
                          else Reason.COOLDOWN if o.cooldown else Reason.CS2_UPDATE_REQUIRED)
                return self._halt(now, reason, agent)
        if s is RunState.PREPARING:
            return self._preparing(now, now_wall)
        if s not in (RunState.IN_MATCH, RunState.POST_MATCH, RunState.LEAVING, RunState.ABORTING_SEARCH):
            # Matchmaking steps need every client; a lost one aborts this wave safely.
            lost = [a for a in self.agents if links.get(a) is not Link.HEALTHY or a not in obs]
            if lost:
                return self._abort_wave(now, obs, Reason.AGENT_OFFLINE, ",".join(lost))
            down = [a for a in self.agents if not (obs[a].steam_running and obs[a].cs2_running)]
            if down:
                return self._abort_wave(now, obs, Reason.CS2_NOT_RUNNING, ",".join(down))
        handler = getattr(self, f"_{s.value}")
        return handler(now, obs, links, results)

    def _halt(self, now: float, reason: Reason, detail: str) -> list[Command]:
        cmds = [self._cmd(a, CommandType.STOP_GAMEPLAY, {}, now) for a in self.agents]
        for m in self.pairs.values():
            if m.state is PairState.MATCH:
                m.goto(PairState.MANUAL if reason is Reason.ACCOUNT_MISMATCH else PairState.PAUSED, now,
                       reason, detail)
        self.goto(RunState.PAUSED, now, reason, detail)
        return cmds

    def _preparing(self, now: float, now_wall: float) -> list[Command]:
        if self.plan.retry.max_cycles and self.ctx.cycles >= self.plan.retry.max_cycles:
            self.goto(RunState.STOPPED, now, Reason.OK, f"{self.ctx.cycles} cycles complete")
            return []
        if not all(m.state is PairState.READY for m in self.pairs.values()):
            return []
        if self.budget.remaining("waves", now) <= 0:
            self.goto(RunState.PAUSED, now, Reason.MISMATCH_LIMIT,
                      f"{self.plan.retry.failed_waves_per_hour} failed search waves in the last hour")
            return []
        self.ctx.wave += 1
        self.ctx.attempt_id = f"{self.plan.run_id}/w{self.ctx.wave}"
        self.ctx.found_at, self.ctx.accepted, self.ctx.verdict = {}, False, ""
        self.ctx.seen_in_match, self.ctx.recreate_after = [], False
        self.ctx.finished_at, self.ctx.reconnects, self.ctx.reconnect_at = 0.0, {}, {}
        self.ctx.play_at = {}
        for m in self.pairs.values():
            m.lock_for_match(now)
        self.goto(RunState.SEARCH_ARMED, now, Reason.OK, self.ctx.attempt_id)
        start_at = now_wall + self.plan.retry.search_start_lead_sec
        return [self._cmd(a, CommandType.START_SEARCH,
                          {"start_at_coordinator": start_at, "attempt_id": self.ctx.attempt_id}, now)
                for a in self.leaders]

    def _search_armed(self, now, obs, links, results) -> list[Command]:
        for cid in self.ctx.issued.values():
            res = results.get(cid)
            if res is not None and res.terminal and not res.succeeded:
                return self._abort_wave(now, obs, Reason.SEARCH_NOT_STARTED, res.reason)
        if any(obs[a].screen in FOUND_SCREENS for a in self.agents):
            self.goto(RunState.SEARCHING, now, Reason.OK)
            return []
        if all(obs[a].screen is Screen.SEARCHING and obs[a].screen_stable_sec >= SEARCH_STABLE_SEC
               for a in self.agents):
            self.goto(RunState.SEARCHING, now, Reason.OK)
            return []
        if now - self.ctx.entered_at > self.plan.retry.command_timeout_sec:
            searching = [a for a in self.agents if obs[a].screen is Screen.SEARCHING]
            return self._abort_wave(now, obs, Reason.SEARCH_DESYNC, f"searching: {searching}")
        return []

    def _searching(self, now, obs, links, results) -> list[Command]:
        found = self._pair_found(obs)
        if any(found.values()):
            for pid, f in found.items():
                if f:
                    self.ctx.found_at.setdefault(pid, now)
            self.goto(RunState.CONFIRMING, now, Reason.OK)
            return self._confirming(now, obs, links, results)
        stopped = [a for a in self.agents if obs[a].screen in MENU_SCREENS]
        if stopped:
            return self._abort_wave(now, obs, Reason.SEARCH_CANCELLED, ",".join(stopped))
        if any(obs[a].screen is not Screen.SEARCHING for a in self.agents):
            return []  # transient unknown frame; never act on it
        if now - self.ctx.entered_at > self.plan.retry.search_timeout_sec:
            return self._abort_wave(now, obs, Reason.SEARCH_CANCELLED, "search timeout")
        return []

    def _confirming(self, now, obs, links, results) -> list[Command]:
        found = self._pair_found(obs)
        for pid, f in found.items():
            if f:
                self.ctx.found_at.setdefault(pid, now)
        window = self.plan.retry.search_confirm_window_sec
        if len(self.ctx.found_at) == len(self.plan.pairs):
            times = sorted(self.ctx.found_at.values())
            if times[-1] - times[0] <= window:
                self.goto(RunState.LOADING, now, Reason.OK, "both pairs found a match together")
                confirm = [a for a in self.agents if obs[a].screen is Screen.MATCH_CONFIRM]
                self.ctx.accepted = True
                return [self._cmd(a, CommandType.ACCEPT_MATCH, {"attempt_id": self.ctx.attempt_id}, now)
                        for a in confirm]
            return self._abort_wave(now, obs, Reason.CONFIRM_DESYNC, "found apart")
        first = min(self.ctx.found_at.values())
        if now - first > window:
            # One pair alone found a match: it is a different match. Never accept it.
            return self._abort_wave(now, obs, Reason.CONFIRM_DESYNC,
                                    f"only {sorted(self.ctx.found_at)} found a match")
        return []

    def _loading(self, now, obs, links, results) -> list[Command]:
        extra = [a for a in self.agents if obs[a].screen is Screen.MATCH_CONFIRM
                 and a not in self.ctx.issued]
        cmds = [self._cmd(a, CommandType.ACCEPT_MATCH, {"attempt_id": self.ctx.attempt_id}, now)
                for a in extra]
        if all(self._in_correct_match(obs[a]) for a in self.agents):
            self.goto(RunState.VERIFYING, now, Reason.OK)
            self.ctx.last_probe = 0.0
            return cmds + self._verifying(now, obs, links, results)
        in_match = [a for a in self.agents if obs[a].screen in (Screen.LOADING, Screen.IN_MATCH)]
        back = [a for a in self.agents if obs[a].screen in MENU_SCREENS | {Screen.SEARCHING}]
        if back and now - self.ctx.entered_at > 20.0:
            # Someone failed to accept/connect: the match did not form for all four.
            self.ctx.recreate_after = True
            self.goto(RunState.LEAVING, now, Reason.PLAYER_NOT_CONNECTED, ",".join(back))
            return cmds
        if now - self.ctx.entered_at > self.plan.retry.match_load_timeout_sec:
            self.ctx.recreate_after = True
            self.goto(RunState.LEAVING, now, Reason.MATCH_LOAD_TIMEOUT, f"in match: {in_match}")
        return cmds

    def _verifying(self, now, obs, links, results) -> list[Command]:
        fingerprints: dict[str, MatchFingerprint | None] = {a: obs[a].fingerprint for a in self.agents}
        verdict, why = judge(fingerprints, self._expected_names())
        if verdict is not Verdict.INSUFFICIENT or self.ctx.verdict != verdict.value:
            self.ctx.verdict = verdict.value
        if verdict is Verdict.SAME:
            self.goto(RunState.IN_MATCH, now, Reason.OK, why)
            self.ctx.seen_in_match = list(self.agents)
            self.ctx.play_at = {a: now for a in self.agents}
            return [self._cmd(a, CommandType.START_GAMEPLAY,
                              {"attempt_id": self.ctx.attempt_id, "map_id": MVP_MAP}, now)
                    for a in self.agents]
        if verdict is Verdict.DIFFERENT:
            self.ctx.recreate_after = True
            self.goto(RunState.LEAVING, now, Reason.MATCH_MISMATCH, why)
            return []
        if now - self.ctx.entered_at > self.plan.retry.match_proof_timeout_sec:
            # Without proof the match may still be shared; never play blind, never leave blind.
            return self._halt(now, Reason.MATCH_PROOF_UNAVAILABLE, why)
        if now - self.ctx.last_probe >= PROBE_INTERVAL_SEC:
            self.ctx.last_probe = now
            self.ctx.issued = {}
            return self._once(self.agents, CommandType.PROBE_MATCH, now, {"attempt_id": self.ctx.attempt_id})
        return []

    def _in_match(self, now, obs, links, results) -> list[Command]:
        cmds: list[Command] = []
        finished = []
        for a in self.agents:
            o = obs.get(a)
            if o is None:
                continue
            if (o.gsi.map_phase == "gameover" or o.worker_exit == "match_finished"
                    or o.screen is Screen.MATCH_RESULT):
                finished.append(a)
            elif links.get(a) is Link.HEALTHY and (o.screen in MENU_SCREENS or not o.cs2_running):
                # Client dropped out mid-match (crash/kick): bounded restart + reconnect.
                last = self.ctx.reconnect_at.get(a, 0.0)
                tries = self.ctx.reconnects.get(a, 0)
                if tries < MAX_RECONNECTS and now - last >= self.plan.retry.reconnect_wait_sec / MAX_RECONNECTS:
                    self.ctx.reconnects[a] = tries + 1
                    self.ctx.reconnect_at[a] = now
                    ctype = CommandType.RECONNECT_MATCH if o.cs2_running else CommandType.RESTART_CS2
                    cmds.append(self._cmd(a, ctype, {"attempt_id": self.ctx.attempt_id}, now))
            elif (links.get(a) is Link.HEALTHY and o.screen is Screen.IN_MATCH and not o.worker_running
                  and self._in_correct_match(o) and now - self.ctx.play_at.get(a, 0.0) >= REPLAY_INTERVAL_SEC):
                # Lease came back after a link loss / reconnect: resume the worker for this attempt.
                self.ctx.play_at[a] = now
                cmds.append(self._cmd(a, CommandType.START_GAMEPLAY,
                                      {"attempt_id": self.ctx.attempt_id, "map_id": MVP_MAP}, now))
            if o.gsi.fresh and o.gsi.map_id and (o.gsi.map_id != MVP_MAP or o.gsi.mode != MVP_MODE):
                return cmds + self._halt(now, Reason.MATCH_MISMATCH, f"{a}: {o.gsi.mode}/{o.gsi.map_id}")
        if not finished:
            return cmds
        if not self.ctx.finished_at:
            self.ctx.finished_at = now
        # The game over is shared; give the remaining clients a short grace.
        if len(finished) == len(self.agents) or now - self.ctx.finished_at > FINISH_GRACE_SEC:
            self.goto(RunState.POST_MATCH, now, Reason.OK, f"match finished ({len(finished)}/4 confirmed)")
            return cmds + self._post_match(now, obs, links, results)
        return cmds

    def _post_match(self, now, obs, links, results) -> list[Command]:
        cmds = self._once(self.agents, CommandType.RETURN_TO_MENU, now)
        if all(a in obs and obs[a].screen in MENU_SCREENS and not obs[a].worker_running
               for a in self.agents):
            self.ctx.cycles += 1
            self._release_pairs(now, recreate=False)
            self.goto(RunState.PREPARING, now, Reason.OK, f"cycle {self.ctx.cycles} complete")
            return cmds
        if now - self.ctx.entered_at > self.plan.retry.post_match_timeout_sec:
            self._release_pairs(now, recreate=True, reason=Reason.COMMAND_TIMEOUT)
            self.ctx.cycles += 1
            self.goto(RunState.PREPARING, now, Reason.COMMAND_TIMEOUT, "post-match return slow")
        return cmds

    def _leaving(self, now, obs, links, results) -> list[Command]:
        # A client without CS2 is in no match; its pair recovers it after release.
        need = [a for a in self.agents if a in obs and obs[a].cs2_running
                and obs[a].screen not in MENU_SCREENS]
        cmds = []
        for a in need:
            ctype = (CommandType.CANCEL_SEARCH if obs[a].screen is Screen.SEARCHING
                     else CommandType.RETURN_TO_MENU if obs[a].screen is Screen.MATCH_RESULT
                     else CommandType.LEAVE_MATCH)
            if a not in self.ctx.issued:
                cmds.append(self._cmd(a, ctype, {}, now))
        if cmds:
            self.ctx.last_issue = now
        if not need:
            self._release_pairs(now, recreate=self.ctx.recreate_after, reason=Reason(self.ctx.reason))
            self.goto(RunState.PREPARING, now, Reason(self.ctx.reason), self.ctx.detail)
            return cmds
        if now - self.ctx.entered_at > self.plan.retry.post_match_timeout_sec:
            self._release_pairs(now, recreate=True, reason=Reason.COMMAND_TIMEOUT)
            self.goto(RunState.PREPARING, now, Reason.COMMAND_TIMEOUT, f"still not in menu: {need}")
        elif self.ctx.issued and now - self.ctx.last_issue > self.plan.retry.command_timeout_sec:
            self.ctx.issued = {}  # allow one more bounded attempt within the phase timeout
        return cmds

    def _aborting_search(self, now, obs, links, results) -> list[Command]:
        return self._leaving(now, obs, links, results)

    def _abort_wave(self, now, obs, reason: Reason, detail: str) -> list[Command]:
        self.ctx.recreate_after = reason in (Reason.MATCH_MISMATCH, Reason.CONFIRM_DESYNC,
                                             Reason.PLAYER_NOT_CONNECTED)
        self.goto(RunState.ABORTING_SEARCH, now, reason, detail)
        return self._leaving(now, obs, {}, {})

    def _stopping(self, now, obs, links, results) -> list[Command]:
        cmds = self._once(self.agents, CommandType.SAFE_STOP, now)
        done = all(
            links.get(a) is Link.OFFLINE
            or (a in self.ctx.issued and results.get(self.ctx.issued[a]) is not None
                and results[self.ctx.issued[a]].terminal)
            for a in self.agents)
        if done or now - self.ctx.entered_at > 20.0:
            for m in self.pairs.values():
                m.stop(now)
            self.goto(RunState.STOPPED, now, Reason.OPERATOR_STOP)
        return cmds
