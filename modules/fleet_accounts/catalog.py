"""Sidecar metadata for the local vault index.

The catalog stores a stable id, a SteamID64 binding, and availability.
It does not store passwords, shared secrets, or maFile contents.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from core.wingman_fleet.accounts import (
    Availability,
    BindingStatus,
    CatalogAccountView,
    CatalogError,
    CatalogSnapshot,
    parse_steam_id64,
)

SCHEMA_VERSION = 1
_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS accounts(
    local_account_id TEXT PRIMARY KEY,
    login TEXT NOT NULL COLLATE NOCASE UNIQUE,
    steam_id64 TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    binding_status TEXT NOT NULL,
    availability_status TEXT NOT NULL,
    last_verified_at REAL NOT NULL DEFAULT 0,
    last_verified_source TEXT NOT NULL DEFAULT '',
    catalog_revision INTEGER NOT NULL DEFAULT 1,
    last_error TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS accounts_one_steam
    ON accounts(steam_id64) WHERE steam_id64 <> '';
CREATE TABLE IF NOT EXISTS binding_history(
    id INTEGER PRIMARY KEY,
    local_account_id TEXT NOT NULL,
    previous_steam_id64 TEXT NOT NULL,
    steam_id64 TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sync_issues(
    login TEXT PRIMARY KEY,
    issue TEXT NOT NULL,
    updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS reservations(
    preparation_id TEXT PRIMARY KEY,
    local_account_id TEXT NOT NULL,
    steam_id64 TEXT NOT NULL,
    catalog_revision INTEGER NOT NULL,
    generation INTEGER NOT NULL,
    coordinator_generation INTEGER NOT NULL,
    status TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS active_reservation(
    id INTEGER PRIMARY KEY CHECK(id = 1),
    preparation_id TEXT NOT NULL);
"""

_OPEN = frozenset({
    Availability.PREPARED.value,
    Availability.COMMITTED.value,
    Availability.ACTIVE.value,
    Availability.RECONCILE_REQUIRED.value,
})


