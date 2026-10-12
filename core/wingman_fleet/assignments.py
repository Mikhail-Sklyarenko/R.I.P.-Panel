"""Durable four-slot account assignment. This does not start Steam or CS2."""
from __future__ import annotations

import hashlib
import hmac
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from core.wingman_fleet import PROTOCOL_VERSION
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


STALE_CATALOG = "Каталог этого компьютера устарел. Дождитесь нового подключения агента."


_PROOF_SOURCES = frozenset({"steam_local", "gsi"})
_VERIFIED = "verified"


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
                revoked INTEGER NOT NULL DEFAULT 0,
                registration_generation INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS agent_presence(
                agent_id TEXT PRIMARY KEY,
                boot_id TEXT NOT NULL DEFAULT '',
                protocol INTEGER NOT NULL DEFAULT 0,
                last_seen REAL NOT NULL DEFAULT 0,
                process_generation INTEGER NOT NULL DEFAULT 0,
                registration_generation INTEGER NOT NULL DEFAULT 0,
                last_sequence INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS verification_seq(
                preparation_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                next_seq INTEGER NOT NULL,
                PRIMARY KEY(preparation_id, agent_id));
            CREATE TABLE IF NOT EXISTS catalog_heads(
                agent_id TEXT PRIMARY KEY,
                catalog_generation INTEGER NOT NULL,
                boot_id TEXT NOT NULL DEFAULT '',
                sequence INTEGER NOT NULL DEFAULT 0,
                received_at REAL NOT NULL,
                registration_generation INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS enrollments(
                agent_id TEXT PRIMARY KEY,
                code_hash TEXT NOT NULL,
                expires_at REAL NOT NULL);
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
        for table, name, decl in (
            ("preparation_slots", "verification_status", "TEXT NOT NULL DEFAULT 'unverified'"),
            ("preparation_slots", "verification_source", "TEXT NOT NULL DEFAULT ''"),
            ("preparation_slots", "verification_boot_id", "TEXT NOT NULL DEFAULT ''"),
            ("preparation_slots", "verification_generation", "INTEGER NOT NULL DEFAULT 0"),
            ("preparation_slots", "verification_error", "TEXT NOT NULL DEFAULT ''"),
            ("preparation_slots", "verification_id", "TEXT NOT NULL DEFAULT ''"),
            ("preparation_slots", "verification_seq", "INTEGER NOT NULL DEFAULT 0"),
            ("preparation_slots", "link_state", "TEXT NOT NULL DEFAULT ''"),
            ("preparations", "plan_json", "TEXT NOT NULL DEFAULT ''"),
            ("catalog_heads", "vault_status", "TEXT NOT NULL DEFAULT ''"),
            ("agent_credentials", "registration_generation", "INTEGER NOT NULL DEFAULT 0"),
            ("agent_presence", "process_generation", "INTEGER NOT NULL DEFAULT 0"),
            ("agent_presence", "registration_generation", "INTEGER NOT NULL DEFAULT 0"),
            ("agent_presence", "last_sequence", "INTEGER NOT NULL DEFAULT 0"),
            ("catalog_heads", "registration_generation", "INTEGER NOT NULL DEFAULT 0"),
        ):
            try:
                self.store.db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
            except sqlite3.OperationalError:
                pass
        version = int(self.store.db.execute("PRAGMA user_version").fetchone()[0])
        if version > 5:
            raise AssignmentError("fleet schema is newer than this program")
        if version < 5:
            self.store.db.execute("PRAGMA user_version=5")

    @contextmanager
    def _tx(self) -> Iterator[Any]:
        """Join only the transaction owned by this thread. Never adopt another thread's."""
        with self.store.transaction():
            yield self.store.db

    def register_agent(self, agent_id: str, token: str) -> None:
        if not agent_id or not token:
            raise AssignmentError("agent registration needs an id and a token")
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._tx():
            row = self.store.db.execute(
                "SELECT token_hash, revoked, registration_generation FROM agent_credentials WHERE agent_id=?",
                (agent_id,),
            ).fetchone()
            if row is not None and row[1] == 0 and not hmac.compare_digest(row[0], digest):
                raise AssignmentError("agent_id is already registered to different credentials")
            previous = int(row["registration_generation"]) if row is not None else 0
            changed = row is None or int(row["revoked"]) != 0 or not hmac.compare_digest(row["token_hash"], digest)
            generation = previous + 1 if changed else max(previous, 1)
            if changed and row is not None:
                self.store.db.execute(
                    "UPDATE agent_presence SET process_generation=0, boot_id='', last_sequence=0 WHERE agent_id=?",
                    (agent_id,),
                )
                self.store.db.execute(
                    "UPDATE preparation_slots SET verification_status='unverified', "
                    "verification_error='registration changed', verification_seq=0, verification_id='', "
                    "identity_at=0, identity_observed='' WHERE agent_id=? AND reservation_status='committed'",
                    (agent_id,),
                )
            self.store.db.execute(
                "INSERT INTO agent_credentials(agent_id, token_hash, revoked, registration_generation) "
                "VALUES(?,?,0,?) ON CONFLICT(agent_id) DO UPDATE SET token_hash=excluded.token_hash, "
                "revoked=0, registration_generation=excluded.registration_generation",
                (agent_id, digest, generation),
            )
        if changed and row is not None:
            current = self.current()
            if current:
                self._refresh_ready(current, self.clock())

    def revoke_agent(self, agent_id: str) -> None:
        with self._tx():
            self.store.db.execute("UPDATE agent_credentials SET revoked=1 WHERE agent_id=?", (agent_id,))

    def registration_state(self, agent_id: str) -> str:
        with self.store._lock:
            row = self.store.db.execute(
                "SELECT revoked FROM agent_credentials WHERE agent_id=?", (agent_id,)
            ).fetchone()
        if row is None:
            return "unregistered"
        return "revoked" if row["revoked"] else "registered"

    def has_credential(self, agent_id: str) -> bool:
        return self.registration_state(agent_id) == "registered"

    def authorize(self, agent_id: str, token: str) -> str:
        state = self.registration_state(agent_id)
        if state == "revoked":
            raise AssignmentError("agent registration is revoked")
        if state != "registered" or not self.authenticate(agent_id, token):
            raise AssignmentError("agent is not registered")
        return state

    def open_enrollment(self, agent_id: str, *, ttl_sec: float = 300.0) -> str:
        if not agent_id or self.registration_state(agent_id) == "registered":
            raise AssignmentError("enrollment needs an unregistered or revoked agent id")
        code = uuid.uuid4().hex
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
        with self._tx():
            self.store.db.execute(
                "INSERT INTO enrollments(agent_id, code_hash, expires_at) VALUES(?,?,?) "
                "ON CONFLICT(agent_id) DO UPDATE SET code_hash=excluded.code_hash, expires_at=excluded.expires_at",
                (agent_id, digest, self.clock() + ttl_sec),
            )
        return code

    def claim_enrollment(self, agent_id: str, code: str) -> str:
        digest = hashlib.sha256(str(code).encode("utf-8")).hexdigest()
        with self.store._lock:
            row = self.store.db.execute(
                "SELECT code_hash, expires_at FROM enrollments WHERE agent_id=?", (agent_id,)
            ).fetchone()
        if row is None or not hmac.compare_digest(row["code_hash"], digest) or self.clock() > float(row["expires_at"]):
            raise AssignmentError("enrollment code is not valid")
        token = uuid.uuid4().hex
        self.register_agent(agent_id, token)
        with self._tx():
            self.store.db.execute("DELETE FROM enrollments WHERE agent_id=?", (agent_id,))
        return token

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
        generation = int(snapshot.get("catalog_generation") or snapshot.get("catalog_revision") or 0)
        sequence = int(snapshot.get("sequence") or 0)
        boot_id = str(snapshot.get("boot_id") or "")
        with self.store._lock:
            head = self.store.db.execute(
                "SELECT catalog_generation, sequence, boot_id, registration_generation "
                "FROM catalog_heads WHERE agent_id=?",
                (agent_id,),
            ).fetchone()
        current_reg = self.registration_generation(agent_id)
        snap_reg = snapshot.get("registration_generation")
        if snap_reg is not None and current_reg and int(snap_reg) != current_reg:
            return
        head_reg = int(head["registration_generation"] or 0) if head is not None else 0
        inherited_unknown = bool(head is not None and head_reg == 0 and current_reg)
        new_registration = bool(current_reg and head_reg and current_reg != head_reg)
        replace_head = inherited_unknown or new_registration
        if head is not None and not replace_head and generation < int(head["catalog_generation"]):
            return
        presence = self.store.db.execute(
            "SELECT boot_id, process_generation FROM agent_presence WHERE agent_id=?", (agent_id,)
        ).fetchone()
        if presence is not None and int(presence["process_generation"] or 0) > 0:
            snap_process = int(snapshot.get("process_generation") or 0)
            snap_boot = str(snapshot.get("boot_id") or "")
            if snap_process != int(presence["process_generation"]) or (
                snap_boot and str(presence["boot_id"] or "") and snap_boot != str(presence["boot_id"])
            ):
                return
        stored_boot = str(head["boot_id"] or "") if head is not None else ""
        new_process = bool(boot_id) and boot_id != stored_boot
        if (
            head is not None and not new_process and generation == int(head["catalog_generation"])
            and sequence < int(head["sequence"])
        ):
            return
        with self._tx():
            self.store.db.execute("DELETE FROM catalog_cache WHERE agent_id=?", (agent_id,))
            for item in accounts:
                account_revision = int(item.get("account_revision") or item.get("catalog_revision") or generation)
                self.store.db.execute(
                    "INSERT INTO catalog_cache(agent_id, local_account_id, steam_id64, display_name, enabled,"
                    " binding_status, availability_status, catalog_revision, received_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (agent_id, str(item["local_account_id"]), str(item.get("steam_id64") or ""),
                     str(item.get("display_name") or "")[:80], 1 if item.get("enabled", True) else 0,
                     str(item.get("binding_status") or "unbound"),
                     str(item.get("availability_status") or "available"), account_revision, self.clock()),
                )
            self.store.db.execute(
                "INSERT INTO catalog_heads(agent_id, catalog_generation, boot_id, sequence, received_at, "
                "vault_status, registration_generation) VALUES(?,?,?,?,?,?,?) ON CONFLICT(agent_id) DO UPDATE SET "
                "catalog_generation=excluded.catalog_generation, boot_id=excluded.boot_id, "
                "sequence=excluded.sequence, received_at=excluded.received_at, "
                "vault_status=excluded.vault_status, "
                "registration_generation=excluded.registration_generation",
                (agent_id, generation, boot_id, sequence, self.clock(),
                 str(snapshot.get("vault_status") or "")[:40], current_reg),
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
        with self._tx():
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

    def begin_prepare(self, preparation_id: str, links: dict[str, str] | None = None) -> list[Any]:
        prep = self._require(preparation_id)
        self._validate_selection(self._selection_from_slots(preparation_id), {} if links is None else links)
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
        with self._tx():
            self.store.db.execute(
                "UPDATE preparations SET run_id=?, status='committed', updated_at=? WHERE preparation_id=?",
                (run_id, self.clock(), preparation_id),
            )
            self._event(preparation_id, "committed", run_id)
        return run_id

    def note_commit(self, preparation_id: str, agent_id: str, *, ok: bool, generation: int, detail: str = "") -> str:
        slot = self._slot_for_agent(preparation_id, agent_id)
        if int(generation) != int(slot["assignment_generation"]):
            raise AssignmentError("assignment generation does not match")
        prep = self._require(preparation_id)
        if prep["status"] in ("released", "failed"):
            return prep["status"]
        if prep["status"] not in ("committed", "committing", "reconcile_required", "verifying_identity", "ready"):
            raise AssignmentError("commit result arrived without a durable commit decision")
        status = "committed" if ok else "reconcile_required"
        with self._tx():
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
                      fresh: bool, source: str = "gsi", generation: int | None = None, boot_id: str = "",
                      verification_id: str = "", seq: int = 0, identity_status: str = "") -> str:
        slot = self._slot_for_agent(preparation_id, agent_id)
        expected_generation = int(slot["assignment_generation"])
        if generation is not None and int(generation) != expected_generation:
            return self._require(preparation_id)["status"]
        live_boot = self._live_boot(agent_id)
        if live_boot and str(boot_id or "") != live_boot:
            return self._require(preparation_id)["status"]
        stored_seq = int(slot["verification_seq"] or 0)
        if stored_seq > int(seq) or (stored_seq == int(seq) and stored_seq > 0):
            return self._require(preparation_id)["status"]
        observed = parse_steam_id64(observed_steam_id64) if observed_steam_id64 else ""
        status, error = self._verification_status(
            slot["steam_id64"], observed, fresh=fresh, source=source, identity_status=identity_status,
        )
        with self._tx():
            self.store.db.execute(
                "UPDATE preparation_slots SET identity_observed=?, identity_at=?, verification_status=?,"
                " verification_source=?, verification_generation=?, verification_boot_id=?, verification_error=?,"
                " verification_id=?, verification_seq=? WHERE preparation_id=? AND agent_id=?",
                (observed, now, status, source, expected_generation, boot_id, error, verification_id, int(seq),
                 preparation_id, agent_id),
            )
            self._event(preparation_id, "identity", f"{agent_id}:{status}")
        return self._refresh_ready(preparation_id, now)

    def note_link(self, agent_id: str, link: str) -> None:
        with self._tx():
            self.store.db.execute(
                "UPDATE preparation_slots SET link_state=? WHERE agent_id=? AND reservation_status='committed'",
                (link, agent_id),
            )

    def note_presence(self, agent_id: str, *, protocol: int, seen_at: float, boot_id: str = "",
                      process_generation: int = -1, registration_generation: int = -1,
                      last_sequence: int = -1, reset_sequence: bool = False) -> None:
        """Record the heartbeat that proves an agent is present. This is not an identity proof."""
        process_value = int(process_generation)
        registration_value = int(registration_generation)
        with self._tx():
            self.store.db.execute(
                "INSERT INTO agent_presence(agent_id, boot_id, protocol, last_seen, process_generation, "
                "registration_generation) VALUES(?,?,?,?,CASE WHEN ?>=0 THEN ? ELSE 0 END,CASE WHEN ?>=0 THEN ? ELSE 0 END) "
                "ON CONFLICT(agent_id) DO UPDATE SET protocol=excluded.protocol, last_seen=excluded.last_seen, "
                "boot_id=CASE WHEN excluded.boot_id<>'' THEN excluded.boot_id ELSE agent_presence.boot_id END, "
                "process_generation=CASE WHEN ?>=0 THEN ? ELSE agent_presence.process_generation END, "
                "registration_generation=CASE WHEN ?>=0 THEN ? ELSE agent_presence.registration_generation END",
                (agent_id, boot_id, int(protocol), float(seen_at),
                 process_value, process_value, registration_value, registration_value,
                 process_value, process_value, registration_value, registration_value),
            )
            if int(last_sequence) >= 0:
                if reset_sequence:
                    self.store.db.execute(
                        "UPDATE agent_presence SET last_sequence=? WHERE agent_id=?",
                        (int(last_sequence), agent_id),
                    )
                else:
                    self.store.db.execute(
                        "UPDATE agent_presence SET last_sequence=? WHERE agent_id=? AND last_sequence<?",
                        (int(last_sequence), agent_id, int(last_sequence)),
                    )

    def registration_generation(self, agent_id: str) -> int:
        with self.store._lock:
            row = self.store.db.execute(
                "SELECT registration_generation FROM agent_credentials WHERE agent_id=? AND revoked=0",
                (agent_id,),
            ).fetchone()
        return int(row["registration_generation"]) if row is not None else 0

    def session_decision(self, agent_id: str, *, registration_generation: int, process_generation: int,
                         boot_id: str) -> str:
        """Return an error code, or '' when this heartbeat may change state. Does not write."""
        if self.registration_generation(agent_id) != int(registration_generation):
            return "registration_rejected"
        if int(process_generation) < 1 or not boot_id:
            return "session_rejected"
        row = self.store.db.execute(
            "SELECT boot_id, process_generation FROM agent_presence WHERE agent_id=?", (agent_id,)
        ).fetchone()
        stored_gen = int(row["process_generation"] or 0) if row is not None else 0
        stored_boot = str(row["boot_id"] or "") if row is not None else ""
        if stored_gen and int(process_generation) < stored_gen:
            return "stale_process"
        if stored_gen and int(process_generation) == stored_gen and stored_boot and stored_boot != boot_id:
            return "boot_conflict"
        return ""

    def heartbeat_sequence_allowed(self, agent_id: str, *, process_generation: int, boot_id: str,
                                   sequence: int) -> bool:
        """False when this boot already accepted a sequence at least this large."""
        row = self.store.db.execute(
            "SELECT boot_id, process_generation, last_sequence FROM agent_presence WHERE agent_id=?",
            (agent_id,),
        ).fetchone()
        if row is None:
            return True
        stored_gen = int(row["process_generation"] or 0)
        stored_boot = str(row["boot_id"] or "")
        stored_seq = int(row["last_sequence"] or 0)
        if stored_gen and int(process_generation) > stored_gen:
            return True
        if stored_boot and stored_boot == boot_id and stored_seq and int(sequence) <= stored_seq:
            return False
        return True

    def evidence_matches_session(self, agent_id: str, evidence: dict[str, Any]) -> bool:
        row = self.store.db.execute(
            "SELECT boot_id, process_generation FROM agent_presence WHERE agent_id=?", (agent_id,)
        ).fetchone()
        if row is None:
            return False
        live_boot = str(row["boot_id"] or "")
        live_gen = int(row["process_generation"] or 0)
        if live_gen <= 0 or "process_generation" not in evidence:
            return False
        if int(evidence.get("process_generation") or 0) != live_gen:
            return False
        ev_boot = str(evidence.get("boot_id") or "")
        return not live_boot or ev_boot == live_boot

    def install_session(self, agent_id: str, *, process_generation: int, registration_generation: int,
                        boot_id: str, protocol: int, seen_at: float, sequence: int = -1) -> None:
        previous_boot = self._live_boot(agent_id)
        previous_gen = 0
        row = self.store.db.execute(
            "SELECT process_generation FROM agent_presence WHERE agent_id=?", (agent_id,)
        ).fetchone()
        if row is not None:
            previous_gen = int(row["process_generation"] or 0)
        new_process = bool(boot_id) and (
            previous_boot != boot_id or (previous_gen and int(process_generation) > previous_gen)
        )
        if new_process:
            self.note_boot(agent_id, boot_id)
        self.note_presence(
            agent_id, protocol=protocol, seen_at=seen_at, boot_id=boot_id,
            process_generation=int(process_generation), registration_generation=int(registration_generation),
            last_sequence=int(sequence), reset_sequence=new_process,
        )

    def note_boot(self, agent_id: str, boot_id: str) -> None:
        """A new process drops the previous identity proof, including its sequence."""
        if not boot_id:
            return
        with self._tx():
            previous = self._live_boot(agent_id)
            self.store.db.execute(
                "INSERT INTO agent_presence(agent_id, boot_id, protocol, last_seen) VALUES(?,?,0,0) "
                "ON CONFLICT(agent_id) DO UPDATE SET boot_id=excluded.boot_id",
                (agent_id, boot_id),
            )
            if not previous or previous != boot_id:
                self.store.db.execute(
                    "UPDATE preparation_slots SET verification_status='unverified', verification_error='agent restarted', "
                    "verification_seq=0, verification_id='', identity_at=0, identity_observed='' "
                    "WHERE agent_id=? AND verification_boot_id<>? AND verification_boot_id<>'' "
                    "AND reservation_status='committed'",
                    (agent_id, boot_id),
                )
        preparation_id = self.current()
        if preparation_id:
            self._refresh_ready(preparation_id, self.clock())

    def _live_boot(self, agent_id: str) -> str:
        row = self.store.db.execute(
            "SELECT boot_id FROM agent_presence WHERE agent_id=?", (agent_id,)
        ).fetchone()
        return str(row["boot_id"] or "") if row is not None else ""

    def _verification_status(self, expected: str, observed: str, *, fresh: bool, source: str,
                             identity_status: str = "") -> tuple[str, str]:
        declared = identity_status or (source if source in _PROOF_SOURCES else "")
        if declared == "mismatch" or source == "conflict":
            return "mismatch", "sources disagree" if not observed or observed == expected else f"observed {observed}"
        if declared in ("unconfirmed", "manual", "loginusers") or source in ("manual", "loginusers", "unconfirmed"):
            return "unverified", "identity was not confirmed"
        if not fresh:
            return "unverified", "observation was not fresh"
        if source not in _PROOF_SOURCES:
            return "unverified", "source is not an active login"
        if not observed:
            return "unavailable", "steam identity was not observed"
        if observed != expected:
            return "mismatch", f"observed {observed}"
        return _VERIFIED, ""

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

    def note_release(self, preparation_id: str, agent_id: str, *, ok: bool, detail: str = "",
                     generation: int | None = None) -> str:
        slot = self._slot_for_agent(preparation_id, agent_id)
        if generation is not None and int(generation) != int(slot["assignment_generation"]):
            return self._require(preparation_id)["status"]
        if not ok:
            self._move(preparation_id, self._require(preparation_id)["status"], "reconcile_required", force=True)
            return "reconcile_required"
        with self._tx():
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

    def _allocate_verification_seq(self, preparation_id: str, agent_id: str) -> int:
        row = self.store.db.execute(
            "SELECT next_seq FROM verification_seq WHERE preparation_id=? AND agent_id=?",
            (preparation_id, agent_id),
        ).fetchone()
        if row is None:
            self.store.db.execute(
                "INSERT INTO verification_seq(preparation_id, agent_id, next_seq) VALUES(?,?,?)",
                (preparation_id, agent_id, 2),
            )
            return 1
        seq = int(row["next_seq"])
        self.store.db.execute(
            "UPDATE verification_seq SET next_seq=? WHERE preparation_id=? AND agent_id=?",
            (seq + 1, preparation_id, agent_id),
        )
        return seq

    def enqueue(self, preparation_id: str, kind: str) -> int:
        from core.wingman_fleet.models import Command, CommandType
        prep = self._require(preparation_id)
        commands = []
        with self.store.transaction():
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
                    "verify": CommandType.VERIFY_ASSIGNMENT,
                }[kind]
                verification_id = uuid.uuid4().hex if kind == "verify" else ""
                if verification_id:
                    params["verification_id"] = verification_id
                    params["seq"] = self._allocate_verification_seq(preparation_id, slot["agent_id"])
                command_id = (
                    f"{preparation_id}/verify/{verification_id}/{slot['agent_id']}"
                    if verification_id else f"{preparation_id}/{kind}/{slot['agent_id']}"
                )
                commands.append(Command(
                    command_id, preparation_id, slot["agent_id"], command_type, params, "", 1, 240.0, self.clock(),
                ))
            return len(self.store.add_commands(commands))

    def release(self, preparation_id: str) -> str:
        raise AssignmentError("direct release is closed; wait for four agent acknowledgements")

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

    def ready(self, preparation_id: str, now: float | None = None, links: dict[str, str] | None = None) -> bool:
        now = self.clock() if now is None else now
        self._refresh_ready(preparation_id, now, links)
        prep = self._require(preparation_id)
        return prep["status"] == "ready" and self._identities_fresh(preparation_id, now, links)

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

    def _refresh_ready(self, preparation_id: str, now: float, links: dict[str, str] | None = None) -> str:
        prep = self._require(preparation_id)
        if prep["status"] not in ("committed", "verifying_identity", "ready"):
            return prep["status"]
        fresh = self._identities_fresh(preparation_id, now, links)
        target = "ready" if fresh else "committed"
        if prep["status"] != target:
            with self._tx():
                self.store.db.execute(
                    "UPDATE preparations SET status=?, updated_at=? WHERE preparation_id=?",
                    (target, self.clock(), preparation_id),
                )
                self._event(preparation_id, target, "identity gate")
        return target

    def _slot_proven(self, row: Any, now: float, links: dict[str, str] | None) -> bool:
        if row["reservation_status"] != "committed":
            return False
        if row["verification_status"] != _VERIFIED:
            return False
        if row["verification_source"] not in _PROOF_SOURCES:
            return False
        if int(row["verification_generation"] or 0) != int(row["assignment_generation"]):
            return False
        if row["identity_observed"] != row["steam_id64"]:
            return False
        age = now - float(row["identity_at"] or 0)
        if age < 0 or age > self.identity_ttl_sec:
            return False
        if row["link_state"] not in ("", "healthy"):
            return False
        if self.registration_state(row["agent_id"]) != "registered":
            return False
        if self._presence_link(row["agent_id"], now) != "healthy":
            return False
        if links:
            supplied = links.get(row["agent_id"])
            if supplied is not None and supplied != "healthy":
                return False
        return True

    def _presence_link(self, agent_id: str, now: float) -> str:
        from core.wingman_fleet.coordinator import OFFLINE_AFTER_SEC, SUSPECT_AFTER_SEC
        row = self.store.db.execute(
            "SELECT protocol, last_seen FROM agent_presence WHERE agent_id=?", (agent_id,)
        ).fetchone()
        if row is None or int(row["protocol"] or 0) != PROTOCOL_VERSION:
            return "offline"
        age = now - float(row["last_seen"] or 0)
        if age < 0 or age > OFFLINE_AFTER_SEC:
            return "offline"
        if age > SUSPECT_AFTER_SEC:
            return "suspect"
        return "healthy"

    def _identities_fresh(self, preparation_id: str, now: float, links: dict[str, str] | None = None) -> bool:
        slots = self.slots(preparation_id)
        return len(slots) == 4 and all(self._slot_proven(row, now, links) for row in slots)

    def _note_slot(self, preparation_id: str, agent_id: str, *, ok: bool, success: str, failure: str,
                   complete_status: str, detail: str) -> str:
        prep = self._require(preparation_id)
        if prep["status"] not in ("preparing", "prepared", "aborting", "reconcile_required"):
            return prep["status"]
        status = success if ok else failure
        with self._tx():
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
            reason = self.catalog_usable(slot["agent_id"])
            if reason:
                raise AssignmentError(reason)
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
            self._require_present(slot["agent_id"], links)

    def catalog_usable(self, agent_id: str, *, now: float | None = None) -> str:
        """Empty when this catalog may be used for a new assignment."""
        now = self.clock() if now is None else now
        if self.registration_state(agent_id) != "registered":
            return STALE_CATALOG
        current_reg = self.registration_generation(agent_id)
        head = self.store.db.execute(
            "SELECT catalog_generation, received_at, registration_generation, boot_id "
            "FROM catalog_heads WHERE agent_id=?",
            (agent_id,),
        ).fetchone()
        if head is None:
            return STALE_CATALOG
        head_reg = int(head["registration_generation"] or 0)
        if not head_reg or head_reg != current_reg:
            return STALE_CATALOG
        catalog_age = now - float(head["received_at"] or 0)
        if catalog_age < 0 or catalog_age > self.identity_ttl_sec:
            return STALE_CATALOG
        presence = self.store.db.execute(
            "SELECT boot_id, process_generation FROM agent_presence WHERE agent_id=?", (agent_id,)
        ).fetchone()
        if presence is not None and int(presence["process_generation"] or 0) > 0:
            live_boot = str(presence["boot_id"] or "")
            head_boot = str(head["boot_id"] or "")
            if live_boot and head_boot and live_boot != head_boot:
                return STALE_CATALOG
        return ""

    def connection_state(self, agent_id: str, *, now: float | None = None,
                         links: dict[str, str] | None = None) -> str:
        """Operator-facing presence. This is not an identity proof."""
        now = self.clock() if now is None else now
        registration = self.registration_state(agent_id) if agent_id else "unregistered"
        if registration == "revoked":
            return "REVOKED"
        if registration != "registered":
            return "UNREGISTERED"
        row = self.store.db.execute(
            "SELECT protocol, last_seen FROM agent_presence WHERE agent_id=?", (agent_id,)
        ).fetchone()
        if row is None:
            return "OFFLINE"
        if int(row["protocol"] or 0) != PROTOCOL_VERSION:
            return "PROTOCOL MISMATCH"
        from core.wingman_fleet.coordinator import OFFLINE_AFTER_SEC, SUSPECT_AFTER_SEC
        age = now - float(row["last_seen"] or 0)
        if age < 0 or age > OFFLINE_AFTER_SEC:
            link = "offline"
        elif age > SUSPECT_AFTER_SEC:
            link = "suspect"
        else:
            link = "healthy"
        supplied = (links or {}).get(agent_id)
        if supplied in ("offline", "suspect") and link == "healthy":
            link = supplied
        return {"healthy": "ONLINE / HEALTHY", "suspect": "SUSPECT", "offline": "OFFLINE"}[link]

    def discard_unstarted(self, preparation_id: str) -> None:
        prep = self._require(preparation_id)
        if prep["status"] in ("draft", "validating"):
            self._move(preparation_id, prep["status"], "failed")

    def _require_present(self, agent_id: str, links: dict[str, str]) -> None:
        from core.wingman_fleet.coordinator import SUSPECT_AFTER_SEC
        if links.get(agent_id) != "healthy":
            raise AssignmentError(f"{agent_id} is not online")
        if self.registration_state(agent_id) != "registered":
            raise AssignmentError(f"{agent_id} is not registered")
        reason = self.catalog_usable(agent_id)
        if reason:
            raise AssignmentError(reason)
        row = self.store.db.execute(
            "SELECT protocol, last_seen FROM agent_presence WHERE agent_id=?", (agent_id,)
        ).fetchone()
        now = self.clock()
        if row is None or int(row["protocol"] or 0) != PROTOCOL_VERSION:
            raise AssignmentError(f"{agent_id} is not on protocol {PROTOCOL_VERSION}")
        age = now - float(row["last_seen"] or 0)
        if age < 0 or age > SUSPECT_AFTER_SEC:
            raise AssignmentError(f"{agent_id} heartbeat is not fresh")

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

    def build_run_plan(self, roster: Any, *, build_version: str, resource_manifest: str,
                       links: dict[str, str] | None = None) -> Any:
        """Freeze the committed assignment into an immutable run. Refuses any other roster."""
        from core.wingman_fleet.models import AccountProfile, PairProfile, RetryPolicy, RunPlan
        from modules.fleet_agent.identity import steam64_to_friend_code
        now = self.clock()
        with self._tx():
            preparation_id = self.current()
            if not preparation_id:
                raise AssignmentError("there is no assignment to start")
            self._refresh_ready(preparation_id, now, links)
            if not self._identities_fresh(preparation_id, now, links):
                raise AssignmentError("assignments are not ready")
            prep = self._require(preparation_id)
            slots = {int(row["slot_id"]): row for row in self.slots(preparation_id)}
            accounts = {}
            seen_names: set[str] = set()
            for slot_id, pair_id, role in SLOT_LAYOUT:
                row = slots[slot_id]
                cached = self._cached(row["agent_id"], row["local_account_id"])
                display = str(cached["display_name"] if cached is not None else "") or row["agent_id"]
                if display.casefold() in seen_names:
                    display = f"{display}-{slot_id}"
                seen_names.add(display.casefold())
                accounts[slot_id] = AccountProfile(
                    f"{row['agent_id']}:{row['local_account_id']}", row["steam_id64"], display,
                    steam64_to_friend_code(row["steam_id64"]), row["agent_id"], pair_id, role,
                )
            pairs = (
                PairProfile("pair-1", 1, accounts[1], accounts[2]),
                PairProfile("pair-2", 2, accounts[3], accounts[4]),
            )
            plan = RunPlan(
                prep["run_id"], now, pairs, build_version, resource_manifest,
                RetryPolicy.from_dict(getattr(roster, "retry", {}) or {}),
            )
            roster.replace_slots({
                slot_id: {
                    "agent_id": row["agent_id"],
                    "steam_id64": row["steam_id64"],
                    "display_name": accounts[slot_id].display_name,
                    "friend_code": accounts[slot_id].friend_code,
                    "local_account_id": row["local_account_id"],
                }
                for slot_id, row in slots.items()
            })
            self.store.db.execute(
                "UPDATE preparations SET plan_json=? WHERE preparation_id=?",
                (plan.to_json(), preparation_id),
            )
        return plan

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
        with self._tx():
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
