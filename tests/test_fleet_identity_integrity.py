"""Reproducing tests for identity integrity, result status, heartbeat sequence, and registration catalogs."""
from __future__ import annotations

import json
import sqlite3

import pytest

from core.wingman_fleet.accounts import BindingStatus
from core.wingman_fleet.assignments import AssignmentBook, AssignmentError
from core.wingman_fleet.coordinator import Coordinator
from core.wingman_fleet.models import Command, CommandResult, CommandType, Observation, ResultStatus, to_dict
from core.wingman_fleet.roster import FleetRoster
from core.wingman_fleet.store import FleetStore
from modules.fleet_accounts.catalog import AccountCatalog
from modules.fleet_agent.identity import STEAMID64_BASE, Identity, IdentityProbe, SteamIdentity
from modules.fleet_agent.journal import CommandJournal
from modules.fleet_agent.service import AgentService
from modules.fleet_agent.transport import InProcessTransport
from tests.test_fleet_acceptance import _Quiet, _ready
from tests.test_fleet_assignments import STEAM, _book
from tests.test_wingman_fleet_fsm import TOKEN


def _probe(registry_account: int, gsi: str = "", *, fresh: bool = False, expected: str = ""):
    return IdentityProbe(registry=lambda: (registry_account, "")).probe(
        gsi_steam_id64=gsi, gsi_fresh=fresh, expected_steam_id64=expected,
    )


def _local_catalog(tmp_path, steam: str) -> tuple[AccountCatalog, str]:
    catalog = AccountCatalog(tmp_path / "pc1-catalog.db", agent_id="pc1")
    catalog.sync_logins(["chosen"], ["chosen"])
    local = catalog.by_login("chosen")["local_account_id"]
    catalog.bind(local, steam)
    return catalog, local


def _verify_through_fleet(tmp_path, *, registry_account: int, gsi: str, gsi_fresh: bool, expected: str):
    """One real probe, then VERIFY through the agent, catalog, journal, and coordinator."""
    book = _book(tmp_path)
    prep = _ready(book)
    catalog, local = _local_catalog(tmp_path, expected)
    measured = _probe(registry_account, gsi, fresh=gsi_fresh, expected=expected)
    command = Command(
        f"{prep}/verify/chain/pc1", prep, "pc1", CommandType.VERIFY_ASSIGNMENT,
        {"preparation_id": prep, "local_account_id": local, "steam_id64": expected,
         "generation": 1, "seq": 1, "verification_id": "chain"},
        "", 1, 240.0, 100.0,
    )
    book.store.add_commands([command])
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    agent = AgentService(
        "pc1", _Quiet(), InProcessTransport(coord), CommandJournal(tmp_path / "j.db"),
        token=TOKEN, build_version="b", resource_manifest="m", inline=True,
        agent_token="token-pc1", catalog=catalog, registration_generation=1,
    )
    agent.identity_probe = lambda: measured
    agent._accept(command, 100.0)
    stored = agent.journal.unacked()
    assert stored, "VERIFY did not reach the journal"
    for index, steam in enumerate(STEAM[1:], start=2):
        book.note_identity(prep, f"pc{index}", steam, now=100.0, fresh=True, source="gsi", boot_id=f"boot-{index}")
    code, body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": agent.boot_id, "agent_token": "token-pc1",
        "process_generation": agent.process_generation, "registration_generation": 1,
        "observation": to_dict(Observation("pc1", 1)),
        "results": [to_dict(stored[0])],
    })
    assert code == 200 and command.command_id in body["accepted_results"]
    slot = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")
    return measured, catalog.get(local)["binding_status"], slot["verification_status"], book.ready(prep, now=100.0)


def test_registry_b_and_fresh_gsi_matching_expected_is_not_ready(tmp_path):
    measured, local_status, book_status, ready = _verify_through_fleet(
        tmp_path, registry_account=int(STEAM[1]) - STEAMID64_BASE, gsi=STEAM[0], gsi_fresh=True, expected=STEAM[0],
    )
    assert measured.identity is Identity.MISMATCH
    assert local_status != BindingStatus.VERIFIED.value
    assert book_status != "verified"
    assert ready is False


def test_agreeing_sources_verify_and_a_real_conflict_does_not(tmp_path):
    measured, local_status, book_status, ready = _verify_through_fleet(
        tmp_path, registry_account=int(STEAM[0]) - STEAMID64_BASE, gsi=STEAM[0], gsi_fresh=True, expected=STEAM[0],
    )
    assert measured.identity is Identity.GSI
    assert local_status == BindingStatus.VERIFIED.value
    assert book_status == "verified"
    assert ready is True