class AccountCatalog:
    def __init__(self, path: Path, *, agent_id: str, identity_ttl_sec: float = 120.0):
        self.path = Path(path)
        self.agent_id = agent_id
        self.identity_ttl_sec = identity_ttl_sec
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self.db.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
            except BaseException:
                try:
                    self.db.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            else:
                self.db.execute("COMMIT")

    def _migrate(self) -> None:
        with self._lock:
            current = 0
            try:
                row = self.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                current = int(row[0]) if row else 0
            except sqlite3.DatabaseError:
                current = 0
            if current > SCHEMA_VERSION:
                raise CatalogError(f"catalog schema {current} is newer than this program")
            if current == SCHEMA_VERSION:
                self._ensure_vault_column()
                return
            backup = self.path.with_suffix(self.path.suffix + f".v{current}.bak")
            if self.path.is_file() and self.path.stat().st_size and not backup.is_file():
                self._backup_to(backup)
            self.db.executescript(_SCHEMA)
            self.db.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )
            self._ensure_vault_column()

    def _ensure_vault_column(self) -> None:
        cols = {row[1] for row in self.db.execute("PRAGMA table_info(accounts)").fetchall()}
        if cols and "vault_present" not in cols:
            self.db.execute("ALTER TABLE accounts ADD COLUMN vault_present INTEGER NOT NULL DEFAULT 1")

    def sync_logins(self, index_logins: list[str], vault_logins: list[str] | None = None) -> list[str]:
        """Link catalog rows to vault-index logins. Never deletes a row automatically."""
        if vault_logins is None:
            vault = {item.strip().lower() for item in index_logins if item.strip()}
        else:
            vault = {item.strip().lower() for item in vault_logins if item.strip()}
        issues: list[str] = []
        seen: set[str] = set()
        with self._tx():
            self.db.execute("DELETE FROM sync_issues")
            for raw in index_logins:
                login = raw.strip()
                if not login:
                    continue
                key = login.lower()
                if key in seen:
                    issues.append(f"duplicate_login:{login}")
                    self._issue(login, "duplicate_login")
                    continue
                seen.add(key)
                if key not in vault:
                    issues.append(f"index_without_vault:{login}")
                    self._issue(login, "index_without_vault")
                present = 1 if key in vault else 0
                row = self.db.execute(
                    "SELECT local_account_id, login, vault_present FROM accounts WHERE login = ? COLLATE NOCASE",
                    (login,),
                ).fetchone()
                if row is None:
                    self.db.execute(
                        "INSERT INTO accounts(local_account_id, login, binding_status, availability_status,"
                        " vault_present, updated_at) VALUES(?,?,?,?,?,?)",
                        (uuid.uuid4().hex, login, BindingStatus.UNBOUND.value, Availability.AVAILABLE.value,
                         present, time.time()),
                    )
                    self._bump_generation()
                else:
                    if int(row["vault_present"]) != present:
                        self.db.execute(
                            "UPDATE accounts SET vault_present=? WHERE local_account_id=?",
                            (present, row["local_account_id"]),
                        )
                        self._bump_generation()
                if row is not None and row["login"] != login:
                    issues.append(f"login_case_changed:{row['login']}->{login}")
                    self._issue(login, "login_case_changed")
            if vault_logins is not None:
                for login in vault_logins:
                    if login.strip() and login.strip().lower() not in seen:
                        issues.append(f"vault_without_index:{login.strip()}")
                        self._issue(login.strip(), "vault_without_index")
        return issues

    def sync_index_payload(self, payload: str, vault_logins: list[str] | None = None) -> list[str]:
        try:
            data = json.loads(payload)
            accounts = data.get("accounts") if isinstance(data, dict) else None
            if not isinstance(accounts, list):
                raise CatalogError("accounts index has no accounts list")
            logins = []
            for item in accounts:
                if not isinstance(item, dict) or not str(item.get("login", "")).strip():
                    raise CatalogError("accounts index entry has no login")
                logins.append(str(item["login"]))
        except (json.JSONDecodeError, CatalogError) as exc:
            with self._tx():
                self._issue("*", f"index_unreadable:{exc}")
            raise CatalogError(f"accounts index is not usable: {exc}") from exc
        return self.sync_logins(logins, vault_logins)

    def _issue(self, login: str, issue: str) -> None:
        self.db.execute(
            "INSERT INTO sync_issues(login, issue, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(login) DO UPDATE SET issue=excluded.issue, updated_at=excluded.updated_at",
            (login, issue, time.time()),
        )

    def issues(self) -> list[tuple[str, str]]:
        with self._lock:
            rows = self.db.execute("SELECT login, issue FROM sync_issues ORDER BY login").fetchall()
        return [(row["login"], row["issue"]) for row in rows]

    def accounts(self) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.db.execute("SELECT * FROM accounts ORDER BY login COLLATE NOCASE").fetchall())

    def get(self, local_account_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self.db.execute(
                "SELECT * FROM accounts WHERE local_account_id=?", (local_account_id,)
            ).fetchone()

    def by_login(self, login: str) -> sqlite3.Row | None:
        with self._lock:
            return self.db.execute(
                "SELECT * FROM accounts WHERE login = ? COLLATE NOCASE", (login.strip(),)
            ).fetchone()

    def revision(self) -> int:
        """Monotonic generation of the whole catalog, not the max account revision."""
        with self._lock:
            row = self.db.execute("SELECT value FROM meta WHERE key='catalog_generation'").fetchone()
        return int(row["value"]) if row else 0

    def _bump_generation(self) -> int:
        generation = self.revision() + 1
        self.db.execute(
            "INSERT INTO meta(key, value) VALUES('catalog_generation', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(generation),),
        )
        return generation

    def snapshot(self, *, boot_id: str = "", sequence: int = 0) -> CatalogSnapshot:
        generation = self.revision()
        views = tuple(
            CatalogAccountView(
                row["local_account_id"], row["steam_id64"], row["display_name"], bool(row["enabled"]),
                row["binding_status"], row["availability_status"], int(row["catalog_revision"]),
            )
            for row in self.accounts()
        )
        return CatalogSnapshot(
            self.agent_id, generation, views, generation, boot_id, sequence, self.vault_status(),
        )

    def vault_status(self) -> str:
        """Short diagnostic. It never includes a password, secret, or maFile."""
        for login, issue in self.issues():
            if login == "*" and issue.startswith("vault_"):
                return issue.removeprefix("vault_")
            if issue == "index_without_vault":
                return "index_without_vault"
        return "ok"

    def note_vault_status(self, code: str) -> None:
        if code not in {"missing", "bad_key", "corrupt", "unreadable"}:
            code = "unreadable"
        with self._tx():
            self._issue("*", f"vault_{code}")

    def _backup_to(self, dest: Path) -> None:
        target = sqlite3.connect(dest)
        try:
            self.db.backup(target)
        finally:
            target.close()

    def set_enabled(self, local_account_id: str, enabled: bool) -> None:
        with self._tx():
            self._touch(local_account_id, enabled=1 if enabled else 0,
                        availability_status=Availability.AVAILABLE.value if enabled else Availability.DISABLED.value)

    def remove_local(self, local_account_id: str) -> None:
        """Hide a catalog row. The vault secret is not touched."""
        with self._tx():
            row = self._require(local_account_id)
            if row["availability_status"] in _OPEN:
                raise CatalogError("cannot remove an account with an open assignment")
            self.db.execute("DELETE FROM accounts WHERE local_account_id=?", (local_account_id,))
            self._bump_generation()

    def bind(self, local_account_id: str, steam_id64: str, *, source: str = "manual",
             confirm_rebind: bool = False) -> None:
        steam_id64 = parse_steam_id64(steam_id64)
        with self._tx():
            row = self._require(local_account_id)
            previous = row["steam_id64"]
            if previous and previous != steam_id64 and not confirm_rebind:
                raise CatalogError("rebinding an existing SteamID64 needs operator confirmation")
            other = self.db.execute(
                "SELECT local_account_id FROM accounts WHERE steam_id64=? AND local_account_id<>?",
                (steam_id64, local_account_id),
            ).fetchone()
            if other is not None:
                raise CatalogError("this SteamID64 is already bound on this computer")
            status = BindingStatus.MANUALLY_BOUND.value if source == "manual" else BindingStatus.UNCONFIRMED.value
            self._touch(local_account_id, steam_id64=steam_id64, binding_status=status,
                        last_verified_at=0, last_verified_source="", last_error="")
            self.db.execute(
                "INSERT INTO binding_history(local_account_id, previous_steam_id64, steam_id64, source, created_at)"
                " VALUES(?,?,?,?,?)",
                (local_account_id, previous, steam_id64, source, time.time()),
            )

    def note_identity(self, local_account_id: str, observed_steam_id64: str, *, source: str, now: float) -> str:
        """Record a probe. A manual value or a remembered VDF name is not verification."""
        observed = observed_steam_id64.strip()
        if observed:
            observed = parse_steam_id64(observed)
        with self._tx():
            row = self._require(local_account_id)
            expected = row["steam_id64"]
            if source == "manual" or source == "loginusers":
                self._touch(local_account_id, binding_status=BindingStatus.UNCONFIRMED.value,
                            last_error="manual or remembered data is not an active login")
                return BindingStatus.UNCONFIRMED.value
            if not observed:
                status = BindingStatus.UNBOUND.value if not expected else BindingStatus.UNCONFIRMED.value
                self._touch(local_account_id, binding_status=status, last_verified_at=0,
                            last_verified_source=source, last_error="Steam identity was not observed")
                return status
            if not expected:
                self._touch(local_account_id, last_error="observed SteamID64 is not bound to this account")
                return row["binding_status"]
            if observed != expected:
                self._touch(local_account_id, binding_status=BindingStatus.MISMATCH.value,
                            last_verified_at=now, last_verified_source=source,
                            last_error=f"observed {observed}")
                return BindingStatus.MISMATCH.value
            self._touch(local_account_id, binding_status=BindingStatus.VERIFIED.value,
                        last_verified_at=now, last_verified_source=source, last_error="")
            return BindingStatus.VERIFIED.value

    def identity_fresh(self, local_account_id: str, now: float) -> bool:
        row = self.get(local_account_id)
        if row is None:
            return False
        return (
            row["binding_status"] == BindingStatus.VERIFIED.value
            and now - float(row["last_verified_at"]) <= self.identity_ttl_sec
        )

    def history(self, local_account_id: str) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.db.execute(
                "SELECT previous_steam_id64, steam_id64, source, created_at FROM binding_history "
                "WHERE local_account_id=? ORDER BY id",
                (local_account_id,),
            ).fetchall())

    def prepare(self, *, preparation_id: str, local_account_id: str, steam_id64: str,
                catalog_revision: int, generation: int, coordinator_generation: int) -> str:
        steam_id64 = parse_steam_id64(steam_id64)
        with self._tx():
            existing = self.db.execute(
                "SELECT * FROM reservations WHERE preparation_id=?", (preparation_id,)
            ).fetchone()
            if existing is not None:
                if (existing["local_account_id"] != local_account_id or existing["steam_id64"] != steam_id64
                        or int(existing["generation"]) != int(generation)):
                    raise CatalogError("preparation parameters do not match the stored reservation")
                return existing["status"]
            active = self.db.execute("SELECT preparation_id FROM active_reservation WHERE id=1").fetchone()
            if active is not None:
                raise CatalogError("this computer already has an open assignment")
            row = self._require(local_account_id)
            if not row["enabled"] or row["availability_status"] == Availability.DISABLED.value:
                raise CatalogError("account is disabled")
            if row["steam_id64"] != steam_id64:
                raise CatalogError("steam_id64 does not match the local binding")
            if int(row["catalog_revision"]) != int(catalog_revision):
                raise CatalogError("catalog revision changed")
            if row["binding_status"] == BindingStatus.UNBOUND.value:
                raise CatalogError("account has no SteamID64 binding")
            self.db.execute(
                "INSERT INTO reservations(preparation_id, local_account_id, steam_id64, catalog_revision,"
                " generation, coordinator_generation, status, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (preparation_id, local_account_id, steam_id64, catalog_revision, generation,
                 coordinator_generation, Availability.PREPARED.value, time.time()),
            )
            self.db.execute(
                "INSERT INTO active_reservation(id, preparation_id) VALUES(1, ?)", (preparation_id,)
            )
            self._touch(local_account_id, availability_status=Availability.PREPARED.value, bump=False)
            return Availability.PREPARED.value

    def commit(self, *, preparation_id: str, generation: int, run_id: str) -> str:
        with self._tx():
            row = self.db.execute(
                "SELECT * FROM reservations WHERE preparation_id=?", (preparation_id,)
            ).fetchone()
            if row is None:
                raise CatalogError("unknown preparation")
            if int(generation) != int(row["generation"]):
                raise CatalogError("assignment generation does not match")
            if row["run_id"] and row["run_id"] != run_id:
                raise CatalogError("commit run_id does not match the stored assignment")
            if row["status"] in (Availability.COMMITTED.value, Availability.ACTIVE.value) and row["run_id"] == run_id:
                return row["status"]
            if row["status"] not in (Availability.PREPARED.value, Availability.RECONCILE_REQUIRED.value,
                                     Availability.COMMITTED.value):
                raise CatalogError(f"cannot commit from {row['status']}")
            self.db.execute(
                "UPDATE reservations SET status=?, generation=?, run_id=?, updated_at=? WHERE preparation_id=?",
                (Availability.COMMITTED.value, generation, run_id, time.time(), preparation_id),
            )
            self._touch(row["local_account_id"], availability_status=Availability.COMMITTED.value, bump=False)
            return Availability.COMMITTED.value

    def release(self, preparation_id: str, *, allow_active_run: bool = False) -> str:
        with self._tx():
            row = self.db.execute(
                "SELECT * FROM reservations WHERE preparation_id=?", (preparation_id,)
            ).fetchone()
            if row is None:
                raise CatalogError("unknown preparation is not proof that it was released")
            if row["status"] == Availability.RELEASED.value:
                return Availability.RELEASED.value
            if row["status"] == Availability.ACTIVE.value and not allow_active_run:
                raise CatalogError("cannot release an assignment that belongs to an active run")
            self.db.execute(
                "UPDATE reservations SET status=?, updated_at=? WHERE preparation_id=?",
                (Availability.RELEASED.value, time.time(), preparation_id),
            )
            self.db.execute("DELETE FROM active_reservation WHERE preparation_id=?", (preparation_id,))
            self._touch(row["local_account_id"], availability_status=Availability.AVAILABLE.value, bump=False)
            return Availability.RELEASED.value

    def mark_reconcile(self, preparation_id: str) -> None:
        with self._tx():
            row = self.db.execute(
                "SELECT local_account_id FROM reservations WHERE preparation_id=?", (preparation_id,)
            ).fetchone()
            if row is None:
                return
            self.db.execute(
                "UPDATE reservations SET status=?, updated_at=? WHERE preparation_id=?",
                (Availability.RECONCILE_REQUIRED.value, time.time(), preparation_id),
            )
            self._touch(row["local_account_id"], availability_status=Availability.RECONCILE_REQUIRED.value, bump=False)

    def active_committed(self) -> sqlite3.Row | None:
        """The reservation a restarted agent may restore. This is not an identity proof."""
        with self._lock:
            return self.db.execute(
                "SELECT r.* FROM reservations r "
                "JOIN active_reservation a ON a.preparation_id = r.preparation_id "
                "WHERE r.status IN (?, ?)",
                (Availability.COMMITTED.value, Availability.ACTIVE.value),
            ).fetchone()

    def reservation(self, preparation_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self.db.execute(
                "SELECT * FROM reservations WHERE preparation_id=?", (preparation_id,)
            ).fetchone()

    def _require(self, local_account_id: str) -> sqlite3.Row:
        row = self.db.execute(
            "SELECT * FROM accounts WHERE local_account_id=?", (local_account_id,)
        ).fetchone()
        if row is None:
            raise CatalogError("unknown local account")
        return row

    def _touch(self, local_account_id: str, *, bump: bool = True, **fields: object) -> None:
        if bump:
            current = self.db.execute(
                "SELECT catalog_revision FROM accounts WHERE local_account_id=?", (local_account_id,)
            ).fetchone()
            fields["catalog_revision"] = int(current["catalog_revision"]) + 1
            self._bump_generation()
        fields["updated_at"] = time.time()
        keys = list(fields)
        assignments = ", ".join(f"{key}=?" for key in keys)
        self.db.execute(
            f"UPDATE accounts SET {assignments} WHERE local_account_id=?",
            (*[fields[key] for key in keys], local_account_id),
        )
