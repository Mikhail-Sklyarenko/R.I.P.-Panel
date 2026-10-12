"""Catalog registration ownership after v4→v5 and after a new enrollment."""
from __future__ import annotations

import hashlib
import sqlite3

import pytest

from core.wingman_fleet import PROTOCOL_VERSION
from core.wingman_fleet.assignments import STALE_CATALOG, AssignmentBook, AssignmentError
from core.wingman_fleet.store import FleetStore
from panel.fleet_desk import FleetDesk
from tests.test_fleet_assignments import LINKS, STEAM, _book, _prepare_all, _selection
from tests.test_fleet_acceptance import _ready


_V4_TABLES = """
CREATE TABLE IF NOT EXISTS preparations(
    preparation_id TEXT PRIMARY KEY, coordinator_generation INTEGER NOT NULL,
    status TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
    run_id TEXT NOT NULL DEFAULT '', last_error TEXT NOT NULL DEFAULT '',
    plan_json TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS preparation_slots(
    preparation_id TEXT NOT NULL, slot_id INTEGER NOT NULL, agent_id TEXT NOT NULL,
    local_account_id TEXT NOT NULL, steam_id64 TEXT NOT NULL,
    expected_catalog_revision INTEGER NOT NULL, assignment_generation INTEGER NOT NULL,
    reservation_status TEXT NOT NULL, identity_observed TEXT NOT NULL DEFAULT '',
    identity_at REAL NOT NULL DEFAULT 0, verification_status TEXT NOT NULL DEFAULT 'unverified',
    verification_source TEXT NOT NULL DEFAULT '', verification_boot_id TEXT NOT NULL DEFAULT '',
    verification_generation INTEGER NOT NULL DEFAULT 0, verification_error TEXT NOT NULL DEFAULT '',
    verification_id TEXT NOT NULL DEFAULT '', verification_seq INTEGER NOT NULL DEFAULT 0,
    link_state TEXT NOT NULL DEFAULT '', PRIMARY KEY(preparation_id, slot_id));
CREATE TABLE IF NOT EXISTS assignment_events(
    id INTEGER PRIMARY KEY, preparation_id TEXT NOT NULL, status TEXT NOT NULL,
    detail TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS agent_credentials(
    agent_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
    registration_generation INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS agent_presence(
    agent_id TEXT PRIMARY KEY, boot_id TEXT NOT NULL DEFAULT '', protocol INTEGER NOT NULL DEFAULT 0,
    last_seen REAL NOT NULL DEFAULT 0, process_generation INTEGER NOT NULL DEFAULT 0,
    registration_generation INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS verification_seq(
    preparation_id TEXT NOT NULL, agent_id TEXT NOT NULL, next_seq INTEGER NOT NULL,
    PRIMARY KEY(preparation_id, agent_id));
CREATE TABLE IF NOT EXISTS catalog_heads(
    agent_id TEXT PRIMARY KEY, catalog_generation INTEGER NOT NULL,
    boot_id TEXT NOT NULL DEFAULT '', sequence INTEGER NOT NULL DEFAULT 0,
    received_at REAL NOT NULL, vault_status TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS enrollments(
    agent_id TEXT PRIMARY KEY, code_hash TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS catalog_cache(
    agent_id TEXT NOT NULL, local_account_id TEXT NOT NULL, steam_id64 TEXT NOT NULL,
    display_name TEXT NOT NULL, enabled INTEGER NOT NULL, binding_status TEXT NOT NULL,
    availability_status TEXT NOT NULL, catalog_revision INTEGER NOT NULL, received_at REAL NOT NULL,
    PRIMARY KEY(agent_id, local_account_id));
"""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _v4_database(path, *, with_reservation: bool = True) -> None:
    """A coordinator file written by schema 4, without last_sequence or catalog registration."""
    store = FleetStore(path)
    db = store.db
    db.executescript(_V4_TABLES)
    db.execute("PRAGMA user_version=4")
    for index, steam in enumerate(STEAM, start=1):
        agent = f"pc{index}"
        db.execute(
            "INSERT INTO agent_credentials(agent_id, token_hash, revoked, registration_generation) "
            "VALUES(?,?,0,1)",
            (agent, _hash(f"token-{agent}")),
        )
        db.execute(
            "INSERT INTO agent_presence(agent_id, boot_id, protocol, last_seen, process_generation, "
            "registration_generation) VALUES(?,?,?,?,1,1)",
            (agent, "boot-old", PROTOCOL_VERSION, 100.0),
        )
        db.execute(
            "INSERT INTO catalog_heads(agent_id, catalog_generation, boot_id, sequence, received_at, vault_status) "
            "VALUES(?,?,?,?,?,?)",
            (agent, 150, "boot-old", 9, 100.0, "ok"),
        )
        db.execute(
            "INSERT INTO catalog_cache(agent_id, local_account_id, steam_id64, display_name, enabled, "
            "binding_status, availability_status, catalog_revision, received_at) VALUES(?,?,?,?,1,?,?,?,?)",
            (agent, f"acc-{index}", steam, "legacy", "manually_bound", "available", 150, 100.0),
        )
    if with_reservation:
        db.execute(
            "INSERT INTO preparations(preparation_id, coordinator_generation, status, created_at, updated_at, run_id) "
            "VALUES('prep-v4',1,'committed',100,100,'run-v4')"
        )
        db.execute(
            "INSERT INTO preparation_slots(preparation_id, slot_id, agent_id, local_account_id, steam_id64, "
            "expected_catalog_revision, assignment_generation, reservation_status) VALUES(?,?,?,?,?,?,?,?)",
            ("prep-v4", 1, "pc1", "acc-1", STEAM[0], 150, 1, "committed"),
        )
    db.execute(
        "INSERT INTO operator_stops(run_id, agent_id, command_id, created_at) VALUES(?,?,?,?)",
        ("run-v4", "pc1", "stop-1", 100.0),
    )
    db.execute(
        "INSERT INTO commands(command_id, run_id, agent_id, type, command_json, issued_at, status, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        ("pending-1", "run-v4", "pc1", "prepare_assignment", "{}", 100.0, "pending", 100.0),
    )
    store.close()