def test_failed_result_with_fresh_matching_evidence_does_not_keep_ready(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    book.note_boot("pc1", "boot-a")
    for index, steam in enumerate(STEAM, start=1):
        book.note_identity(
            prep, f"pc{index}", steam, now=100.0, fresh=True, source="gsi", boot_id="boot-a", seq=1,
        )
    assert book.ready(prep, now=100.0) is True
    command = Command(
        f"{prep}/verify/failed/pc1", prep, "pc1", CommandType.VERIFY_ASSIGNMENT,
        {"preparation_id": prep, "generation": 1, "seq": 2, "verification_id": "failed"},
        "", 1, 240.0, 100.0,
    )
    book.store.add_commands([command])
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    failed = CommandResult(command.command_id, ResultStatus.FAILED, "command_failed", evidence={
        "status": "verified", "identity_status": "gsi", "observed_steam_id64": STEAM[0],
        "source": "gsi", "fresh": True, "verification_id": "failed",
        "boot_id": "boot-a", "process_generation": 1,
    })
    code, body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": "boot-a", "agent_token": "token-pc1",
        "process_generation": 1, "registration_generation": 1,
        "observation": to_dict(Observation("pc1", 1)),
        "results": [to_dict(failed)],
    })
    assert code == 200 and command.command_id in body["accepted_results"]
    slot = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")
    assert slot["verification_status"] != "verified"
    assert book.ready(prep, now=100.0) is False
    book.store.close()


def test_heartbeat_sequence_survives_coordinator_restart(tmp_path):
    book = _book(tmp_path)
    path = book.store.path
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    first = {
        "token": TOKEN, "boot_id": "boot-a", "agent_token": "token-pc1",
        "process_generation": 1, "registration_generation": 1,
        "observation": to_dict(Observation("pc1", 100)),
    }
    assert coord.handle_heartbeat(first)[0] == 200
    book.store.close()
    store = FleetStore(path)
    restored = Coordinator(store, token=TOKEN, clock=lambda: 100.0)
    restored.assignments = AssignmentBook(store, clock=lambda: 100.0)
    late = dict(first)
    late["observation"] = to_dict(Observation("pc1", 99))
    code, body = restored.handle_heartbeat(late)
    assert code == 409 and body["commands"] == []
    same = dict(first)
    same["observation"] = to_dict(Observation("pc1", 100))
    assert restored.handle_heartbeat(same)[0] == 409
    nxt = dict(first)
    nxt["observation"] = to_dict(Observation("pc1", 101))
    assert restored.handle_heartbeat(nxt)[0] == 200
    store.close()


