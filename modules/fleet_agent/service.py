"""Agent service loop: heartbeat, exactly-once command execution, gameplay lease.

Safety rules enforced locally, independent of the coordinator:
* gameplay runs only while a lease from a recent heartbeat is valid (TTL);
* coordinator unreachable for OFFLINE_AFTER_SEC -> cancel automation, release inputs;
* SAFE_STOP / STOP_GAMEPLAY pre-empt whatever command is running.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import replace
from typing import Any, Callable

from core.wingman_fleet import PROTOCOL_VERSION
from core.wingman_fleet.models import (
    Command, CommandResult, CommandType, Observation, ResultStatus, Screen, to_dict,
)
from core.wingman_fleet.reasons import Reason
from modules.fleet_agent.backend import ExecContext, GameBackend
from modules.fleet_agent.journal import CommandJournal
from modules.fleet_agent.transport import Transport, TransportError

HEARTBEAT_SEC = 0.5
OFFLINE_AFTER_SEC = 3.0
URGENT = frozenset({CommandType.SAFE_STOP, CommandType.STOP_GAMEPLAY})


class _CommandCancel:
    """Cancel flag captured by one command. A later clear cannot revive it."""

    def __init__(self, source: threading.Event, epoch: int, service: "AgentService"):
        self._source = source
        self._epoch = epoch
        self._service = service
        self._stuck = False

    def is_set(self) -> bool:
        if (self._stuck or self._source.is_set() or self._service.epoch != self._epoch
                or self._service.session_stopped):
            self._stuck = True
        return self._stuck


class AgentService:
    def __init__(self, agent_id: str, backend: GameBackend, transport: Transport, journal: CommandJournal, *,
                 token: str, build_version: str, resource_manifest: str, computer: str = "", inline: bool = False,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time,
                 log: Callable[[str], None] | None = None):
        self.agent_id, self.backend, self.transport, self.journal = agent_id, backend, transport, journal
        self.token = token
        self.build_version, self.resource_manifest = build_version, resource_manifest
        self.computer = computer
        self.inline, self.clock, self.wall = inline, clock, wall
        self.log = log or (lambda _m: None)
        self.boot_id = uuid.uuid4().hex
        self.sequence = 0
        self.clock_offset = 0.0
        self.lease_attempt = ""
        self.lease_until = 0.0
        self.last_ok = clock()
        self.offline = False
        self.queue: deque[Command] = deque()
        self.current: Command | None = None
        self.cancel = threading.Event()
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self.last_error = ""
        self.run_id = ""
        self.epoch = 0
        self.session_stopped = False
        self._run_released = False
        self._shut_down = False
        self._draining = False

    # ----- clocks / lease ------------------------------------------------------------
    def coordinator_time(self) -> float:
        return self.wall() + self.clock_offset

    def _gameplay_blocked(self) -> bool:
        return self.session_stopped or self._stop.is_set()

    def _set_lease(self, gameplay: dict[str, Any] | None, now: float) -> None:
        with self._lock:
            if self._gameplay_blocked():
                self.lease_attempt, self.lease_until = "", 0.0
            elif gameplay and gameplay.get("attempt_id"):
                self.lease_attempt = str(gameplay["attempt_id"])
                self.lease_until = now + float(gameplay.get("ttl_sec", 1.5))
            else:
                self.lease_attempt, self.lease_until = "", 0.0
            grant = self.lease_attempt
        self._push_lease()
        with self._lock:
            # SAFE_STOP can land while set_gameplay is still applying the old attempt.
            blocked = self._gameplay_blocked() or self.lease_attempt != grant
            if blocked:
                self.lease_attempt, self.lease_until = "", 0.0
        if blocked and grant:
            self._push_lease()

    def enforce_lease(self) -> None:
        with self._lock:
            if self.lease_attempt and self.clock() > self.lease_until:
                self.log("agent: gameplay lease expired — revoking inputs")
                self.lease_attempt, self.lease_until = "", 0.0
            else:
                return
        self._push_lease()

    def _push_lease(self) -> None:
        try:
            self.backend.set_gameplay(self.lease_attempt)
        except Exception as exc:
            self.log(f"agent: set_gameplay failed: {exc!r}")
            self.backend.safe_stop("lease update failed")

    # ----- observation ---------------------------------------------------------------
    def observe(self) -> Observation:
        try:
            base = self.backend.observe()
        except Exception as exc:  # no evidence is never success
            self.last_error = f"observe failed: {exc!r}"
            base = Observation(self.agent_id, 0, screen=Screen.UNKNOWN)
        self.sequence += 1
        return replace(base, agent_id=self.agent_id, sequence=self.sequence, protocol=PROTOCOL_VERSION,
                       build_version=self.build_version, resource_manifest=self.resource_manifest,
                       active_command=self.current.command_id if self.current else "")

    # ----- heartbeat -----------------------------------------------------------------
    def tick(self) -> bool:
        now = self.clock()
        self.enforce_lease()
        obs = self.observe()
        results = self.journal.unacked()
        payload = {"boot_id": self.boot_id, "computer": self.computer, "token": self.token,
                   "observation": to_dict(obs), "results": [to_dict(r) for r in results]}
        t0 = self.wall()
        try:
            resp = self.transport.heartbeat(payload)
        except TransportError as exc:
            self._link_down(now, str(exc))
            return False
        t1 = self.wall()
        accepted = resp.get("accepted_results")
        if isinstance(accepted, list):
            sent = {r.command_id for r in results}
            self.journal.ack([str(cid) for cid in accepted if str(cid) in sent])
        if "server_time" in resp:
            self.clock_offset = float(resp["server_time"]) - (t0 + t1) / 2.0
        if not resp.get("ok"):
            self.last_error = str(resp.get("error"))
            self._link_down(now, self.last_error, hard=True)
            return False
        if self.offline:
            self.log("agent: coordinator link restored")
        self.offline, self.last_ok, self.last_error = False, now, ""
        self._rotate_run(str(resp.get("run_id", "")))
        if not self.session_stopped and self.run_id:
            self.cancel.clear()
        self._set_lease(resp.get("gameplay"), now)
        server_time = float(resp.get("server_time", self.wall()))
        for raw in resp.get("commands") or ():
            self._accept(Command.from_dict(raw), server_time)
        if self.inline:
            self.drain()
        return True

    def _link_down(self, now: float, why: str, hard: bool = False) -> None:
        self.last_error = why
        if hard or now - self.last_ok > OFFLINE_AFTER_SEC:
            self._set_lease(None, now)
            if not self.offline:
                self.offline = True
                self.log(f"agent: coordinator unreachable ({why}) — automation cancelled, inputs released")
                self._invalidate_queue(Reason.AGENT_OFFLINE.value, why, latch=False)
                self.backend.safe_stop("coordinator offline")
        else:
            self.enforce_lease()

    # ----- commands ------------------------------------------------------------------
    def _rotate_run(self, run_id: str) -> None:
        """A new run_id drops the previous session. The first bind does not."""
        with self._lock:
            if run_id == self.run_id:
                return
            previous = self.run_id
            self.run_id = run_id
            # The first bind has no session to drop. An empty gap after a real run does.
            if not previous and not (run_id and self._run_released):
                return
            pending = list(self.queue)
            self.queue.clear()
            self.epoch += 1
            self._run_released = not bool(run_id)
            if run_id:
                self.session_stopped = False
                self.cancel.clear()
        detail = f"run changed to {run_id}" if run_id else "coordinator has no run"
        self._fail_queued(pending, Reason.OPERATOR_STOP.value, detail)

    def _accept(self, cmd: Command, server_time: float) -> None:
        if cmd.agent_id != self.agent_id:
            return
        known = self.journal.known(cmd.command_id)
        if known is not None:
            if known[0] == "done":
                self.journal.requeue_result(cmd.command_id)
            return
        if not self.journal.begin(cmd):
            return
        if server_time > cmd.issued_at + cmd.deadline_sec:
            self.journal.finish(CommandResult(cmd.command_id, ResultStatus.EXPIRED, Reason.COMMAND_TIMEOUT.value,
                                              "received after its deadline"))
            return
        if self.run_id and cmd.run_id and cmd.run_id != self.run_id:
            self._fail(cmd, Reason.OPERATOR_STOP.value, "stale run")
            return
        if cmd.type in URGENT:
            # SAFE_STOP latches the session. STOP_GAMEPLAY only drops the queue.
            self._invalidate_queue(Reason.OPERATOR_STOP.value, cmd.type.value,
                                   latch=cmd.type is CommandType.SAFE_STOP)
            self._run(cmd)
            return
        with self._lock:
            if self.session_stopped or self.cancel.is_set() or self._stop.is_set():
                rejected = True
            else:
                rejected = False
                self.queue.append((cmd, self.epoch))
                self._wake.set()
        if rejected:
            self._fail(cmd, Reason.OPERATOR_STOP.value, "cancelled")

    def _invalidate_queue(self, reason: str, detail: str, *, latch: bool) -> None:
        with self._lock:
            self.epoch += 1
            self.cancel.set()
            if latch:
                self.session_stopped = True
                self.lease_attempt, self.lease_until = "", 0.0
            pending = list(self.queue)
            self.queue.clear()
        self._fail_queued(pending, reason, detail)

    def _fail_queued(self, pending: list, reason: str, detail: str) -> None:
        for item in pending:
            cmd = item[0] if isinstance(item, tuple) else item
            self._fail(cmd, reason, detail)

    def _fail(self, cmd: Command, reason: str, detail: str) -> None:
        known = self.journal.known(cmd.command_id)
        if known is None or known[0] != "running":
            return
        self.journal.finish(CommandResult(cmd.command_id, ResultStatus.FAILED, reason, detail))

    def _cancel_view(self, epoch: int) -> _CommandCancel:
        return _CommandCancel(self.cancel, epoch, self)

    def _run(self, cmd: Command, epoch: int | None = None) -> None:
        if cmd.type not in URGENT:
            with self._lock:
                bound = self.epoch if epoch is None else epoch
                stale = self.cancel.is_set() or self.session_stopped or bound != self.epoch
            if stale:
                self._fail(cmd, Reason.OPERATOR_STOP.value, "cancelled")
                return
        else:
            bound = self.epoch
        view = self._cancel_view(bound)
        cancelled_before = view.is_set()
        ctx = ExecContext(view, self.coordinator_time, lambda: self.lease_attempt)
        try:
            result = self.backend.execute(cmd, ctx)
        except Exception as exc:
            self.log(f"agent: {cmd.type.value} crashed: {exc!r}")
            self.backend.safe_stop(f"{cmd.type.value} crashed")
            result = CommandResult(cmd.command_id, ResultStatus.FAILED, Reason.COMMAND_FAILED.value, repr(exc))
        if result.command_id != cmd.command_id:
            result = replace(result, command_id=cmd.command_id)
        if result.succeeded and view.is_set() and not cancelled_before:
            detail = "effect not confirmed after cancel"
            if result.detail:
                detail = f"{detail}: {result.detail}"
            result = replace(result, status=ResultStatus.UNCONFIRMED, reason=Reason.EFFECT_UNCONFIRMED.value,
                             detail=detail)
        self.journal.finish(result)

    def drain(self) -> None:
        with self._lock:
            if self._draining:
                return
            self._draining = True
        try:
            while not self._stop.is_set():
                with self._lock:
                    if not self.queue:
                        return
                    cmd, cmd_epoch = self.queue.popleft()
                    if cmd_epoch != self.epoch or self.cancel.is_set() or self.session_stopped:
                        self.current = None
                        stale = True
                    else:
                        stale = False
                        self.current = cmd
                if stale:
                    self._fail(cmd, Reason.OPERATOR_STOP.value, "cancelled")
                    continue
                try:
                    self._run(cmd, cmd_epoch)
                finally:
                    with self._lock:
                        if self.current is cmd:
                            self.current = None
        finally:
            with self._lock:
                self._draining = False

    # ----- threads -------------------------------------------------------------------
    def _executor(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(0.2)
            self._wake.clear()
            self.drain()

    def _watchdog(self) -> None:
        while not self._stop.wait(0.1):
            self.enforce_lease()

    def run_forever(self, heartbeat_sec: float = HEARTBEAT_SEC) -> None:
        threads = [threading.Thread(target=self._executor, daemon=True, name="fleet-exec"),
                   threading.Thread(target=self._watchdog, daemon=True, name="fleet-lease")]
        for t in threads:
            t.start()
        try:
            while not self._stop.is_set():
                started = self.clock()
                try:
                    self.tick()
                except Exception as exc:
                    self.log(f"agent: heartbeat crashed: {exc!r}")
                self._stop.wait(max(0.05, heartbeat_sec - (self.clock() - started)))
        finally:
            self.shutdown()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def shutdown(self) -> None:
        with self._lock:
            if self._shut_down:
                return
            self._shut_down = True
        self._stop.set()
        self._wake.set()
        self._invalidate_queue(Reason.OPERATOR_STOP.value, "agent shutting down", latch=True)
        self._set_lease(None, self.clock())
        try:
            self.backend.safe_stop("agent shutdown")
        except Exception as exc:
            self.log(f"agent: safe_stop during shutdown failed: {exc!r}")

    def snapshot(self) -> dict[str, Any]:
        return {"agent_id": self.agent_id, "run_id": self.run_id, "offline": self.offline,
                "last_error": self.last_error, "lease": self.lease_attempt,
                "current": self.current.command_id if self.current else "", "queued": len(self.queue),
                "clock_offset": round(self.clock_offset, 3)}
