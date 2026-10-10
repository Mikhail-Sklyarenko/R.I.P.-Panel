"""Durable four-slot account assignment. This does not start Steam or CS2."""
from __future__ import annotations

import hashlib
import hmac
import sqlite3
import time
import uuid
from typing import Any

from core.wingman_fleet.accounts import parse_steam_id64
from core.wingman_fleet.roster import SLOT_LAYOUT
from core.wingman_fleet.store import FleetStore

_OPEN = ("prepared", "committed", "active", "reconcile_required")
_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"validating", "failed", "released"}),
    "validating": frozenset({"preparing", "failed", "released"}),
    "preparing": frozenset({"prepared", "aborting", "reconcile_required", "failed"}),
    "prepared": frozenset({"committing", "aborting", "failed"}),
    "committing": frozenset({"committed", "reconcile_required"}),
    "committed": frozenset({"verifying_identity", "reconcile_required", "released", "aborting"}),
    "verifying_identity": frozenset({"ready", "committed", "reconcile_required"}),
    "ready": frozenset({"committed", "reconcile_required", "released", "aborting"}),
    "aborting": frozenset({"released", "reconcile_required", "failed"}),
    "reconcile_required": frozenset({"preparing", "committing", "committed", "released", "failed"}),
    "failed": frozenset({"released"}),
    "released": frozenset(),
}


class AssignmentError(RuntimeError):
    pass