def test_new_registration_accepts_a_lower_catalog_generation(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    for index, steam in enumerate(STEAM, start=1):
        book.note_identity(prep, f"pc{index}", steam, now=100.0, fresh=True, source="gsi")
    assert book.ready(prep, now=100.0) is True
    old = {
        "agent_id": "pc1", "catalog_generation": 150, "boot_id": "boot-a", "sequence": 1,
        "registration_generation": 1,
        "accounts": [{
            "local_account_id": "acc-1", "steam_id64": STEAM[0], "display_name": "old",
            "enabled": True, "binding_status": "manually_bound", "availability_status": "available",
        }],
    }
    book.remember_catalog("pc1", old)
    same_registration = dict(old, catalog_generation=1)
    same_registration["accounts"] = [dict(old["accounts"][0], display_name="rejected")]
    book.remember_catalog("pc1", same_registration)
    assert book.store.db.execute(
        "SELECT display_name FROM catalog_cache WHERE agent_id='pc1' AND local_account_id='acc-1'"
    ).fetchone()[0] == "old"
    book.revoke_agent("pc1")
    book.register_agent("pc1", "token-pc1-next")
    assert book.registration_generation("pc1") == 2
    assert book.ready(prep, now=100.0) is False
    fresh = dict(old, catalog_generation=1, registration_generation=2, boot_id="boot-b")
    fresh["accounts"] = [dict(old["accounts"][0], display_name="fresh")]
    book.remember_catalog("pc1", fresh)
    assert book.store.db.execute(
        "SELECT display_name FROM catalog_cache WHERE agent_id='pc1' AND local_account_id='acc-1'"
    ).fetchone()[0] == "fresh"
    stale = dict(old, catalog_generation=200, registration_generation=1)
    stale["accounts"] = [dict(old["accounts"][0], display_name="stale-registration")]
    book.remember_catalog("pc1", stale)
    assert book.store.db.execute(
        "SELECT display_name FROM catalog_cache WHERE agent_id='pc1' AND local_account_id='acc-1'"
    ).fetchone()[0] == "fresh"
    assert book.ready(prep, now=100.0) is False
    slot = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")
    assert slot["reservation_status"] == "committed"
    assert slot["verification_status"] != "verified"
    book.store.close()


def _account(steam_id64: str) -> int:
    return int(steam_id64) - STEAMID64_BASE


def test_identity_matrix_reaches_ready_only_for_a_single_fresh_source(tmp_path):
    cases = [
        ("agree", _account(STEAM[0]), STEAM[0], True, Identity.GSI, True),
        ("registry-a-gsi-b", _account(STEAM[0]), STEAM[1], True, Identity.MISMATCH, False),
        ("registry-b-gsi-b", _account(STEAM[1]), STEAM[1], True, Identity.MISMATCH, False),
        ("stale-gsi", _account(STEAM[0]), STEAM[1], False, Identity.STEAM_LOCAL, True),
        ("gsi-only", 0, STEAM[0], True, Identity.GSI, True),
        ("neither", 0, "", False, Identity.UNCONFIRMED, False),
    ]
    for name, registry, gsi, fresh, identity, ready in cases:
        measured, local_status, book_status, is_ready = _verify_through_fleet(
            tmp_path / name, registry_account=registry, gsi=gsi, gsi_fresh=fresh, expected=STEAM[0],
        )
        assert measured.identity is identity, name
        if ready:
            assert local_status == BindingStatus.VERIFIED.value, name
            assert book_status == "verified", name
            assert is_ready is True, name
        else:
            assert local_status != BindingStatus.VERIFIED.value, name
            assert book_status != "verified", name
            assert is_ready is False, name


def _armed(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    book.note_boot("pc1", "boot-a")
    for index, steam in enumerate(STEAM, start=1):
        book.note_identity(
            prep, f"pc{index}", steam, now=100.0, fresh=True, source="gsi", boot_id="boot-a", seq=1,
        )
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    return book, prep, coord


def _proof(steam: str = STEAM[0], **overrides) -> dict:
    evidence = {
        "status": "verified", "identity_status": "gsi", "observed_steam_id64": steam,
        "source": "gsi", "fresh": True, "verification_id": "proof",
        "boot_id": "boot-a", "process_generation": 1,
    }
    evidence.update(overrides)
    return evidence


def _deliver(book, coord, status: ResultStatus, evidence: dict, *, seq: int, obs_seq: int,
             verification_id: str, agent_id: str = "pc1"):
    prep = book.current()
    command = Command(
        f"{prep}/verify/{verification_id}/{agent_id}", prep, agent_id, CommandType.VERIFY_ASSIGNMENT,
        {"preparation_id": prep, "generation": 1, "seq": seq, "verification_id": verification_id,
         "local_account_id": "acc-1", "steam_id64": STEAM[0]},
        "", 1, 240.0, 100.0,
    )
    book.store.add_commands([command])
    result = CommandResult(command.command_id, status, evidence=evidence)
    code, body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": evidence.get("boot_id") or "boot-a", "agent_token": f"token-{agent_id}",
        "process_generation": int(evidence.get("process_generation") or 1), "registration_generation": 1,
        "observation": to_dict(Observation(agent_id, obs_seq)),
        "results": [to_dict(result)],
    })
    return code, body, command


