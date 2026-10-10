"""Coordinator: links, observations, durable command outbox and FSM ticking.

Thread-safe; the HTTP server calls `handle_heartbeat`, a background loop calls
`tick`. Time is wall clock so persisted timers survive a coordinator restart.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from core.wingman_fleet import PROTOCOL_VERSION
from core.wingman_fleet.models import (
    ASSIGNMENT_COMMANDS, Command, CommandResult, CommandType, Link, Observation, RunPlan, to_dict,
)
from core.wingman_fleet.pair_fsm import HALTED, PairCtx, PairMachine
from core.wingman_fleet.reasons import describe
from core.wingman_fleet.run_fsm import RunCtx, RunMachine, RunState
from core.wingman_fleet.store import FleetStore

SUSPECT_AFTER_SEC = 1.5
OFFLINE_AFTER_SEC = 3.0
GAMEPLAY_TTL_SEC = 1.5
RESULT_WINDOW_SEC = 3600.0
OPERATOR_COMMANDS = frozenset({CommandType.RESTART_CS2, CommandType.RESTART_STEAM,
                               CommandType.SCREENSHOT, CommandType.SAFE_STOP})
# Safety and operator commands are delivered until they expire by deadline.
ALWAYS_DELIVER = {CommandType.SAFE_STOP.value, CommandType.STOP_GAMEPLAY.value,
                  CommandType.SCREENSHOT.value}


@dataclass
class AgentLinkState:
    agent_id: str
    computer: str = ""
    last_seen: float = 0.0
    observation: Observation | None = None
    received_at: float = 0.0
    protocol: int = 0
    boot_id: str = ""


class Coordinator:
    def __init__(self, store: FleetStore, *, token: str, clock: Callable[[], float] = time.time,
                 log: Callable[[str], None] | None = None):
        if len(token) < 24:
            raise ValueError("fleet token must contain at least 24 characters")
        self.store, self.token, self.clock = store, token, clock
        self.log = log or (lambda _msg: None)
        self.lock = threading.RLock()
        self.agents: dict[str, AgentLinkState] = {}
        self.plan: RunPlan | None = None
        self.pairs: dict[str, PairMachine] = {}
        self.run: RunMachine | None = None
        self._saved_state = ""
        self.operator_ids: set[str] = set()
        self._resume()

    # ----- lifecycle -----------------------------------------------------------------
    def _resume(self) -> None:
        active = self.store.active_run()
        if active is None:
            return
        plan, state = active
        self._install(plan, state)
        self.log(f"fleet: resumed run {plan.run_id} in {self.run.state.value}")

    def _install(self, plan: RunPlan, state: dict[str, Any] | None) -> None:
        state = state or {}
        self.plan = plan
        self.pairs = {}
        for p in plan.pairs:
            ctx = PairCtx.from_dict(state["pairs"][p.pair_id]) if p.pair_id in state.get("pairs", {}) else None
            m = PairMachine(plan, p, ctx, on_transition=self._transition)
            m.known_friends = self.store.friendship_known(p.leader.steam_id64, p.follower.steam_id64)
            self.pairs[p.pair_id] = m
        run_ctx = RunCtx.from_dict(state["run"]) if "run" in state else None
        self.run = RunMachine(plan, self.pairs, run_ctx, on_transition=self._transition)
        for agent_id in self.store.operator_stopped_agents(plan.run_id):
            self.run.note_operator_stop(agent_id)

    def start_run(self, plan: RunPlan) -> None:
        with self.lock:
            if self.run is not None and self.run.state not in (RunState.STOPPED, RunState.IDLE):
                raise RuntimeError(f"run {self.plan.run_id} is still {self.run.state.value}")
            self.store.save_run(plan)
            self._install(plan, None)
            self.store.event("run_started", run_id=plan.run_id, detail=plan.to_json())
            self.run.start(self.clock())
            self._persist(force=True)

    def stop_run(self) -> None:
        with self.lock:
            if self.run is not None:
                self.run.stop(self.clock())
                self._persist(force=True)

    def _transition(self, *, pair_id: str, before: str, after: str, reason: str, detail: str) -> None:
        run_id = self.plan.run_id if self.plan else ""
        self.store.event("transition", run_id=run_id, pair_id=pair_id, before=before, after=after,
                         reason=reason, detail=detail)
        who = pair_id or "run"
        self.log(f"fleet[{who}]: {before} → {after} — {describe(reason, detail)}")

    def _persist(self, force: bool = False) -> None:
        if self.plan is None or self.run is None:
            return
        state = {"pairs": {pid: m.snapshot() for pid, m in self.pairs.items()}, "run": self.run.snapshot()}
        raw = json.dumps(state, sort_keys=True, ensure_ascii=False)
        if force or raw != self._saved_state:
            self.store.save_state(self.plan.run_id, state)
            self._saved_state = raw
        if self.run.state is RunState.STOPPED:
            self.store.deactivate_run(self.plan.run_id)

    # ----- operator ------------------------------------------------------------------
    def pair_action(self, pair_id: str, action: str) -> None:
        with self.lock:
            m = self.pairs[pair_id]
            now = self.clock()
            {"pause": m.pause, "resume": m.resume, "retry": m.retry_stage,
             "recreate": m.force_recreate}[action](now)
            if action == "resume" and self.run is not None and self.run.state is RunState.PAUSED:
                self.run.start(now)
            self.store.event("operator", run_id=self.plan.run_id, pair_id=pair_id, detail=action)
            self._persist(force=True)

    def agent_command(self, agent_id: str, ctype: CommandType, *, request_key: str = "") -> Command:
        """Operator-issued command. SAFE_STOP is durable before this method returns."""
        with self.lock:
            if ctype not in OPERATOR_COMMANDS:
                raise ValueError(f"{ctype.value} is not an operator command")
            if self.plan is None or agent_id not in self.plan.agent_ids:
                raise ValueError(f"{agent_id} is not part of the active run")
            if (ctype in (CommandType.RESTART_CS2, CommandType.RESTART_STEAM) and self.run
                    and self.run.state is RunState.IN_MATCH):
                raise RuntimeError("перезапуск во время матча запрещён — сначала безопасная остановка")
            now = self.clock()
            key = request_key or uuid.uuid4().hex
            cmd = Command(
                f"{self.plan.run_id}/operator/{uuid.uuid4().hex}/{agent_id}/{ctype.value}",
                self.plan.run_id, agent_id, ctype, {}, "", 1, 240.0, now,
            )
            # Durable write first. A failed transaction leaves memory and the caller unchanged.
            stored = self.store.accept_operator_command(
                cmd, key, latch_stop=ctype is CommandType.SAFE_STOP and self.run is not None,
            )
            if ctype is CommandType.SAFE_STOP and self.run is not None:
                self.run.note_operator_stop(agent_id)
            self.operator_ids.add(stored.command_id)
            if stored.command_id == cmd.command_id:
                self.store.event("operator", run_id=self.plan.run_id, agent_id=agent_id, detail=ctype.value)
            return stored

    # ----- network -------------------------------------------------------------------
    def links(self, now: float | None = None) -> dict[str, Link]:
        now = self.clock() if now is None else now
        out = {}
        for agent_id, st in self.agents.items():
            age = now - st.last_seen
            out[agent_id] = (Link.HEALTHY if age <= SUSPECT_AFTER_SEC
                             else Link.SUSPECT if age <= OFFLINE_AFTER_SEC else Link.OFFLINE)
        return out

    def observations(self, now: float) -> dict[str, Observation]:
        return {a: st.observation.aged(now - st.received_at)
                for a, st in self.agents.items() if st.observation is not None}

    def handle_heartbeat(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        import hmac
        token = payload.get("token")
        if not isinstance(token, str) or not hmac.compare_digest(token, self.token):
            return 403, {"ok": False, "error": "unauthorized"}
        try:
            obs = Observation.from_dict(payload["observation"])
            results = [CommandResult.from_dict(r) for r in payload.get("results") or ()]
        except (KeyError, TypeError, ValueError) as exc:
            return 400, {"ok": False, "error": f"bad payload: {exc}"}
        agent_id = obs.agent_id
        book = getattr(self, "assignments", None)
        if book is not None and book.has_credential(agent_id):
            if not book.authenticate(agent_id, str(payload.get("agent_token") or "")):
                return 403, {"ok": False, "error": "unauthorized"}
        with self.lock:
            now = self.clock()
            st = self.agents.setdefault(agent_id, AgentLinkState(agent_id))
            boot_id = str(payload.get("boot_id", ""))
            if (st.observation is not None and obs.sequence <= st.observation.sequence
                    and boot_id == st.boot_id):
                return 409, {"ok": False, "error": "out-of-order heartbeat"}
            st.boot_id = boot_id
            st.computer = str(payload.get("computer", ""))
            st.protocol = obs.protocol
            st.last_seen, st.observation, st.received_at = now, obs, now
            active_run = self.plan.run_id if self.plan else ""
            catalog = payload.get("catalog")
            if book is not None and isinstance(catalog, dict):
                book.remember_catalog(agent_id, catalog)
            accepted: list[str] = []
            for r in results:
                result_run = self._result_run(r, agent_id, active_run)
                stored = self.store.record_result(r, agent_id=agent_id, run_id=result_run)
                if stored and r.terminal and not r.succeeded:
                    self.store.event("command_result", run_id=result_run,
                                     agent_id=agent_id, reason=r.reason, detail=f"{r.command_id}: {r.detail}",
                                     data=r.evidence or None)
                if stored:
                    self._fold_assignment_result(r, agent_id)
                if stored or self.store.result_is_stored(r, agent_id=agent_id, run_id=result_run):
                    accepted.append(r.command_id)
            if obs.protocol != PROTOCOL_VERSION:
                return 200, {"ok": False, "error": "protocol_mismatch", "server_time": now,
                             "protocol": PROTOCOL_VERSION, "commands": [], "gameplay": None,
                             "accepted_results": accepted}
            commands, gameplay, run_id = [], None, ""
            if self.plan is not None and agent_id in self.plan.agent_ids:
                run_id = self.plan.run_id
                commands = [to_dict(c) for c in self._commands_for(agent_id, run_id)]
                attempt = self.run.gameplay_admitted(agent_id, self.links(now)) if self.run else ""
                if attempt:
                    gameplay = {"attempt_id": attempt, "ttl_sec": GAMEPLAY_TTL_SEC}
            if not commands:
                commands = [to_dict(c) for c in self.store.pending_assignments(agent_id)]
            return 200, {"ok": True, "server_time": now, "run_id": run_id, "commands": commands,
                         "gameplay": gameplay, "protocol": PROTOCOL_VERSION,
                         "accepted_results": accepted}

    def _fold_assignment_result(self, result: CommandResult, agent_id: str) -> None:
        book = getattr(self, "assignments", None)
        if book is None:
            return
        row = self.store.command_owner(result.command_id)
        if row is None or row[0] != agent_id or row[2] not in {item.value for item in ASSIGNMENT_COMMANDS}:
            return
        raw = self.store.db.execute(
            "SELECT command_json FROM commands WHERE command_id=?", (result.command_id,)
        ).fetchone()
        if raw is None:
            return
        cmd = Command.from_dict(json.loads(raw[0]))
        preparation_id = str(cmd.params.get("preparation_id") or cmd.run_id)
        try:
            if cmd.type is CommandType.PREPARE_ASSIGNMENT:
                book.note_prepare(preparation_id, agent_id, ok=result.succeeded, detail=result.detail)
            elif cmd.type is CommandType.COMMIT_ASSIGNMENT:
                book.note_commit(
                    preparation_id, agent_id, ok=result.succeeded,
                    generation=int(cmd.params.get("generation") or 0), detail=result.detail,
                )
            elif cmd.type is CommandType.RELEASE_ASSIGNMENT:
                book.note_release(preparation_id, agent_id, ok=result.succeeded, detail=result.detail)
            elif cmd.type is CommandType.VERIFY_ASSIGNMENT:
                book.note_identity(
                    preparation_id, agent_id, str(cmd.params.get("observed_steam_id64") or ""),
                    now=self.clock(), fresh=result.succeeded and result.evidence.get("status") == "verified",
                )
        except Exception as exc:
            self.store.event("assignment", run_id=preparation_id, agent_id=agent_id, detail=str(exc)[:240])

    def _result_run(self, result: CommandResult, agent_id: str, active_run: str) -> str:
        row = self.store.command_owner(result.command_id)
        if row is not None and row[0] == agent_id and row[2] in {item.value for item in ASSIGNMENT_COMMANDS}:
            return str(row[1])
        return active_run

    def _commands_for(self, agent_id: str, run_id: str) -> list[Command]:
        gameplay = self.store.pending_for(agent_id, run_id)
        seen = {cmd.command_id for cmd in gameplay}
        extra = [cmd for cmd in self.store.pending_assignments(agent_id) if cmd.command_id not in seen]
        return gameplay + extra

    # ----- FSM tick ------------------------------------------------------------------
    def tick(self) -> list[Command]:
        with self.lock:
            if self.plan is None or self.run is None:
                return []
            now = self.clock()
            links = self.links(now)
            obs = self.observations(now)
            results = self.store.results(self.plan.run_id, since=now - RESULT_WINDOW_SEC)
            issued: list[Command] = []
            for m in self.pairs.values():
                issued += m.step(now, obs, links, results)
                self._remember_friendship(m, obs)
            issued += self.run.step(now, obs, links, results, now)
            added = self.store.add_commands(issued)
            for c in added:
                self.store.event("command", run_id=self.plan.run_id, pair_id=c.pair_id, agent_id=c.agent_id,
                                 detail=f"{c.type.value} {c.command_id}", data=c.params or None)
            wanted = {c.command_id for c in issued}
            wanted |= {m.ctx.active.command_id for m in self.pairs.values() if m.ctx.active}
            wanted |= set(self.run.ctx.issued.values()) | self.operator_ids
            self.store.supersede(self.plan.run_id, wanted, ALWAYS_DELIVER)
            self.store.expire_pending(self.plan.run_id, now, now - 2 * self.plan.retry.command_timeout_sec)
            self._persist()
            return added

    def _remember_friendship(self, m: PairMachine, obs: dict[str, Observation]) -> None:
        if m.known_friends:
            return
        L, F = obs.get(m.pair.leader.agent_id), obs.get(m.pair.follower.agent_id)
        if L is not None and F is not None and m.friends(L, F):
            self.store.confirm_friendship(m.pair.leader.steam_id64, m.pair.follower.steam_id64)
            m.known_friends = True

    # ----- panel view ----------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        with self.lock:
            now = self.clock()
            links = self.links(now)
            out: dict[str, Any] = {"run_id": self.plan.run_id if self.plan else "",
                                   "run_state": self.run.state.value if self.run else "idle",
                                   "run_reason": describe(self.run.ctx.reason, self.run.ctx.detail)
                                   if self.run and self.run.ctx.reason else "",
                                   "cycles": self.run.ctx.cycles if self.run else 0,
                                   "failed_cycles": self.run.ctx.failed_cycles if self.run else 0,
                                   "wave": self.run.ctx.wave if self.run else 0,
                                   "pairs": [], "agents": {}}
            for agent_id, st in sorted(self.agents.items()):
                o = st.observation
                out["agents"][agent_id] = {
                    "computer": st.computer, "link": links[agent_id].value,
                    "seen_ago": round(now - st.last_seen, 1),
                    "steam_id64": o.steam_id64 if o else "", "identity": o.identity.value if o else "",
                    "screen": o.screen.value if o else "", "lobby": list(o.lobby.members) if o else [],
                    "gsi_age": round(o.gsi.age_sec, 1) if o and o.gsi.age_sec != float("inf") else None,
                    "input_owner": o.input_owner if o else "", "worker": o.worker_running if o else False,
                    "preflight": "ok" if o and o.preflight_ok else ", ".join(o.preflight_failures) if o else "",
                    "active_command": o.active_command if o else "",
                }
            if self.plan:
                for p in self.plan.pairs:
                    m = self.pairs[p.pair_id]
                    out["pairs"].append({
                        "pair_id": p.pair_id, "state": m.state.value,
                        "reason": describe(m.ctx.reason, m.ctx.detail),
                        "halted": m.state in HALTED, "attempt": m.ctx.stage_attempts,
                        "leader": {"agent_id": p.leader.agent_id, "name": p.leader.display_name},
                        "follower": {"agent_id": p.follower.agent_id, "name": p.follower.display_name},
                    })
                out["events"] = self.store.events(self.plan.run_id, 40)
                out["commands"] = self.store.command_rows(self.plan.run_id, 30)
            return out