class AssignmentBook:
    def __init__(self, store: FleetStore, *, identity_ttl_sec: float = 120.0, clock=time.time):
        self.store = store
        self.identity_ttl_sec = identity_ttl_sec
        self.clock = clock
        self.store.db.row_factory = sqlite3.Row
        self._ensure()

    def _ensure(self) -> None:
        self.store.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS preparations(
                preparation_id TEXT PRIMARY KEY,
                coordinator_generation INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                run_id TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS preparation_slots(
                preparation_id TEXT NOT NULL,
                slot_id INTEGER NOT NULL,
                agent_id TEXT NOT NULL,
                local_account_id TEXT NOT NULL,
                steam_id64 TEXT NOT NULL,
                expected_catalog_revision INTEGER NOT NULL,
                assignment_generation INTEGER NOT NULL,
                reservation_status TEXT NOT NULL,
                identity_observed TEXT NOT NULL DEFAULT '',
                identity_at REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(preparation_id, slot_id));
            CREATE UNIQUE INDEX IF NOT EXISTS assignment_one_agent
                ON preparation_slots(agent_id)
                WHERE reservation_status IN ('prepared','committed','active','reconcile_required');
            CREATE UNIQUE INDEX IF NOT EXISTS assignment_one_steam
                ON preparation_slots(steam_id64)
                WHERE reservation_status IN ('prepared','committed','active','reconcile_required');
            CREATE TABLE IF NOT EXISTS assignment_events(
                id INTEGER PRIMARY KEY,
                preparation_id TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT NOT NULL,
                created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS agent_credentials(
                agent_id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS catalog_cache(
                agent_id TEXT NOT NULL,
                local_account_id TEXT NOT NULL,
                steam_id64 TEXT NOT NULL,
                display_name TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                binding_status TEXT NOT NULL,
                availability_status TEXT NOT NULL,
                catalog_revision INTEGER NOT NULL,
                received_at REAL NOT NULL,
                PRIMARY KEY(agent_id, local_account_id));
            """
        )

    def register_agent(self, agent_id: str, token: str) -> None:
        if not agent_id or not token:
            raise AssignmentError("agent registration needs an id and a token")
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self.store.transaction():
            row = self.store.db.execute(
                "SELECT token_hash, revoked FROM agent_credentials WHERE agent_id=?", (agent_id,)
            ).fetchone()
            if row is not None and row[1] == 0 and not hmac.compare_digest(row[0], digest):
                raise AssignmentError("agent_id is already registered to different credentials")
            self.store.db.execute(
                "INSERT INTO agent_credentials(agent_id, token_hash, revoked) VALUES(?,?,0) "
                "ON CONFLICT(agent_id) DO UPDATE SET token_hash=excluded.token_hash, revoked=0",
                (agent_id, digest),
            )

    def revoke_agent(self, agent_id: str) -> None:
        with self.store.transaction():
            self.store.db.execute("UPDATE agent_credentials SET revoked=1 WHERE agent_id=?", (agent_id,))

    def has_credential(self, agent_id: str) -> bool:
        with self.store._lock:
            row = self.store.db.execute(
                "SELECT revoked FROM agent_credentials WHERE agent_id=?", (agent_id,)
            ).fetchone()
        return row is not None and not row["revoked"]

    def current(self) -> str:
        with self.store._lock:
            row = self.store.db.execute(
                "SELECT preparation_id FROM preparations WHERE status NOT IN ('released', 'failed') "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return str(row["preparation_id"]) if row is not None else ""

    def current_ready(self, now: float | None = None) -> bool:
        preparation_id = self.current()
        return bool(preparation_id) and self.ready(preparation_id, now)

    def authenticate(self, agent_id: str, token: str) -> bool:
        with self.store._lock:
            row = self.store.db.execute(
                "SELECT token_hash, revoked FROM agent_credentials WHERE agent_id=?", (agent_id,)
            ).fetchone()
        if row is None or row[1]:
            return False
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return hmac.compare_digest(row[0], digest)

    def remember_catalog(self, agent_id: str, snapshot: dict[str, Any]) -> None:
        if snapshot.get("agent_id") not in (None, "", agent_id):
            raise AssignmentError("catalog snapshot is for a different agent")
        accounts = snapshot.get("accounts") or []
        revision = int(snapshot.get("catalog_revision") or 0)
        with self.store.transaction():
            self.store.db.execute("DELETE FROM catalog_cache WHERE agent_id=?", (agent_id,))
            for item in accounts:
                self.store.db.execute(
                    "INSERT INTO catalog_cache(agent_id, local_account_id, steam_id64, display_name, enabled,"
                    " binding_status, availability_status, catalog_revision, received_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (agent_id, str(item["local_account_id"]), str(item.get("steam_id64") or ""),
                     str(item.get("display_name") or "")[:80], 1 if item.get("enabled", True) else 0,
                     str(item.get("binding_status") or "unbound"),
                     str(item.get("availability_status") or "available"), revision, self.clock()),
                )

    def draft(self, selections: list[dict[str, Any]], *, links: dict[str, str] | None = None) -> str:
        """Validate four slots and persist a draft. Nothing is reserved yet."""
        if self._blocking_run():
            raise AssignmentError("an active run forbids assignment changes")
        normalized = self._normalize(selections)
        links = links or {}
        self._validate_selection(normalized, links)
        preparation_id = uuid.uuid4().hex
        generation = self._next_generation()
        now = self.clock()
        with self.store.transaction():
            self.store.db.execute(
                "INSERT INTO preparations(preparation_id, coordinator_generation, status, created_at, updated_at)"
                " VALUES(?,?,?,?,?)",
                (preparation_id, generation, "draft", now, now),
            )
            for slot in normalized:
                self.store.db.execute(
                    "INSERT INTO preparation_slots(preparation_id, slot_id, agent_id, local_account_id, steam_id64,"
                    " expected_catalog_revision, assignment_generation, reservation_status) VALUES(?,?,?,?,?,?,?,?)",
                    (preparation_id, slot["slot_id"], slot["agent_id"], slot["local_account_id"], slot["steam_id64"],
                     slot["expected_catalog_revision"], generation, "selected"),
                )
            self._reject_conflicts(normalized, preparation_id)
            self._event(preparation_id, "draft", "selection stored")
        return preparation_id

    def begin_prepare(self, preparation_id: str) -> list[Any]:
        prep = self._require(preparation_id)
        self._validate_selection(self._selection_from_slots(preparation_id), {})
        if prep["status"] == "draft":
            self._move(preparation_id, "draft", "validating")
            prep = self._require(preparation_id)
        self._move(preparation_id, prep["status"], "preparing")
        return self.slots(preparation_id)

    def note_prepare(self, preparation_id: str, agent_id: str, *, ok: bool, detail: str = "") -> str:
        return self._note_slot(preparation_id, agent_id, ok=ok, success="prepared", failure="rejected",
                               complete_status="prepared", detail=detail or "prepare")

    def decide_commit(self, preparation_id: str, *, run_id: str) -> str:
        prep = self._require(preparation_id)
        if prep["status"] == "committed" and prep["run_id"] == run_id:
            return run_id
        if prep["status"] != "prepared":
            raise AssignmentError(f"cannot commit from {prep['status']}")
        if not run_id:
            raise AssignmentError("commit needs a run_id")
        self._move(preparation_id, "prepared", "committing")
        with self.store.transaction():
            self.store.db.execute(
                "UPDATE preparations SET run_id=?, status='committed', updated_at=? WHERE preparation_id=?",
                (run_id, self.clock(), preparation_id),
            )
            self._event(preparation_id, "committed", run_id)
        return run_id

    def note_commit(self, preparation_id: str, agent_id: str, *, ok: bool, generation: int, detail: str = "") -> str:
        slot = self._slot_for_agent(preparation_id, agent_id)
        if int(generation) < int(slot["assignment_generation"]):
            raise AssignmentError("stale assignment generation")
        prep = self._require(preparation_id)
        if prep["status"] not in ("committed", "committing", "reconcile_required", "verifying_identity", "ready"):
            raise AssignmentError("commit result arrived without a durable commit decision")
        status = "committed" if ok else "reconcile_required"
        with self.store.transaction():
            self.store.db.execute(
                "UPDATE preparation_slots SET reservation_status=?, assignment_generation=? "
                "WHERE preparation_id=? AND agent_id=?",
                (status, generation, preparation_id, agent_id),
            )
            if not ok:
                self.store.db.execute(
                    "UPDATE preparations SET status='reconcile_required', last_error=?, updated_at=? "
                    "WHERE preparation_id=?",
                    (detail or "commit failed", self.clock(), preparation_id),
                )
            self._event(preparation_id, status, f"{agent_id}:{detail}")
        return self._require(preparation_id)["status"]

    def note_identity(self, preparation_id: str, agent_id: str, observed_steam_id64: str, *, now: float,
                      fresh: bool) -> str:
        slot = self._slot_for_agent(preparation_id, agent_id)
        observed = parse_steam_id64(observed_steam_id64) if observed_steam_id64 else ""
        matched = fresh and observed == slot["steam_id64"]
        with self.store.transaction():
            self.store.db.execute(
                "UPDATE preparation_slots SET identity_observed=?, identity_at=? WHERE preparation_id=? AND agent_id=?",
                (observed, now, preparation_id, agent_id),
            )
            self._event(preparation_id, "identity", f"{agent_id}:{'match' if matched else 'mismatch'}")
        return self._refresh_ready(preparation_id, now)

    def begin_release(self, preparation_id: str) -> str:
        """Ask agents to drop the reservation. The group is not released until they answer."""
        prep = self._require(preparation_id)
        if prep["status"] == "released":
            return "released"
        if self._blocking_run() and prep["run_id"] and prep["status"] in ("committed", "ready", "verifying_identity"):
            raise AssignmentError("cannot release assignments that belong to the active run")
        if prep["status"] != "aborting":
            self._move(preparation_id, prep["status"], "aborting")
        return "aborting"

    def note_release(self, preparation_id: str, agent_id: str, *, ok: bool, detail: str = "") -> str:
        if not ok:
            self._move(preparation_id, self._require(preparation_id)["status"], "reconcile_required", force=True)
            return "reconcile_required"
        with self.store.transaction():
            self.store.db.execute(
                "UPDATE preparation_slots SET reservation_status='released' "
                "WHERE preparation_id=? AND agent_id=?",
                (preparation_id, agent_id),
            )
            rows = list(self.store.db.execute(
                "SELECT reservation_status FROM preparation_slots WHERE preparation_id=?",
                (preparation_id,),
            ).fetchall())
            if len(rows) == 4 and all(row[0] == "released" for row in rows):
                self.store.db.execute(
                    "UPDATE preparations SET status='released', updated_at=? WHERE preparation_id=?",
                    (self.clock(), preparation_id),
                )
            self._event(preparation_id, "release", f"{agent_id}:{detail}")
        return self._require(preparation_id)["status"]

    def enqueue(self, preparation_id: str, kind: str) -> int:
        from core.wingman_fleet.models import Command, CommandType
        prep = self._require(preparation_id)
        commands = []
        for slot in self.slots(preparation_id):
            params = {
                "preparation_id": preparation_id,
                "local_account_id": slot["local_account_id"],
                "steam_id64": slot["steam_id64"],
                "catalog_revision": int(slot["expected_catalog_revision"]),
                "generation": int(slot["assignment_generation"]),
                "coordinator_generation": int(prep["coordinator_generation"]),
                "run_id": prep["run_id"],
            }
            command_type = {
                "prepare": CommandType.PREPARE_ASSIGNMENT,
                "commit": CommandType.COMMIT_ASSIGNMENT,
                "release": CommandType.RELEASE_ASSIGNMENT,
                "reconcile": CommandType.RECONCILE_ASSIGNMENT,
            }[kind]
            commands.append(Command(
                f"{preparation_id}/{kind}/{slot['agent_id']}",
                preparation_id, slot["agent_id"], command_type, params, "", 1, 240.0, self.clock(),
            ))
        return len(self.store.add_commands(commands))

    def release(self, preparation_id: str) -> str:
        prep = self._require(preparation_id)
        if prep["status"] == "released":
            return "released"
        if self._blocking_run() and prep["run_id"] and prep["status"] in ("committed", "ready", "verifying_identity"):
            raise AssignmentError("cannot release assignments that belong to the active run")
        with self.store.transaction():
            self.store.db.execute(
                "UPDATE preparation_slots SET reservation_status='released' WHERE preparation_id=?",
                (preparation_id,),
            )
            self.store.db.execute(
                "UPDATE preparations SET status='released', updated_at=? WHERE preparation_id=?",
                (self.clock(), preparation_id),
            )
            self._event(preparation_id, "released", "operator release")
        return "released"

    def reconcile(self, preparation_id: str) -> str:
        prep = self._require(preparation_id)
        if prep["status"] == "released":
            return "released"
        self._move(preparation_id, prep["status"], "reconcile_required", force=True)
        return "reconcile_required"

    def status(self, preparation_id: str) -> dict[str, Any]:
        prep = self._require(preparation_id)
        return {
            "preparation_id": preparation_id,
            "status": prep["status"],
            "run_id": prep["run_id"],
            "coordinator_generation": prep["coordinator_generation"],
            "last_error": prep["last_error"],
            "slots": [dict(row) for row in self.slots(preparation_id)],
        }

    def slots(self, preparation_id: str) -> list[Any]:
        with self.store._lock:
            return list(self.store.db.execute(
                "SELECT * FROM preparation_slots WHERE preparation_id=? ORDER BY slot_id", (preparation_id,)
            ).fetchall())

    def events(self, preparation_id: str) -> list[Any]:
        with self.store._lock:
            return list(self.store.db.execute(
                "SELECT status, detail FROM assignment_events WHERE preparation_id=? ORDER BY id",
                (preparation_id,),
            ).fetchall())

    def ready(self, preparation_id: str, now: float | None = None) -> bool:
        now = self.clock() if now is None else now
        self._refresh_ready(preparation_id, now)
        prep = self._require(preparation_id)
        return prep["status"] == "ready" and self._identities_fresh(preparation_id, now)

    def _reject_conflicts(self, slots: list[dict[str, Any]], preparation_id: str) -> None:
        for slot in slots:
            row = self.store.db.execute(
                "SELECT s.preparation_id FROM preparation_slots s "
                "JOIN preparations p ON p.preparation_id = s.preparation_id "
                "WHERE p.status NOT IN ('released', 'failed') AND s.preparation_id<>? "
                "AND (s.agent_id=? OR s.steam_id64=?)",
                (preparation_id, slot["agent_id"], slot["steam_id64"]),
            ).fetchone()
            if row is not None:
                raise AssignmentError("an open preparation already uses this agent or SteamID64")

    def _selection_from_slots(self, preparation_id: str) -> list[dict[str, Any]]:
        return [
            {
                "slot_id": row["slot_id"],
                "agent_id": row["agent_id"],
                "local_account_id": row["local_account_id"],
                "steam_id64": row["steam_id64"],
                "expected_catalog_revision": row["expected_catalog_revision"],
            }
            for row in self.slots(preparation_id)
        ]

    def _refresh_ready(self, preparation_id: str, now: float) -> str:
        prep = self._require(preparation_id)
        if prep["status"] not in ("committed", "verifying_identity", "ready"):
            return prep["status"]
        slots = self.slots(preparation_id)
        if len(slots) != 4 or any(row["reservation_status"] != "committed" for row in slots):
            return prep["status"]
        fresh = all(
            row["identity_observed"] == row["steam_id64"] and now - float(row["identity_at"]) <= self.identity_ttl_sec
            for row in slots
        )
        target = "ready" if fresh else "committed"
        if prep["status"] != target:
            with self.store.transaction():
                self.store.db.execute(
                    "UPDATE preparations SET status=?, updated_at=? WHERE preparation_id=?",
                    (target, self.clock(), preparation_id),
                )
                self._event(preparation_id, target, "identity gate")
        return target

    def _identities_fresh(self, preparation_id: str, now: float) -> bool:
        slots = self.slots(preparation_id)
        return len(slots) == 4 and all(
            row["identity_observed"] == row["steam_id64"] and now - float(row["identity_at"]) <= self.identity_ttl_sec
            for row in slots
        )

    def _note_slot(self, preparation_id: str, agent_id: str, *, ok: bool, success: str, failure: str,
                   complete_status: str, detail: str) -> str:
        prep = self._require(preparation_id)
        if prep["status"] not in ("preparing", "prepared", "aborting", "reconcile_required"):
            raise AssignmentError(f"prepare result is not accepted in {prep['status']}")
        status = success if ok else failure
        with self.store.transaction():
            current = self._slot_for_agent(preparation_id, agent_id)
            if current["reservation_status"] == success and ok:
                pass
            else:
                self.store.db.execute(
                    "UPDATE preparation_slots SET reservation_status=? WHERE preparation_id=? AND agent_id=?",
                    (status, preparation_id, agent_id),
                )
            self._event(preparation_id, status, f"{agent_id}:{detail}")
            rows = list(self.store.db.execute(
                "SELECT reservation_status FROM preparation_slots WHERE preparation_id=?", (preparation_id,)
            ).fetchall())
            if any(row[0] == failure for row in rows):
                self.store.db.execute(
                    "UPDATE preparations SET status='aborting', last_error=?, updated_at=? WHERE preparation_id=?",
                    (detail or failure, self.clock(), preparation_id),
                )
            elif len(rows) == 4 and all(row[0] == success for row in rows):
                self.store.db.execute(
                    "UPDATE preparations SET status=?, updated_at=? WHERE preparation_id=?",
                    (complete_status, self.clock(), preparation_id),
                )
        return self._require(preparation_id)["status"]

    def _validate_selection(self, slots: list[dict[str, Any]], links: dict[str, str]) -> None:
        if len(slots) != 4:
            raise AssignmentError("exactly four slots are required")
        agents = [slot["agent_id"] for slot in slots]
        steams = [slot["steam_id64"] for slot in slots]
        if len(set(agents)) != 4:
            raise AssignmentError("duplicate agent_id")
        if len(set(steams)) != 4:
            raise AssignmentError("duplicate steam_id64")
        expected = {slot: (pair, role.value) for slot, pair, role in SLOT_LAYOUT}
        for slot in slots:
            if slot["slot_id"] not in expected:
                raise AssignmentError("unknown slot")
            link = links.get(slot["agent_id"])
            if link is not None and link != "healthy":
                raise AssignmentError(f"{slot['agent_id']} is not online")
            cached = self._cached(slot["agent_id"], slot["local_account_id"])
            if cached is None:
                raise AssignmentError(f"{slot['agent_id']} has no catalog entry for that account")
            if not cached["enabled"]:
                raise AssignmentError("account is disabled")
            if cached["steam_id64"] != slot["steam_id64"]:
                raise AssignmentError("catalog steam_id64 does not match the selection")
            if not cached["steam_id64"]:
                raise AssignmentError("account has no SteamID64 binding")
            if int(cached["catalog_revision"]) != int(slot["expected_catalog_revision"]):
                raise AssignmentError("catalog revision is stale")
            if cached["binding_status"] == "unbound":
                raise AssignmentError("account is unbound")

    def _normalize(self, selections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = []
        for item in selections:
            steam = parse_steam_id64(item.get("steam_id64"))
            normalized.append({
                "slot_id": int(item["slot_id"]),
                "agent_id": str(item["agent_id"]),
                "local_account_id": str(item["local_account_id"]),
                "steam_id64": steam,
                "expected_catalog_revision": int(item["expected_catalog_revision"]),
            })
        return normalized

    def _cached(self, agent_id: str, local_account_id: str):
        return self.store.db.execute(
            "SELECT * FROM catalog_cache WHERE agent_id=? AND local_account_id=?",
            (agent_id, local_account_id),
        ).fetchone()

    def _blocking_run(self) -> bool:
        row = self.store.db.execute("SELECT run_id FROM runs WHERE active=1").fetchone()
        return row is not None

    def _next_generation(self) -> int:
        row = self.store.db.execute("SELECT COALESCE(MAX(coordinator_generation), 0) FROM preparations").fetchone()
        return int(row[0]) + 1

    def _require(self, preparation_id: str):
        row = self.store.db.execute(
            "SELECT * FROM preparations WHERE preparation_id=?", (preparation_id,)
        ).fetchone()
        if row is None:
            raise AssignmentError("unknown preparation")
        return row

    def _slot_for_agent(self, preparation_id: str, agent_id: str):
        row = self.store.db.execute(
            "SELECT * FROM preparation_slots WHERE preparation_id=? AND agent_id=?",
            (preparation_id, agent_id),
        ).fetchone()
        if row is None:
            raise AssignmentError("agent is not part of this preparation")
        return row

    def _move(self, preparation_id: str, current: str, target: str, *, force: bool = False) -> None:
        if current == target:
            return
        if not force and target not in _TRANSITIONS.get(current, frozenset()):
            raise AssignmentError(f"cannot move {current} to {target}")
        with self.store.transaction():
            self.store.db.execute(
                "UPDATE preparations SET status=?, updated_at=? WHERE preparation_id=?",
                (target, self.clock(), preparation_id),
            )
            self._event(preparation_id, target, f"from {current}")

    def _event(self, preparation_id: str, status: str, detail: str) -> None:
        self.store.db.execute(
            "INSERT INTO assignment_events(preparation_id, status, detail, created_at) VALUES(?,?,?,?)",
            (preparation_id, status, detail[:240], self.clock()),
        )