def test_terminal_status_gates_identity_and_a_replay_cannot_restore_ready(tmp_path):
    book, prep, coord = _armed(tmp_path)
    assert book.ready(prep, now=100.0) is True
    cursor = 2
    blocked = [
        (ResultStatus.FAILED, _proof(verification_id="failed"), 2, "failed"),
        (ResultStatus.UNCONFIRMED, _proof(verification_id="unconfirmed"), 2, "unconfirmed"),
        (ResultStatus.EXPIRED, _proof(verification_id="expired"), 2, "expired"),
        (ResultStatus.REJECTED, _proof(verification_id="rejected"), 2, "rejected"),
        (ResultStatus.COMPLETED, _proof(identity_status="mismatch", status="mismatch", source="conflict",
                                        verification_id="conflict"), 2, "conflict"),
        (ResultStatus.COMPLETED, _proof(identity_status="unconfirmed", status="verified", source="unconfirmed",
                                        fresh=True, verification_id="blank"), 2, "blank"),
        (ResultStatus.COMPLETED, _proof(identity_status="gsi", status="verified", source="conflict",
                                        verification_id="contradiction"), 2, "contradiction"),
        (ResultStatus.COMPLETED, _proof(identity_status="gsi", status="verified", source="manual",
                                        verification_id="manual"), 2, "manual"),
        (ResultStatus.COMPLETED, _proof(identity_status="gsi", status="verified", source="loginusers",
                                        verification_id="loginusers"), 2, "loginusers"),
    ]
    for index, (status, evidence, _seq, name) in enumerate(blocked, start=1):
        code, body, command = _deliver(
            book, coord, status, evidence, seq=cursor, obs_seq=index, verification_id=evidence["verification_id"],
        )
        slot = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")
        if status is ResultStatus.COMPLETED and evidence["identity_status"] == "mismatch":
            assert slot["verification_status"] == "mismatch", name
        else:
            assert slot["verification_status"] != "verified", name
        assert book.ready(prep, now=100.0) is False, name
        assert code == 200 and command.command_id in body["accepted_results"], name
        cursor += 1
        book.note_identity(
            prep, "pc1", STEAM[0], now=100.0, fresh=True, source="gsi", boot_id="boot-a", seq=cursor,
        )
        cursor += 1
    code, body, command = _deliver(
        book, coord, ResultStatus.ACCEPTED, _proof(verification_id="accepted"),
        seq=30, obs_seq=40, verification_id="accepted",
    )
    assert command.command_id not in body["accepted_results"]
    book.note_identity(prep, "pc1", STEAM[0], now=100.0, fresh=True, source="gsi", boot_id="boot-a", seq=31)
    assert book.ready(prep, now=100.0) is True
    code, body, failed = _deliver(
        book, coord, ResultStatus.FAILED, _proof(verification_id="newer-failed"),
        seq=32, obs_seq=41, verification_id="newer-failed",
    )
    assert code == 200 and failed.command_id in body["accepted_results"]
    assert book.ready(prep, now=100.0) is False
    events = len(book.events(prep))
    again, replay_body, _same = _deliver(
        book, coord, ResultStatus.FAILED, _proof(verification_id="newer-failed"),
        seq=32, obs_seq=42, verification_id="newer-failed",
    )
    assert again == 409 or failed.command_id in replay_body.get("accepted_results", [])
    if again == 200:
        assert len(book.events(prep)) == events
    assert book.ready(prep, now=100.0) is False
    code, body, old = _deliver(
        book, coord, ResultStatus.COMPLETED, _proof(verification_id="old-completed"),
        seq=31, obs_seq=43, verification_id="old-completed",
    )
    assert book.ready(prep, now=100.0) is False
    slot = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")
    assert slot["verification_status"] != "verified"
    book.store.close()


def test_already_applied_does_not_restore_ready(tmp_path):
    book, prep, coord = _armed(tmp_path)
    code, body, failed = _deliver(
        book, coord, ResultStatus.FAILED, _proof(verification_id="gone"),
        seq=2, obs_seq=1, verification_id="gone",
    )
    assert code == 200 and failed.command_id in body["accepted_results"]
    assert book.ready(prep, now=100.0) is False
    code, body, replay = _deliver(
        book, coord, ResultStatus.ALREADY_APPLIED, _proof(verification_id="replayed"),
        seq=3, obs_seq=2, verification_id="replayed",
    )
    assert code == 200 and replay.command_id in body["accepted_results"]
    slot = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")
    assert slot["verification_status"] != "verified"
    assert book.ready(prep, now=100.0) is False
    book.store.close()


def test_cancel_during_verify_clears_the_local_catalog_and_the_coordinator(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    catalog, local = _local_catalog(tmp_path, STEAM[0])
    command = Command(
        f"{prep}/verify/cancel/pc1", prep, "pc1", CommandType.VERIFY_ASSIGNMENT,
        {"preparation_id": prep, "local_account_id": local, "steam_id64": STEAM[0],
         "generation": 1, "seq": 1, "verification_id": "cancel"},
        "", 1, 240.0, 100.0,
    )
    book.store.add_commands([command])
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    agent = AgentService(
        "pc1", _Quiet(), InProcessTransport(coord), CommandJournal(tmp_path / "j.db"),
        token=TOKEN, build_version="b", resource_manifest="m", inline=True,
        agent_token="token-pc1", catalog=catalog, registration_generation=1,
    )

    def probe():
        agent.cancel.set()
        return SteamIdentity(Identity.GSI, STEAM[0])

    agent.identity_probe = probe
    agent._accept(command, 100.0)
    stored = agent.journal.unacked()
    assert stored[0].status is ResultStatus.UNCONFIRMED
    assert catalog.get(local)["binding_status"] != BindingStatus.VERIFIED.value
    for index, steam in enumerate(STEAM[1:], start=2):
        book.note_identity(prep, f"pc{index}", steam, now=100.0, fresh=True, source="gsi")
    code, body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": agent.boot_id, "agent_token": "token-pc1",
        "process_generation": agent.process_generation, "registration_generation": 1,
        "observation": to_dict(Observation("pc1", 1)),
        "results": [to_dict(stored[0])],
    })
    assert code == 200 and command.command_id in body["accepted_results"]
    slot = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")
    assert slot["verification_status"] != "verified"
    assert book.ready(prep, now=100.0) is False
    book.store.close()


