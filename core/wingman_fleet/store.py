"""Coordinator persistence: run snapshot, command outbox/results, transitions, friendships.

SQLite gives atomic writes, so a coordinator restart never forgets that a command
was already issued (the deterministic command id is the idempotency key).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from core.wingman_fleet.models import Command, CommandResult, ResultStatus, RunPlan, dumps

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
    run_id TEXT PRIMARY KEY, plan_json TEXT NOT NULL, created_at REAL NOT NULL,
    state_json TEXT NOT NULL DEFAULT '{}', updated_at REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS commands(
    command_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, agent_id TEXT NOT NULL, type TEXT NOT NULL,
    command_json TEXT NOT NULL, issued_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
    result_json TEXT, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS commands_agent ON commands(agent_id, status);
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, run_id TEXT, pair_id TEXT, agent_id TEXT,
    kind TEXT NOT NULL, before TEXT, after TEXT, reason TEXT, detail TEXT, data_json TEXT);
CREATE INDEX IF NOT EXISTS events_run ON events(run_id, id);
CREATE TABLE IF NOT EXISTS friendships(
    a TEXT NOT NULL, b TEXT NOT NULL, confirmed_at REAL NOT NULL, PRIMARY KEY(a, b));
CREATE TABLE IF NOT EXISTS agents(
    agent_id TEXT PRIMARY KEY, computer TEXT, last_seen REAL, info_json TEXT);
"""


class FleetStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self.db.close()

    # ----- runs ----------------------------------------------------------------------
    def save_run(self, plan: RunPlan) -> None:
        with self._lock:
            self.db.execute("UPDATE runs SET active=0 WHERE run_id<>?", (plan.run_id,))
            self.db.execute(
                "INSERT OR IGNORE INTO runs(run_id, plan_json, created_at, updated_at) VALUES(?,?,?,?)",
                (plan.run_id, plan.to_json(), plan.created_at, time.time()))

    def save_state(self, run_id: str, state: dict[str, Any]) -> None:
        with self._lock:
            self.db.execute("UPDATE runs SET state_json=?, updated_at=? WHERE run_id=?",
                            (json.dumps(state, ensure_ascii=False), time.time(), run_id))

    def deactivate_run(self, run_id: str) -> None:
        with self._lock:
            self.db.execute("UPDATE runs SET active=0 WHERE run_id=?", (run_id,))

    def active_run(self) -> tuple[RunPlan, dict[str, Any]] | None:
        with self._lock:
            row = self.db.execute(
                "SELECT plan_json, state_json FROM runs WHERE active=1 ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return RunPlan.from_json(row[0]), json.loads(row[1] or "{}")

    # ----- commands ------------------------------------------------------------------
    def add_commands(self, commands: Iterable[Command]) -> list[Command]:
        """Insert new commands; an existing id is never re-inserted or re-executed."""
        added = []
        with self._lock:
            for c in commands:
                cur = self.db.execute(
                    "INSERT OR IGNORE INTO commands(command_id, run_id, agent_id, type, command_json,"
                    " issued_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                    (c.command_id, c.run_id, c.agent_id, c.type.value, dumps(c), c.issued_at, time.time()))
                if cur.rowcount:
                    added.append(c)
        return added

    def pending_for(self, agent_id: str, run_id: str) -> list[Command]:
        with self._lock:
            rows = self.db.execute(
                "SELECT command_json FROM commands WHERE agent_id=? AND run_id=? AND status IN"
                " ('pending','accepted') ORDER BY issued_at, rowid", (agent_id, run_id)).fetchall()
        return [Command.from_dict(json.loads(r[0])) for r in rows]

    def _owned_row(self, result: CommandResult, agent_id: str, run_id: str):
        if not agent_id or not run_id:
            return None
        row = self.db.execute(
            "SELECT status, agent_id, run_id FROM commands WHERE command_id=?",
            (result.command_id,)).fetchone()
        if row is None or row[1] != agent_id or row[2] != run_id:
            return None
        return row

    def record_result(self, result: CommandResult, *, agent_id: str, run_id: str) -> bool:
        """Store a result only for the agent and run that own the command.

        A terminal status is never overwritten. False means nothing new was written:
        unknown command, wrong owner, or a result that was already terminal.
        """
        with self._lock:
            row = self._owned_row(result, agent_id, run_id)
            if row is None:
                return False
            if row[0] not in ("pending", ResultStatus.ACCEPTED.value):
                return False
            self.db.execute("UPDATE commands SET status=?, result_json=?, updated_at=? WHERE command_id=?",
                            (result.status.value, dumps(result), time.time(), result.command_id))
            return True

    def result_is_stored(self, result: CommandResult, *, agent_id: str, run_id: str) -> bool:
        """True when this agent already has a terminal result for its own command."""
        with self._lock:
            row = self._owned_row(result, agent_id, run_id)
            if row is None:
                return False
            return row[0] not in ("pending", ResultStatus.ACCEPTED.value)

    def expire_pending(self, run_id: str, now_monotonic: float, issued_before: float) -> list[str]:
        with self._lock:
            rows = self.db.execute(
                "SELECT command_id FROM commands WHERE run_id=? AND status='pending' AND issued_at<?",
                (run_id, issued_before)).fetchall()
            ids = [r[0] for r in rows]
            for cid in ids:
                r = CommandResult(cid, ResultStatus.EXPIRED, "command_timeout", "never acknowledged")
                self.db.execute("UPDATE commands SET status=?, result_json=?, updated_at=? WHERE command_id=?",
                                (r.status.value, dumps(r), time.time(), cid))
        return ids

    def supersede(self, run_id: str, keep_ids: set[str], keep_types: set[str]) -> list[str]:
        """Expire undelivered phase-bound commands the FSM no longer wants.

        A reconnecting agent must never receive, e.g., a START_SEARCH of an aborted wave.
        Commands already accepted by the agent are left to finish and report.
        """
        with self._lock:
            rows = self.db.execute("SELECT command_id, type FROM commands WHERE run_id=? AND status='pending'",
                                   (run_id,)).fetchall()
            stale = [cid for cid, ctype in rows if cid not in keep_ids and ctype not in keep_types]
            for cid in stale:
                r = CommandResult(cid, ResultStatus.EXPIRED, "superseded", "state machine moved on")
                self.db.execute("UPDATE commands SET status=?, result_json=?, updated_at=? WHERE command_id=?",
                                (r.status.value, dumps(r), time.time(), cid))
        return stale

    def results(self, run_id: str, since: float = 0.0) -> dict[str, CommandResult]:
        with self._lock:
            rows = self.db.execute(
                "SELECT result_json FROM commands WHERE run_id=? AND result_json IS NOT NULL AND issued_at>=?",
                (run_id, since)).fetchall()
        return {r.command_id: r for r in (CommandResult.from_dict(json.loads(x[0])) for x in rows)}

    def command_rows(self, run_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.db.execute(
                "SELECT command_id, agent_id, type, status, result_json, issued_at FROM commands"
                " WHERE run_id=? ORDER BY rowid DESC LIMIT ?", (run_id, limit)).fetchall()
        return [{"command_id": r[0], "agent_id": r[1], "type": r[2], "status": r[3],
                 "result": json.loads(r[4]) if r[4] else None, "issued_at": r[5]} for r in rows]

    # ----- events / friendships / agents -----------------------------------------------
    def event(self, kind: str, *, run_id: str = "", pair_id: str = "", agent_id: str = "",
              before: str = "", after: str = "", reason: str = "", detail: str = "",
              data: dict[str, Any] | None = None) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO events(ts, run_id, pair_id, agent_id, kind, before, after, reason, detail, data_json)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (time.time(), run_id, pair_id, agent_id, kind, before, after, reason, detail,
                 json.dumps(data, ensure_ascii=False) if data else None))

    def events(self, run_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.db.execute(
                "SELECT ts, pair_id, agent_id, kind, before, after, reason, detail FROM events"
                " WHERE run_id=? ORDER BY id DESC LIMIT ?", (run_id, limit)).fetchall()
        keys = ("ts", "pair_id", "agent_id", "kind", "before", "after", "reason", "detail")
        return [dict(zip(keys, r)) for r in rows]

    def confirm_friendship(self, a: str, b: str) -> None:
        a, b = sorted((a, b))
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO friendships(a, b, confirmed_at) VALUES(?,?,?)",
                            (a, b, time.time()))

    def friendship_known(self, a: str, b: str) -> bool:
        a, b = sorted((a, b))
        with self._lock:
            return self.db.execute("SELECT 1 FROM friendships WHERE a=? AND b=?", (a, b)).fetchone() is not None

    def touch_agent(self, agent_id: str, computer: str, info: dict[str, Any]) -> None:
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO agents(agent_id, computer, last_seen, info_json)"
                            " VALUES(?,?,?,?)", (agent_id, computer, time.time(), json.dumps(info)))