def _fresh_snapshot(agent: str, steam: str, local: str, *, generation: int, registration: int,
                    boot: str = "boot-new", process: int = 1, sequence: int = 1, name: str = "fresh"):
    return {
        "agent_id": agent, "catalog_generation": generation, "registration_generation": registration,
        "boot_id": boot, "sequence": sequence, "process_generation": process,
        "accounts": [{
            "local_account_id": local, "steam_id64": steam, "display_name": name,
            "enabled": True, "binding_status": "manually_bound", "availability_status": "available",
            "catalog_revision": generation,
        }],
    }


def test_v4_head_does_not_block_the_current_registration_catalog(tmp_path):
    path = tmp_path / "v4.db"
    _v4_database(path)
    store = FleetStore(path)
    book = AssignmentBook(store, clock=lambda: 100.0)
    assert int(store.db.execute("PRAGMA user_version").fetchone()[0]) == 5
    cols = {row[1] for row in store.db.execute("PRAGMA table_info(catalog_heads)").fetchall()}
    assert "registration_generation" in cols
    presence_cols = {row[1] for row in store.db.execute("PRAGMA table_info(agent_presence)").fetchall()}
    assert "last_sequence" in presence_cols
    head = store.db.execute(
        "SELECT catalog_generation, registration_generation FROM catalog_heads WHERE agent_id='pc1'"
    ).fetchone()
    assert int(head["catalog_generation"]) == 150
    assert int(head["registration_generation"] or 0) == 0
    assert store.db.execute("SELECT COUNT(*) FROM operator_stops").fetchone()[0] == 1
    assert store.db.execute("SELECT status FROM commands WHERE command_id='pending-1'").fetchone()[0] == "pending"
    slot = store.db.execute(
        "SELECT reservation_status FROM preparation_slots WHERE preparation_id='prep-v4'"
    ).fetchone()
    assert slot["reservation_status"] == "committed"
    with pytest.raises(AssignmentError):
        book.draft(_selection(), links=LINKS)
    book.install_session(
        "pc1", process_generation=1, registration_generation=1, boot_id="boot-new",
        protocol=PROTOCOL_VERSION, seen_at=100.0, sequence=1,
    )
    book.remember_catalog("pc1", _fresh_snapshot("pc1", STEAM[0], "acc-1", generation=1, registration=1))
    head = store.db.execute(
        "SELECT catalog_generation, registration_generation, display_name FROM catalog_heads "
        "JOIN catalog_cache USING(agent_id) WHERE agent_id='pc1'"
    ).fetchone()
    assert int(head["catalog_generation"]) == 1
    assert int(head["registration_generation"]) == 1
    assert head["display_name"] == "fresh"
    book.remember_catalog("pc1", _fresh_snapshot(
        "pc1", STEAM[0], "acc-1", generation=200, registration=0, name="old-reg",
    ))
    assert store.db.execute(
        "SELECT display_name FROM catalog_cache WHERE agent_id='pc1'"
    ).fetchone()[0] == "fresh"
    store.close()