def test_process_generation_restarts_sequence_and_a_store_failure_rolls_back(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    for index, steam in enumerate(STEAM, start=1):
        book.note_identity(prep, f"pc{index}", steam, now=100.0, fresh=True, source="gsi", boot_id="boot-a")
    path = book.store.path
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    first = {
        "token": TOKEN, "boot_id": "boot-a", "agent_token": "token-pc1",
        "process_generation": 1, "registration_generation": 1,
        "observation": to_dict(Observation("pc1", 100)),
        "catalog": {"agent_id": "pc1", "catalog_generation": 4, "boot_id": "boot-a", "sequence": 100,
                    "accounts": [{"local_account_id": "acc-1", "steam_id64": STEAM[0], "display_name": "kept",
                                  "enabled": True, "binding_status": "manually_bound"}]},
    }
    assert coord.handle_heartbeat(first)[0] == 200
    assert book.ready(prep, now=100.0) is True
    book.store.close()
    store = FleetStore(path)
    restored = Coordinator(store, token=TOKEN, clock=lambda: 100.0)
    book = AssignmentBook(store, clock=lambda: 100.0)
    restored.assignments = book
    newer = dict(first)
    newer["process_generation"] = 2
    newer["boot_id"] = "boot-b"
    newer["observation"] = to_dict(Observation("pc1", 1))
    assert restored.handle_heartbeat(newer)[0] == 200
    older = dict(first)
    older["observation"] = to_dict(Observation("pc1", 101))
    code, body = restored.handle_heartbeat(older)
    assert code == 409 and body["commands"] == []
    assert book.ready(prep, now=100.0) is False
    real = book.note_presence

    def fail(*args, **kwargs):
        real(*args, **kwargs)
        raise sqlite3.OperationalError("disk full")

    book.note_presence = fail
    before = store.db.execute("SELECT last_sequence, boot_id FROM agent_presence WHERE agent_id='pc1'").fetchone()
    broken = dict(newer)
    broken["observation"] = to_dict(Observation("pc1", 2))
    broken["results"] = [to_dict(CommandResult("missing", ResultStatus.COMPLETED))]
    code, body = restored.handle_heartbeat(broken)
    assert code == 500 and body["error"] == "store_failed" and body["commands"] == []
    after = store.db.execute("SELECT last_sequence, boot_id FROM agent_presence WHERE agent_id='pc1'").fetchone()
    assert tuple(after) == tuple(before)
    assert restored.agents.get("pc1") is None or restored.agents["pc1"].observation.sequence != 2
    book.note_presence = real
    store.close()


def test_rejected_heartbeat_does_not_change_ready_catalog_or_commands(tmp_path):
    book, prep, coord = _armed(tmp_path)
    payload = {
        "token": TOKEN, "boot_id": "boot-a", "agent_token": "token-pc1",
        "process_generation": 1, "registration_generation": 1,
        "observation": to_dict(Observation("pc1", 5)),
    }
    assert coord.handle_heartbeat(payload)[0] == 200
    assert book.ready(prep, now=100.0) is True
    name = book.store.db.execute("SELECT display_name FROM catalog_cache WHERE agent_id='pc1'").fetchone()[0]
    seq = book.store.db.execute("SELECT verification_seq FROM preparation_slots WHERE agent_id='pc1'").fetchone()[0]
    late = dict(payload)
    late["observation"] = to_dict(Observation("pc1", 4))
    late["catalog"] = {"agent_id": "pc1", "catalog_generation": 9, "accounts": []}
    late["results"] = [to_dict(CommandResult("not-a-command", ResultStatus.COMPLETED, evidence=_proof()))]
    code, body = coord.handle_heartbeat(late)
    assert code == 409 and body["commands"] == []
    assert book.ready(prep, now=100.0) is True
    assert book.store.db.execute("SELECT display_name FROM catalog_cache WHERE agent_id='pc1'").fetchone()[0] == name
    assert book.store.db.execute(
        "SELECT verification_seq FROM preparation_slots WHERE agent_id='pc1'"
    ).fetchone()[0] == seq
    book.store.close()


def test_registration_restart_empty_catalog_and_repeat_are_safe(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    for index, steam in enumerate(STEAM, start=1):
        book.note_identity(prep, f"pc{index}", steam, now=100.0, fresh=True, source="gsi")
    snapshot = {
        "agent_id": "pc1", "catalog_generation": 150, "registration_generation": 1,
        "accounts": [{"local_account_id": "acc-1", "steam_id64": STEAM[0], "display_name": "kept",
                      "enabled": True, "binding_status": "manually_bound"}],
    }
    book.remember_catalog("pc1", snapshot)
    try:
        book.register_agent("pc1", "different-token")
    except AssignmentError:
        pass
    else:
        raise AssertionError("a second token replaced a live registration")
    assert book.store.db.execute(
        "SELECT display_name FROM catalog_cache WHERE agent_id='pc1' AND local_account_id='acc-1'"
    ).fetchone()[0] == "kept"
    book.register_agent("pc1", "token-pc1")
    assert book.registration_generation("pc1") == 1
    assert book.ready(prep, now=100.0) is True
    path = book.store.path
    book.store.close()
    store = FleetStore(path)
    restored = AssignmentBook(store, clock=lambda: 100.0)
    assert restored.store.db.execute(
        "SELECT display_name FROM catalog_cache WHERE agent_id='pc1' AND local_account_id='acc-1'"
    ).fetchone()[0] == "kept"
    restored.remember_catalog("pc1", dict(snapshot, catalog_generation=1))
    assert restored.store.db.execute(
        "SELECT display_name FROM catalog_cache WHERE agent_id='pc1' AND local_account_id='acc-1'"
    ).fetchone()[0] == "kept"
    restored.revoke_agent("pc1")
    restored.register_agent("pc1", "token-pc1-next")
    empty = dict(snapshot, catalog_generation=1, registration_generation=2, accounts=[])
    restored.remember_catalog("pc1", empty)
    restored.remember_catalog("pc1", empty)
    assert restored.store.db.execute(
        "SELECT COUNT(*) FROM catalog_cache WHERE agent_id='pc1'"
    ).fetchone()[0] == 0
    slot = next(row for row in restored.slots(prep) if row["agent_id"] == "pc1")
    assert slot["reservation_status"] == "committed"
    assert restored.ready(prep, now=100.0) is False
    with pytest.raises(AssignmentError):
        restored.build_run_plan(FleetRoster(), build_version="b", resource_manifest="m",
                                links={f"pc{i}": "healthy" for i in range(1, 5)})
    store.close()


def test_verified_then_mismatch_revokes_ready(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    catalog, local = _local_catalog(tmp_path, STEAM[0])
    measured = {"value": _probe(_account(STEAM[0]), STEAM[0], fresh=True, expected=STEAM[0])}
    command = Command(
        f"{prep}/verify/first/pc1", prep, "pc1", CommandType.VERIFY_ASSIGNMENT,
        {"preparation_id": prep, "local_account_id": local, "steam_id64": STEAM[0],
         "generation": 1, "seq": 1, "verification_id": "first"},
        "", 1, 240.0, 100.0,
    )
    book.store.add_commands([command])
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    agent = AgentService(
        "pc1", _Quiet(), InProcessTransport(coord), CommandJournal(tmp_path / "j.db"),
        token=TOKEN, build_version="b", resource_manifest="m", inline=True,
        agent_token="token-pc1", catalog=catalog, registration_generation=1,
    )
    agent.identity_probe = lambda: measured["value"]
    agent._accept(command, 100.0)
    for index, steam in enumerate(STEAM[1:], start=2):
        book.note_identity(prep, f"pc{index}", steam, now=100.0, fresh=True, source="gsi")
    code, body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": agent.boot_id, "agent_token": "token-pc1",
        "process_generation": agent.process_generation, "registration_generation": 1,
        "observation": to_dict(Observation("pc1", 1)),
        "results": [to_dict(agent.journal.unacked()[0])],
    })
    assert code == 200 and book.ready(prep, now=100.0) is True
    measured["value"] = _probe(_account(STEAM[1]), STEAM[0], fresh=True, expected=STEAM[0])
    second = Command(
        f"{prep}/verify/second/pc1", prep, "pc1", CommandType.VERIFY_ASSIGNMENT,
        {"preparation_id": prep, "local_account_id": local, "steam_id64": STEAM[0],
         "generation": 1, "seq": 2, "verification_id": "second"},
        "", 1, 240.0, 100.0,
    )
    book.store.add_commands([second])
    agent._accept(second, 100.0)
    assert catalog.get(local)["binding_status"] == BindingStatus.MISMATCH.value
    pending = [item for item in agent.journal.unacked() if item.command_id == second.command_id]
    code, body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": agent.boot_id, "agent_token": "token-pc1",
        "process_generation": agent.process_generation, "registration_generation": 1,
        "observation": to_dict(Observation("pc1", 2)),
        "results": [to_dict(pending[0])],
    })
    assert code == 200 and second.command_id in body["accepted_results"]
    slot = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")
    assert slot["verification_status"] == "mismatch"
    assert book.ready(prep, now=100.0) is False
    book.store.close()


