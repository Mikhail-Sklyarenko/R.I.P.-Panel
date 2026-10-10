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
from core.wingman_fleet.accounts import CatalogError
from core.wingman_fleet.models import (
    ASSIGNMENT_COMMANDS, Command, CommandResult, CommandType, Identity, Observation, ResultStatus, Screen, to_dict,
)
from core.wingman_fleet.reasons import Reason
from modules.fleet_agent.backend import ExecContext, GameBackend
from modules.fleet_agent.journal import CommandJournal, JournalCorrupt
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
                 log: Callable[[str], None] | None = None, catalog: Any = None, agent_token: str = "",
                 registration_generation: int = 0):
        self.agent_id, self.backend, self.transport, self.journal = agent_id, backend, transport, journal
        self.token = token
        self.catalog = catalog
        self.agent_token = agent_token
        self.registration_generation = int(registration_generation or 0)
        self.build_version, self.resource_manifest = build_version, resource_manifest
        self.computer = computer
        self.inline, self.clock, self.wall = inline, clock, wall
        self.log = log or (lambda _m: None)
        self.boot_id = uuid.uuid4().hex
        self.process_generation = 0
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
        self._session_generation = 0
        self._lease_generation = 0
        self._fail_closed = False
        self._shut_down = False
        self._draining = False
        self._expected_generation = 0
        self._restore_session()
        self._claim_process()
        self._restore_expected_identity()

    def _claim_process(self) -> None:
        from modules.fleet_agent.journal import JournalCorrupt
        try:
            self.process_generation = self.journal.claim_process_generation()
            if self.registration_generation <= 0:
                self.registration_generation = self.journal.load_registration()
        except JournalCorrupt as exc:
            self.process_generation = 0
            self._fail_closed = True
            self.session_stopped = True
            self.cancel.set()
            self.last_error = f"journal corrupt: {exc}"

    def _restore_session(self) -> None:
        try:
            run_id, stopped, generation = self.journal.load_session()
        except JournalCorrupt as exc:
            self._fail_closed = True
            self.session_stopped = True
            self.cancel.set()
            self.last_error = f"journal corrupt: {exc}"
            return
        self.run_id = run_id
        self._session_generation = generation
        if stopped and run_id:
            self.session_stopped = True
            self.cancel.set()
            self._run_released = False

    def _restore_expected_identity(self) -> None:
        """Reapply a committed expected SteamID64. This does not mark the account verified."""
        catalog = self.catalog
        if catalog is None or not hasattr(catalog, "active_committed"):
            return
        row = catalog.active_committed()
        if row is None:
            return
        steam = str(row["steam_id64"] or "")
        if not steam:
            return
        try:
            self._install_expected(steam, int(row["generation"] or 0))
        except Exception:
            self.last_error = "expected identity was not restored"

    def _install_expected(self, steam_id64: str, generation: int) -> None:
        if int(generation) < int(self._expected_generation):
            return
        apply = getattr(self.backend, "apply_identity_assignment", None)
        if apply is None:
            return
        apply(steam_id64)
        self._expected_generation = int(generation)

    def _identity_locked(self) -> bool:
        if self.lease_attempt:
            return True
        return bool(getattr(self.backend, "_lease", ""))

    def _persist_session(self) -> None:
        if self._fail_closed:
            return
        self.journal.save_session(self.run_id, self.session_stopped, self._session_generation)

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
            self._lease_generation += 1
            generation = self._lease_generation
        self._push_lease(generation)
        with self._lock:
            # The apply above can return after SAFE_STOP already wrote a newer decision.
            superseded = (
                generation != self._lease_generation
                or self._gameplay_blocked()
                or self.lease_attempt != grant
            )
            if superseded and generation == self._lease_generation:
                self.lease_attempt, self.lease_until = "", 0.0
                self._lease_generation += 1
            follow = self._lease_generation if superseded else 0
        if follow:
            self._push_lease(follow)

    def enforce_lease(self) -> None:
        with self._lock:
            if self.lease_attempt and self.clock() > self.lease_until:
                self.log("agent: gameplay lease expired — revoking inputs")
                self.lease_attempt, self.lease_until = "", 0.0
            else:
                return
        self._push_lease(self._lease_generation)

    def _push_lease(self, generation: int | None = None) -> None:
        try:
            attempt = self.lease_attempt
            setter = self.backend.set_gameplay
            names = getattr(getattr(setter, "__code__", None), "co_varnames", ())
            if generation is not None and "generation" in names:
                setter(attempt, generation)
            else:
                setter(attempt)
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
        if self._fail_closed or self.process_generation < 1:
            self.last_error = self.last_error or "process generation is not available"
            return False
        now = self.clock()
        self.enforce_lease()
        obs = self.observe()
        results = self.journal.unacked()
        payload = {
            "boot_id": self.boot_id, "computer": self.computer, "token": self.token,
            "process_generation": self.process_generation,
            "registration_generation": self.registration_generation,
            "observation": to_dict(obs), "results": [to_dict(r) for r in results],
        }
        if self.agent_token:
            payload["agent_token"] = self.agent_token
        if self.catalog is not None:
            snapshot = self.catalog.snapshot(boot_id=self.boot_id, sequence=self.sequence).as_dict()
            snapshot["process_generation"] = self.process_generation
            payload["catalog"] = snapshot
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
                if self._fail_closed:
                    self.session_stopped = True
                else:
                    self.session_stopped = False
                    self.cancel.clear()
            self._session_generation += 1
        detail = f"run changed to {run_id}" if run_id else "coordinator has no run"
        self._fail_queued(pending, Reason.OPERATOR_STOP.value, detail)
        self._persist_session()

    def _accept(self, cmd: Command, server_time: float) -> None:
        if self._fail_closed or cmd.agent_id != self.agent_id:
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
        if cmd.type not in ASSIGNMENT_COMMANDS and self.run_id and cmd.run_id and cmd.run_id != self.run_id:
            self._fail(cmd, Reason.OPERATOR_STOP.value, "stale run")
            return
        if cmd.type in ASSIGNMENT_COMMANDS:
            self._run(cmd)
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
                self._lease_generation += 1
                self._session_generation += 1
            pending = list(self.queue)
            self.queue.clear()
            generation = self._lease_generation if latch else None
        self._fail_queued(pending, reason, detail)
        if latch:
            self._persist_session()
            self._push_lease(generation)

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
        if cmd.type in ASSIGNMENT_COMMANDS and (self._stop.is_set() or self._fail_closed):
            self._fail(cmd, Reason.OPERATOR_STOP.value, "agent is stopped")
            return
        if cmd.type not in URGENT and cmd.type not in ASSIGNMENT_COMMANDS:
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
            if cmd.type in ASSIGNMENT_COMMANDS:
                result = self._apply_assignment(cmd)
            else:
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

    def _measure_identity(self) -> tuple[str, str]:
        """The coordinator never supplies the observed SteamID64. This PC measures it."""
        probe = getattr(self, "identity_probe", None)
        if probe is None and not str(getattr(self.backend, "expected", "") or ""):
            return "", "unconfirmed"
        if probe is None and hasattr(self.backend, "measure_identity"):
            probe = self.backend.measure_identity
        elif probe is None and hasattr(self.backend, "verify_active_identity"):
            probe = self.backend.verify_active_identity
        if probe is None:
            return "", "unconfirmed"
        found = probe()
        identity = getattr(found, "identity", None)
        source = getattr(identity, "value", "") or "unconfirmed"
        steam = str(getattr(found, "steam_id64", "") or "")
        if identity is Identity.MISMATCH and steam:
            detail = str(getattr(found, "detail", "") or "")
            source = "gsi" if "GSI" in detail else "steam_local"
        elif source not in ("steam_local", "gsi"):
            source = "unconfirmed"
        return steam, source

    def _apply_assignment(self, cmd: Command) -> CommandResult:
        """Local catalog only. This never starts Steam, CS2, or a gameplay lease."""
        if self.catalog is None:
            return CommandResult(cmd.command_id, ResultStatus.FAILED, "no_catalog", "local catalog is not configured")
        params = cmd.params
        try:
            if cmd.type is CommandType.PREPARE_ASSIGNMENT:
                status = self.catalog.prepare(
                    preparation_id=str(params["preparation_id"]),
                    local_account_id=str(params["local_account_id"]),
                    steam_id64=str(params["steam_id64"]),
                    catalog_revision=int(params["catalog_revision"]),
                    generation=int(params["generation"]),
                    coordinator_generation=int(params.get("coordinator_generation") or params["generation"]),
                )
            elif cmd.type is CommandType.COMMIT_ASSIGNMENT:
                if self._identity_locked():
                    return CommandResult(
                        cmd.command_id, ResultStatus.FAILED, "assignment_rejected",
                        "identity cannot change during an active session",
                    )
                status = self.catalog.commit(
                    preparation_id=str(params["preparation_id"]),
                    generation=int(params["generation"]),
                    run_id=str(params["run_id"]),
                )
                steam = str(params.get("steam_id64") or "")
                if steam:
                    try:
                        self._install_expected(steam, int(params["generation"]))
                    except RuntimeError as exc:
                        return CommandResult(
                            cmd.command_id, ResultStatus.FAILED, "assignment_rejected", str(exc),
                        )
            elif cmd.type is CommandType.RELEASE_ASSIGNMENT:
                status = self.catalog.release(str(params["preparation_id"]))
            elif cmd.type is CommandType.RECONCILE_ASSIGNMENT:
                self.catalog.mark_reconcile(str(params["preparation_id"]))
                status = "reconcile_required"
            elif cmd.type is CommandType.VERIFY_ASSIGNMENT:
                observed, source = self._measure_identity()
                status = self.catalog.note_identity(
                    str(params["local_account_id"]), observed, source=source, now=self.wall(),
                )
                return CommandResult(
                    cmd.command_id, ResultStatus.COMPLETED,
                    evidence={
                        "status": status,
                        "observed_steam_id64": observed,
                        "source": source,
                        "fresh": status in {"verified", "mismatch"},
                        "verification_id": str(params.get("verification_id") or ""),
                        "boot_id": self.boot_id,
                        "process_generation": self.process_generation,
                    },
                )
            else:
                return CommandResult(cmd.command_id, ResultStatus.FAILED, "bad_command", cmd.type.value)
        except (CatalogError, KeyError, TypeError, ValueError) as exc:
            return CommandResult(cmd.command_id, ResultStatus.FAILED, "assignment_rejected", str(exc))
        return CommandResult(cmd.command_id, ResultStatus.COMPLETED, evidence={"status": status})

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