def test_inherited_catalog_is_not_used_for_prepare_until_replaced(tmp_path):
    path = tmp_path / "v4.db"
    _v4_database(path, with_reservation=False)
    store = FleetStore(path)
    book = AssignmentBook(store, clock=lambda: 100.0)
    for index in range(1, 5):
        book.note_presence(f"pc{index}", protocol=PROTOCOL_VERSION, seen_at=100.0, boot_id="boot-old",
                           process_generation=1, registration_generation=1)
    with pytest.raises(AssignmentError, match="устарел"):
        book.draft(_selection(), links=LINKS)
    for index, steam in enumerate(STEAM, start=1):
        agent = f"pc{index}"
        book.install_session(
            agent, process_generation=1, registration_generation=1, boot_id="boot-new",
            protocol=PROTOCOL_VERSION, seen_at=100.0, sequence=index,
        )
        book.remember_catalog(agent, _fresh_snapshot(
            agent, steam, f"acc-{index}", generation=1, registration=1, sequence=index,
        ))
    rows = _selection()
    for row in rows:
        row["expected_catalog_revision"] = 1
    prep = book.draft(rows, links=LINKS)
    _prepare_all(book, prep)
    assert book.status(prep)["status"] == "prepared"
    store.close()


def test_wrong_boot_or_process_does_not_replace_an_inherited_head(tmp_path):
    path = tmp_path / "v4.db"
    _v4_database(path)
    store = FleetStore(path)
    book = AssignmentBook(store, clock=lambda: 100.0)
    book.install_session(
        "pc1", process_generation=2, registration_generation=1, boot_id="boot-live",
        protocol=PROTOCOL_VERSION, seen_at=100.0, sequence=4,
    )
    book.remember_catalog("pc1", _fresh_snapshot(
        "pc1", STEAM[0], "acc-1", generation=1, registration=1, boot="boot-other", process=2,
    ))
    assert store.db.execute(
        "SELECT catalog_generation FROM catalog_heads WHERE agent_id='pc1'"
    ).fetchone()[0] == 150
    book.remember_catalog("pc1", _fresh_snapshot(
        "pc1", STEAM[0], "acc-1", generation=1, registration=1, boot="boot-live", process=1,
    ))
    assert store.db.execute(
        "SELECT catalog_generation FROM catalog_heads WHERE agent_id='pc1'"
    ).fetchone()[0] == 150
    book.remember_catalog("pc1", _fresh_snapshot(
        "pc1", STEAM[0], "acc-1", generation=1, registration=1, boot="boot-live", process=2,
    ))
    assert store.db.execute(
        "SELECT catalog_generation FROM catalog_heads WHERE agent_id='pc1'"
    ).fetchone()[0] == 1
    store.close()


def test_reopening_v5_and_a_newer_schema_are_safe(tmp_path):
    path = tmp_path / "v4.db"
    _v4_database(path)
    first = AssignmentBook(FleetStore(path), clock=lambda: 100.0)
    assert int(first.store.db.execute("PRAGMA user_version").fetchone()[0]) == 5
    first.store.close()
    second = AssignmentBook(FleetStore(path), clock=lambda: 100.0)
    assert int(second.store.db.execute("PRAGMA user_version").fetchone()[0]) == 5
    assert second.store.db.execute("SELECT COUNT(*) FROM operator_stops").fetchone()[0] == 1
    second.store.db.execute("PRAGMA user_version=6")
    second.store.close()
    with pytest.raises(AssignmentError, match="newer"):
        AssignmentBook(FleetStore(path), clock=lambda: 100.0)


def test_previous_registration_catalog_cannot_be_selected_or_prepared(tmp_path):
    book = _book(tmp_path)
    desk = FleetDesk(book)
    assert desk.accounts_for("pc1")
    book.revoke_agent("pc1")
    book.register_agent("pc1", "token-pc1-next")
    book.note_presence("pc1", protocol=PROTOCOL_VERSION, seen_at=100.0)
    assert book.registration_generation("pc1") == 2
    assert desk.accounts_for("pc1") == []
    assert desk.choose(1, "pc1", "acc-1") == STALE_CATALOG
    with pytest.raises(AssignmentError, match="устарел"):
        book.draft(_selection(), links=LINKS)
    snapshot = _fresh_snapshot("pc1", STEAM[0], "acc-1", generation=1, registration=2, name="regen")
    book.remember_catalog("pc1", snapshot)
    book.remember_catalog("pc1", snapshot)
    names = [item["display_name"] for item in desk.accounts_for("pc1")]
    assert names == ["regen"]
    book.remember_catalog("pc1", _fresh_snapshot(
        "pc1", STEAM[0], "acc-1", generation=9, registration=1, name="late-old",
    ))
    assert desk.accounts_for("pc1")[0]["display_name"] == "regen"
    book.store.close()


