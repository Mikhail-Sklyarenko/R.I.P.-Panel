"""Durable agent-side command journal: exactly-once execution per command_id."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from core.wingman_fleet.models import Command, CommandResult, ResultStatus, dumps

_SCHEMA = """
CREATE TABLE IF NOT EXISTS journal(
  command_id TEXT PRIMARY KEY, type TEXT NOT NULL, run_id TEXT NOT NULL,
  received_at REAL NOT NULL, state TEXT NOT NULL, result_json TEXT, acked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS agent_session(
  id INTEGER PRIMARY KEY CHECK(id=1),
  run_id TEXT NOT NULL,
  stopped INTEGER NOT NULL,
  generation INTEGER NOT NULL,
  updated_at REAL NOT NULL);
"""


class JournalCorrupt(RuntimeError):
    """The local journal cannot be trusted. The agent must fail closed."""


class CommandJournal:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(_SCHEMA)
        self._lock = threading.RLock()
        self._recover_interrupted()

    def _recover_interrupted(self) -> None:
        """A command running when the agent died is reported failed, never silently re-run."""
        with self._lock:
            rows = self.db.execute("SELECT command_id FROM journal WHERE state='running'").fetchall()
            for (cid,) in rows:
                self.finish(CommandResult(cid, ResultStatus.FAILED, "command_failed",
                                          "agent restarted while the command was running"))

    def known(self, command_id: str) -> tuple[str, CommandResult | None] | None:
        with self._lock:
            row = self.db.execute("SELECT state, result_json FROM journal WHERE command_id=?",
                                  (command_id,)).fetchone()
        if row is None:
            return None
        return row[0], CommandResult.from_dict(json.loads(row[1])) if row[1] else None

    def begin(self, cmd: Command) -> bool:
        """Claim the command; False when it was already seen (duplicate delivery)."""
        with self._lock:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO journal(command_id, type, run_id, received_at, state) VALUES(?,?,?,?,?)",
                (cmd.command_id, cmd.type.value, cmd.run_id, time.time(), "running"))
            return cur.rowcount == 1

    def finish(self, result: CommandResult) -> None:
        with self._lock:
            self.db.execute("UPDATE journal SET state='done', result_json=?, acked=0 WHERE command_id=?",
                            (dumps(result), result.command_id))

    def unacked(self, limit: int = 32) -> list[CommandResult]:
        with self._lock:
            rows = self.db.execute("SELECT result_json FROM journal WHERE state='done' AND acked=0 "
                                   "ORDER BY received_at LIMIT ?", (limit,)).fetchall()
        return [CommandResult.from_dict(json.loads(r[0])) for r in rows]

    def ack(self, command_ids: list[str]) -> None:
        with self._lock:
            self.db.executemany("UPDATE journal SET acked=1 WHERE command_id=?", [(c,) for c in command_ids])

    def requeue_result(self, command_id: str) -> None:
        """Coordinator re-delivered a finished command: resend its result."""
        with self._lock:
            self.db.execute("UPDATE journal SET acked=0 WHERE command_id=? AND state='done'", (command_id,))

    def prune(self, older_than_sec: float = 7 * 86400) -> None:
        with self._lock:
            self.db.execute("DELETE FROM journal WHERE acked=1 AND received_at<?", (time.time() - older_than_sec,))

    def load_session(self) -> tuple[str, bool, int]:
        """Return (run_id, stopped, generation). A damaged row fails closed."""
        with self._lock:
            try:
                row = self.db.execute(
                    "SELECT run_id, stopped, generation FROM agent_session WHERE id=1"
                ).fetchone()
            except sqlite3.DatabaseError as exc:
                raise JournalCorrupt(str(exc)) from exc
        if row is None:
            return "", False, 0
        run_id, stopped, generation = row
        if not isinstance(run_id, str) or stopped not in (0, 1) or not isinstance(generation, int):
            raise JournalCorrupt("agent_session row is not usable")
        return run_id, bool(stopped), int(generation)

    def save_session(self, run_id: str, stopped: bool, generation: int) -> None:
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self.db.execute(
                    "INSERT INTO agent_session(id, run_id, stopped, generation, updated_at) VALUES(1,?,?,?,?)"
                    " ON CONFLICT(id) DO UPDATE SET run_id=excluded.run_id, stopped=excluded.stopped,"
                    " generation=excluded.generation, updated_at=excluded.updated_at",
                    (run_id, 1 if stopped else 0, int(generation), time.time()),
                )
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def close(self) -> None:
        with self._lock:
            self.db.close()