def test_four_agents_lose_ready_on_conflict_and_recover_only_after_fresh_proof(tmp_path):
    store = FleetStore(tmp_path / "coord.db")
    coord = Coordinator(store, token=TOKEN, clock=lambda: 100.0)
    book = AssignmentBook(store, identity_ttl_sec=120.0, clock=lambda: 100.0)
    coord.assignments = book
    agents = []
    chosen = []
    mode = {"pc2": "ok"}

    def probe_for(agent_id: str, steam: str):
        def probe():
            if agent_id == "pc2" and mode["pc2"] == "conflict":
                return _probe(_account(STEAM[0]), steam, fresh=True, expected=steam)
            return SteamIdentity(Identity.GSI, steam)
        return probe

    for index, steam in enumerate(STEAM, start=1):
        agent_id = f"pc{index}"
        code = book.open_enrollment(agent_id)
        token = book.claim_enrollment(agent_id, code)
        catalog = AccountCatalog(tmp_path / f"{agent_id}.db", agent_id=agent_id)
        catalog.sync_logins(["skip", "chosen"], ["skip", "chosen"])
        catalog.bind(catalog.by_login("skip")["local_account_id"], str(76561197960265728 + 20 + index))
        chosen_id = catalog.by_login("chosen")["local_account_id"]
        catalog.bind(chosen_id, steam)
        agent = AgentService(
            agent_id, _Quiet(), InProcessTransport(coord), CommandJournal(tmp_path / f"{agent_id}.journal"),
            token=TOKEN, build_version="b", resource_manifest="m", inline=True, agent_token=token,
            catalog=catalog, registration_generation=book.registration_generation(agent_id),
        )
        agent.identity_probe = probe_for(agent_id, steam)
        agents.append(agent)
        chosen.append((agent_id, chosen_id, steam, int(catalog.get(chosen_id)["catalog_revision"])))
        agent.tick()
    prep = book.draft([
        {"slot_id": index, "agent_id": agent_id, "local_account_id": local_id, "steam_id64": steam,
         "expected_catalog_revision": revision}
        for index, (agent_id, local_id, steam, revision) in enumerate(chosen, start=1)
    ], links={f"pc{i}": "healthy" for i in range(1, 5)})
    book.begin_prepare(prep, {f"pc{i}": "healthy" for i in range(1, 5)})
    book.enqueue(prep, "prepare")
    for _ in range(2):
        for agent in agents:
            agent.tick()
    book.decide_commit(prep, run_id="run-e2e")
    book.enqueue(prep, "commit")
    for _ in range(2):
        for agent in agents:
            agent.tick()
    book.enqueue(prep, "verify")
    for _ in range(2):
        for agent in agents:
            agent.tick()
    links = {f"pc{i}": "healthy" for i in range(1, 5)}
    assert book.ready(prep, now=100.0, links=links) is True
    plan = book.build_run_plan(FleetRoster(), build_version="b", resource_manifest="m", links=links)
    assert plan.account_for_agent("pc2").steam_id64 == STEAM[1]
    old = store.db.execute(
        "SELECT command_id, result_json FROM commands WHERE agent_id='pc2' AND type='verify_assignment' "
        "AND status='completed' ORDER BY issued_at"
    ).fetchone()
    mode["pc2"] = "conflict"
    book.enqueue(prep, "verify")
    for _ in range(2):
        for agent in agents:
            agent.tick()
    assert book.ready(prep, now=100.0, links=links) is False
    assert agents[1].catalog.get(chosen[1][1])["binding_status"] == BindingStatus.MISMATCH.value
    with pytest.raises(AssignmentError):
        book.build_run_plan(FleetRoster(), build_version="b", resource_manifest="m", links=links)
    pc2 = agents[1]
    replay = CommandResult.from_dict(json.loads(old["result_json"]))
    pc2.sequence += 1
    code, body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": pc2.boot_id, "agent_token": pc2.agent_token,
        "process_generation": pc2.process_generation, "registration_generation": pc2.registration_generation,
        "observation": to_dict(Observation("pc2", pc2.sequence)),
        "results": [to_dict(replay)],
    })
    assert code == 200 and replay.command_id in body["accepted_results"]
    assert book.ready(prep, now=100.0, links=links) is False
    failed_id = "failed-positive"
    generation = int(next(row["assignment_generation"] for row in book.slots(prep) if row["agent_id"] == "pc2"))
    failed_command = Command(
        failed_id, prep, "pc2", CommandType.VERIFY_ASSIGNMENT,
        {"preparation_id": prep, "generation": generation, "seq": 50, "verification_id": failed_id,
         "local_account_id": chosen[1][1], "steam_id64": STEAM[1]},
        "", 1, 240.0, 100.0,
    )
    book.store.add_commands([failed_command])
    pc2.sequence += 1
    failed = CommandResult(failed_id, ResultStatus.FAILED, evidence=_proof(
        STEAM[1], verification_id=failed_id, boot_id=pc2.boot_id, process_generation=pc2.process_generation,
    ))
    code, body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": pc2.boot_id, "agent_token": pc2.agent_token,
        "process_generation": pc2.process_generation, "registration_generation": pc2.registration_generation,
        "observation": to_dict(Observation("pc2", pc2.sequence)),
        "results": [to_dict(failed)],
    })
    assert code == 200 and failed_id in body["accepted_results"]
    assert book.ready(prep, now=100.0, links=links) is False
    path = store.path
    last_sequence = pc2.sequence
    store.close()
    store = FleetStore(path)
    coord = Coordinator(store, token=TOKEN, clock=lambda: 100.0)
    book = AssignmentBook(store, identity_ttl_sec=120.0, clock=lambda: 100.0)
    coord.assignments = book
    for agent in agents:
        agent.transport = InProcessTransport(coord)
    code, body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": pc2.boot_id, "agent_token": pc2.agent_token,
        "process_generation": pc2.process_generation, "registration_generation": pc2.registration_generation,
        "observation": to_dict(Observation("pc2", last_sequence - 1)),
    })
    assert code == 409 and body["commands"] == []
    assert book.ready(prep, now=100.0, links=links) is False
    book.revoke_agent("pc2")
    enrollment = book.open_enrollment("pc2")
    new_token = book.claim_enrollment("pc2", enrollment)
    pc2.agent_token = new_token
    pc2.registration_generation = book.registration_generation("pc2")
    assert pc2.registration_generation == 2
    assert book.ready(prep, now=100.0, links=links) is False
    pc2.sequence += 1
    snapshot = pc2.catalog.snapshot(boot_id=pc2.boot_id, sequence=pc2.sequence).as_dict()
    snapshot["catalog_generation"] = 1
    snapshot["process_generation"] = pc2.process_generation
    snapshot["registration_generation"] = pc2.registration_generation
    code, body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": pc2.boot_id, "agent_token": pc2.agent_token,
        "process_generation": pc2.process_generation, "registration_generation": pc2.registration_generation,
        "observation": to_dict(Observation("pc2", pc2.sequence)),
        "catalog": snapshot,
    })
    assert code == 200
    head = store.db.execute(
        "SELECT catalog_generation, registration_generation FROM catalog_heads WHERE agent_id='pc2'"
    ).fetchone()
    assert int(head["catalog_generation"]) == 1 and int(head["registration_generation"]) == 2
    assert book.ready(prep, now=100.0, links=links) is False
    mode["pc2"] = "ok"
    book.enqueue(prep, "verify")
    for _ in range(3):
        for agent in agents:
            agent.tick()
    assert book.ready(prep, now=100.0, links=links) is True
    plan = book.build_run_plan(FleetRoster(), build_version="b", resource_manifest="m", links=links)
    assert [plan.account_for_agent(f"pc{index}").steam_id64 for index in range(1, 5)] == STEAM
    for agent in agents:
        agent.journal.close()
        agent.catalog.close()
    store.close()