def test_registration_change_between_choose_and_prepare_is_rejected(tmp_path):
    book = _book(tmp_path)
    desk = FleetDesk(book)
    assert desk.choose(1, "pc1", "acc-1") == "acc-1"
    for slot in range(2, 5):
        desk.choose(slot, f"pc{slot}", f"acc-{slot}")
    book.revoke_agent("pc2")
    book.register_agent("pc2", "token-pc2-next")
    book.note_presence("pc2", protocol=PROTOCOL_VERSION, seen_at=100.0)
    assert desk.prepare(links=LINKS) == ""
    assert "устарел" in desk.error
    book.store.close()


def test_unknown_account_is_not_replaced_by_another(tmp_path):
    book = _book(tmp_path)
    desk = FleetDesk(book)
    assert "не найден" in desk.choose(1, "pc1", "missing")
    assert 1 not in desk.selection
    assert desk.accounts_for("pc2")[0]["local_account_id"] == "acc-2"
    book.store.close()


def test_agent_catalog_cannot_be_used_for_another_agent(tmp_path):
    book = _book(tmp_path)
    desk = FleetDesk(book)
    assert "не найден" in desk.choose(1, "pc1", "acc-2")
    with pytest.raises(AssignmentError):
        stolen = _selection()
        stolen[0]["local_account_id"] = "acc-2"
        book.draft(stolen, links=LINKS)
    book.store.close()


def test_disabled_account_and_empty_new_catalog_are_not_assignable(tmp_path):
    book = _book(tmp_path)
    book.remember_catalog("pc3", {
        "agent_id": "pc3", "catalog_generation": 4, "registration_generation": 1,
        "accounts": [{
            "local_account_id": "acc-3", "steam_id64": STEAM[2], "display_name": "pc3",
            "enabled": False, "binding_status": "manually_bound", "availability_status": "disabled",
        }],
    })
    desk = FleetDesk(book)
    assert desk.accounts_for("pc3") == []
    book.revoke_agent("pc4")
    book.register_agent("pc4", "token-pc4-next")
    book.remember_catalog("pc4", {
        "agent_id": "pc4", "catalog_generation": 1, "registration_generation": 2, "accounts": [],
    })
    assert desk.accounts_for("pc4") == []
    with pytest.raises(AssignmentError):
        book.draft(_selection(), links=LINKS)
    book.store.close()


def test_re_enrollment_keeps_committed_and_does_not_restore_ready(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    for index, steam in enumerate(STEAM, start=1):
        book.note_identity(prep, f"pc{index}", steam, now=100.0, fresh=True, source="gsi")
    assert book.ready(prep, now=100.0) is True
    book.revoke_agent("pc1")
    book.register_agent("pc1", "token-pc1-next")
    slot = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")
    assert slot["reservation_status"] == "committed"
    assert book.ready(prep, now=100.0) is False
    book.store.close()


def test_sqlite_backup_reads_the_migrated_file(tmp_path):
    path = tmp_path / "v4.db"
    _v4_database(path)
    book = AssignmentBook(FleetStore(path), clock=lambda: 100.0)
    assert book.store.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    copy = tmp_path / "backup.db"
    dest = sqlite3.connect(str(copy))
    book.store.db.backup(dest)
    dest.close()
    restored = sqlite3.connect(str(copy))
    restored.row_factory = sqlite3.Row
    assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert int(restored.execute("PRAGMA user_version").fetchone()[0]) == 5
    assert restored.execute("SELECT COUNT(*) FROM operator_stops").fetchone()[0] == 1
    assert restored.execute(
        "SELECT reservation_status FROM preparation_slots WHERE preparation_id='prep-v4'"
    ).fetchone()[0] == "committed"
    restored.close()
    book.store.close()


def test_same_registration_still_rejects_a_lower_catalog_generation(tmp_path):
    book = _book(tmp_path)
    book.remember_catalog("pc1", _fresh_snapshot(
        "pc1", STEAM[0], "acc-1", generation=8, registration=1, name="eight",
    ))
    book.remember_catalog("pc1", _fresh_snapshot(
        "pc1", STEAM[0], "acc-1", generation=1, registration=1, name="one",
    ))
    assert book.store.db.execute(
        "SELECT catalog_generation, display_name FROM catalog_heads JOIN catalog_cache USING(agent_id) "
        "WHERE agent_id='pc1'"
    ).fetchone()[0] == 8
    book.store.close()
