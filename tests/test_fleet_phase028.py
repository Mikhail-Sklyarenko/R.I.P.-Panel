"""Phase 02.8 message fencing. These tests describe the required contract."""
from __future__ import annotations

import json
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from core.wingman_fleet.assignments import AssignmentBook, AssignmentError
from core.wingman_fleet.coordinator import Coordinator
from core.wingman_fleet.models import (
    Command, CommandResult, CommandType, Observation, ResultStatus, to_dict,
)
from core.wingman_fleet.roster import FleetRoster
from core.wingman_fleet.store import FleetStore
from modules.fleet_accounts.catalog import AccountCatalog
from modules.fleet_agent.identity import STEAMID64_BASE, Identity, IdentityProbe, SteamIdentity
from modules.fleet_agent.journal import CommandJournal, JournalCorrupt
from modules.fleet_agent.live import WindowsBackend
from modules.fleet_agent.service import AgentService
from modules.fleet_agent.transport import InProcessTransport
from tests.test_fleet_acceptance import _Quiet, _ready
from tests.test_fleet_assignments import LINKS, STEAM, _book
from tests.test_wingman_fleet_fsm import TOKEN


def _verify_result(command_id: str, steam: str, *, boot_id: str, verification_id: str, status: str = "verified"):
    fresh = status == "verified"
    return CommandResult(command_id, ResultStatus.COMPLETED, evidence={
        "status": status,
        "observed_steam_id64": steam,
        "source": "gsi",
        "fresh": fresh,
        "verification_id": verification_id,
        "boot_id": boot_id,
        "process_generation": 1,
    })


def test_two_verifies_in_one_millisecond_get_distinct_sequences(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    assert book.enqueue(prep, "verify") == 4
    assert book.enqueue(prep, "verify") == 4
    rows = book.store.db.execute(
        "SELECT command_json FROM commands WHERE type=? ORDER BY rowid",
        (CommandType.VERIFY_ASSIGNMENT.value,),
    ).fetchall()
    import json
    seqs = [json.loads(row[0])["params"]["seq"] for row in rows if json.loads(row[0])["agent_id"] == "pc1"]
    assert len(seqs) == 2
    assert seqs[0] != seqs[1]
    assert seqs[1] > seqs[0]
    book.store.close()


def test_duplicate_terminal_verify_does_not_apply_twice(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    book.note_boot("pc1", "boot-a")
    command = Command(
        f"{prep}/verify/v1/pc1", prep, "pc1", CommandType.VERIFY_ASSIGNMENT,
        {"preparation_id": prep, "generation": 1, "seq": 1, "verification_id": "v1"},
        "", 1, 240.0, 100.0,
    )
    book.store.add_commands([command])
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    result = _verify_result(command.command_id, STEAM[0], boot_id="boot-a", verification_id="v1")
    payload = {
        "token": TOKEN, "boot_id": "boot-a", "agent_token": "token-pc1",
        "process_generation": 1, "registration_generation": 1,
        "observation": to_dict(Observation("pc1", 1)),
        "results": [to_dict(result)],
    }
    code, body = coord.handle_heartbeat(payload)
    assert code == 200 and command.command_id in body["accepted_results"]
    events = len(book.events(prep))
    observed_at = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")["identity_at"]
    payload["observation"] = to_dict(Observation("pc1", 2))
    code, body = coord.handle_heartbeat(payload)
    assert code == 200 and command.command_id in body["accepted_results"]
    assert len(book.events(prep)) == events
    assert next(row for row in book.slots(prep) if row["agent_id"] == "pc1")["identity_at"] == observed_at
    book.store.close()


def test_older_verify_cannot_restore_ready_after_a_newer_mismatch(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    for index in range(1, 5):
        book.note_boot(f"pc{index}", "boot-a")
        book.note_identity(
            prep, f"pc{index}", STEAM[index - 1], now=100.0, fresh=True, source="gsi",
            boot_id="boot-a", seq=1, generation=1, verification_id=f"v-{index}",
        )
    newer = Command(
        f"{prep}/verify/new/pc1", prep, "pc1", CommandType.VERIFY_ASSIGNMENT,
        {"preparation_id": prep, "generation": 1, "seq": 2, "verification_id": "new"},
        "", 1, 240.0, 100.0,
    )
    older = Command(
        f"{prep}/verify/old/pc1", prep, "pc1", CommandType.VERIFY_ASSIGNMENT,
        {"preparation_id": prep, "generation": 1, "seq": 1, "verification_id": "v-1"},
        "", 1, 240.0, 100.0,
    )
    book.store.add_commands([newer, older])
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    mismatch = _verify_result(newer.command_id, STEAM[1], boot_id="boot-a", verification_id="new", status="mismatch")
    code, body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": "boot-a", "agent_token": "token-pc1",
        "process_generation": 1, "registration_generation": 1,
        "observation": to_dict(Observation("pc1", 1)),
        "results": [to_dict(mismatch)],
    })
    assert code == 200 and newer.command_id in body["accepted_results"]
    assert book.ready(prep, now=100.0) is False
    late = _verify_result(older.command_id, STEAM[0], boot_id="boot-a", verification_id="v-1")
    code, body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": "boot-a", "agent_token": "token-pc1",
        "process_generation": 1, "registration_generation": 1,
        "observation": to_dict(Observation("pc1", 2)),
        "results": [to_dict(late)],
    })
    assert code == 200
    slot = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")
    assert slot["verification_status"] != "verified"
    assert book.ready(prep, now=100.0) is False
    book.store.close()


def test_stale_process_cannot_replace_a_newer_session(tmp_path):
    book = _book(tmp_path)
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    fresh = {
        "token": TOKEN, "boot_id": "boot-b", "agent_token": "token-pc1",
        "process_generation": 2, "registration_generation": 1,
        "observation": to_dict(Observation("pc1", 1)),
        "catalog": {
            "agent_id": "pc1", "catalog_generation": 3, "boot_id": "boot-b",
            "process_generation": 2, "sequence": 1,
            "accounts": [{
                "local_account_id": "acc-1", "steam_id64": STEAM[0], "display_name": "new",
                "enabled": True, "binding_status": "manually_bound", "availability_status": "available",
            }],
        },
    }
    code, body = coord.handle_heartbeat(fresh)
    assert code == 200 and body["ok"] is True
    stale = {
        "token": TOKEN, "boot_id": "boot-a", "agent_token": "token-pc1",
        "process_generation": 1, "registration_generation": 1,
        "observation": to_dict(Observation("pc1", 1501)),
        "catalog": {
            "agent_id": "pc1", "catalog_generation": 3, "boot_id": "boot-a",
            "process_generation": 1, "sequence": 1501,
            "accounts": [{
                "local_account_id": "acc-1", "steam_id64": STEAM[0], "display_name": "old",
                "enabled": True, "binding_status": "manually_bound", "availability_status": "available",
            }],
        },
    }
    code, body = coord.handle_heartbeat(stale)
    assert code == 409
    assert body.get("commands", []) == []
    name = book.store.db.execute(
        "SELECT display_name FROM catalog_cache WHERE agent_id='pc1' AND local_account_id='acc-1'"
    ).fetchone()[0]
    assert name == "new"
    presence = book.store.db.execute(
        "SELECT boot_id, process_generation FROM agent_presence WHERE agent_id='pc1'"
    ).fetchone()
    assert presence["boot_id"] == "boot-b"
    assert int(presence["process_generation"]) == 2
    book.store.close()


def test_verify_uses_the_same_fresh_gsi_snapshot_as_observe(tmp_path):
    steam_a = str(STEAMID64_BASE + 11)
    steam_b = str(STEAMID64_BASE + 22)
    backend = object.__new__(WindowsBackend)
    backend.expected = steam_a
    backend.identity = IdentityProbe(registry=lambda: (11, ""))
    backend.gsi = SimpleNamespace(view=lambda: SimpleNamespace(steam_id64=steam_b, fresh=True))
    found = backend.verify_active_identity()
    assert found.identity is Identity.MISMATCH
    assert found.steam_id64 == steam_b
    agreed = IdentityProbe(registry=lambda: (11, "")).probe(
        gsi_steam_id64=steam_b, gsi_fresh=True, expected_steam_id64=steam_a,
    )
    assert agreed.identity is Identity.MISMATCH
    stale = IdentityProbe(registry=lambda: (11, "")).probe(
        gsi_steam_id64=steam_b, gsi_fresh=False, expected_steam_id64=steam_a,
    )
    assert stale.identity is Identity.STEAM_LOCAL
    assert stale.steam_id64 == steam_a
    missing = IdentityProbe(registry=lambda: (0, "")).probe()
    assert missing.identity is Identity.UNCONFIRMED


def _session(seq: int, **extra):
    payload = {
        "token": TOKEN, "boot_id": "boot-a", "agent_token": "token-pc1",
        "process_generation": 1, "registration_generation": 1,
        "observation": to_dict(Observation("pc1", seq)),
    }
    payload.update(extra)
    return payload


def test_verify_a_match_then_verify_b_mismatch_stays_mismatch(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    book.note_boot("pc1", "boot-a")
    book.enqueue(prep, "verify")
    rows = book.store.db.execute(
        "SELECT command_id, command_json FROM commands WHERE agent_id='pc1' AND type=? ORDER BY rowid",
        (CommandType.VERIFY_ASSIGNMENT.value,),
    ).fetchall()
    import json
    first_id, first_params = rows[0][0], json.loads(rows[0][1])["params"]
    book.enqueue(prep, "verify")
    rows = book.store.db.execute(
        "SELECT command_id, command_json FROM commands WHERE agent_id='pc1' AND type=? ORDER BY rowid",
        (CommandType.VERIFY_ASSIGNMENT.value,),
    ).fetchall()
    second_id, second_params = rows[1][0], json.loads(rows[1][1])["params"]
    assert int(second_params["seq"]) > int(first_params["seq"])
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    matched = _verify_result(first_id, STEAM[0], boot_id="boot-a", verification_id=first_params["verification_id"])
    code, body = coord.handle_heartbeat(_session(1, results=[to_dict(matched)]))
    assert code == 200 and first_id in body["accepted_results"]
    clash = CommandResult(second_id, ResultStatus.COMPLETED, evidence={
        "status": "mismatch", "observed_steam_id64": STEAM[1], "source": "gsi", "fresh": True,
        "verification_id": second_params["verification_id"], "boot_id": "boot-a", "process_generation": 1,
    })
    code, body = coord.handle_heartbeat(_session(2, results=[to_dict(clash)]))
    assert code == 200 and second_id in body["accepted_results"]
    slot = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")
    assert slot["verification_status"] == "mismatch"
    replay = coord.handle_heartbeat(_session(3, results=[to_dict(matched)]))
    assert replay[0] == 200 and first_id in replay[1]["accepted_results"]
    slot = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")
    assert slot["verification_status"] == "mismatch"
    assert book.ready(prep, now=100.0) is False
    book.store.close()


def test_accepted_and_conflicting_results_do_not_move_the_book(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    book.note_boot("pc1", "boot-a")
    command = Command(
        f"{prep}/verify/once/pc1", prep, "pc1", CommandType.VERIFY_ASSIGNMENT,
        {"preparation_id": prep, "generation": 1, "seq": 1, "verification_id": "once"},
        "", 1, 240.0, 100.0,
    )
    book.store.add_commands([command])
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    accepted = CommandResult(command.command_id, ResultStatus.ACCEPTED, evidence={"status": "accepted"})
    code, body = coord.handle_heartbeat(_session(1, results=[to_dict(accepted)]))
    assert code == 200 and command.command_id not in body["accepted_results"]
    slot = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")
    assert slot["verification_status"] != "verified"
    real = _verify_result(command.command_id, STEAM[0], boot_id="boot-a", verification_id="once")
    code, body = coord.handle_heartbeat(_session(2, results=[to_dict(real)]))
    assert code == 200 and command.command_id in body["accepted_results"]
    when = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")["identity_at"]
    other = _verify_result(command.command_id, STEAM[1], boot_id="boot-a", verification_id="once")
    code, body = coord.handle_heartbeat(_session(3, results=[to_dict(other)]))
    assert code == 200 and command.command_id not in body["accepted_results"]
    slot = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")
    assert slot["verification_status"] == "verified"
    assert slot["identity_at"] == when
    book.store.close()


def test_forged_verification_id_and_old_generation_are_not_acked(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    book.note_boot("pc1", "boot-a")
    command = Command(
        f"{prep}/verify/real/pc1", prep, "pc1", CommandType.VERIFY_ASSIGNMENT,
        {"preparation_id": prep, "generation": 1, "seq": 1, "verification_id": "real"},
        "", 1, 240.0, 100.0,
    )
    stale = Command(
        f"{prep}/verify/oldgen/pc1", prep, "pc1", CommandType.VERIFY_ASSIGNMENT,
        {"preparation_id": prep, "generation": 0, "seq": 2, "verification_id": "oldgen"},
        "", 1, 240.0, 100.0,
    )
    book.store.add_commands([command, stale])
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    forged = _verify_result(command.command_id, STEAM[0], boot_id="boot-a", verification_id="forged")
    code, body = coord.handle_heartbeat(_session(1, results=[to_dict(forged)]))
    assert code == 200 and command.command_id not in body["accepted_results"]
    pending = book.store.db.execute(
        "SELECT status FROM commands WHERE command_id=?", (command.command_id,)
    ).fetchone()[0]
    assert pending == "pending"
    old = _verify_result(stale.command_id, STEAM[0], boot_id="boot-a", verification_id="oldgen")
    code, body = coord.handle_heartbeat(_session(2, results=[to_dict(old)]))
    assert code == 200 and stale.command_id not in body["accepted_results"]
    assert next(row for row in book.slots(prep) if row["agent_id"] == "pc1")["verification_status"] != "verified"
    book.store.close()


def test_verification_sequence_survives_restart_and_a_backward_clock(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    book.enqueue(prep, "verify")
    path = book.store.path
    book.store.close()
    restored = AssignmentBook(FleetStore(path), clock=lambda: 50.0)
    restored.enqueue(prep, "verify")
    import json
    rows = restored.store.db.execute(
        "SELECT command_json FROM commands WHERE agent_id='pc1' AND type=? ORDER BY rowid",
        (CommandType.VERIFY_ASSIGNMENT.value,),
    ).fetchall()
    seqs = [int(json.loads(row[0])["params"]["seq"]) for row in rows]
    assert seqs == [1, 2]
    restored.store.close()


def test_sqlite_failure_during_fold_does_not_ack(tmp_path):
    import sqlite3
    book = _book(tmp_path)
    prep = _ready(book)
    book.note_boot("pc1", "boot-a")
    command = Command(
        f"{prep}/verify/boom/pc1", prep, "pc1", CommandType.VERIFY_ASSIGNMENT,
        {"preparation_id": prep, "generation": 1, "seq": 1, "verification_id": "boom"},
        "", 1, 240.0, 100.0,
    )
    book.store.add_commands([command])
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book

    def boom(*_args, **_kwargs):
        raise sqlite3.OperationalError("injected")

    book.note_identity = boom
    result = _verify_result(command.command_id, STEAM[0], boot_id="boot-a", verification_id="boom")
    code, body = coord.handle_heartbeat(_session(1, results=[to_dict(result)]))
    assert code == 200 and command.command_id not in body["accepted_results"]
    status = book.store.db.execute(
        "SELECT status FROM commands WHERE command_id=?", (command.command_id,)
    ).fetchone()[0]
    assert status == "pending"
    book.store.close()


def test_same_generation_different_boot_is_a_conflict(tmp_path):
    book = _book(tmp_path)
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    assert coord.handle_heartbeat(_session(1))[0] == 200
    code, body = coord.handle_heartbeat(_session(1, boot_id="boot-b"))
    assert code == 409 and body["error"] == "boot_conflict"
    presence = book.store.db.execute(
        "SELECT boot_id, process_generation FROM agent_presence WHERE agent_id='pc1'"
    ).fetchone()
    assert presence["boot_id"] == "boot-a"
    assert int(presence["process_generation"]) == 1
    book.store.close()


def test_missing_generation_and_old_protocol_do_not_write(tmp_path):
    book = _book(tmp_path)
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    before = book.store.db.execute(
        "SELECT display_name FROM catalog_cache WHERE agent_id='pc1' AND local_account_id='acc-1'"
    ).fetchone()[0]
    code, body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": "boot-a", "agent_token": "token-pc1",
        "observation": to_dict(Observation("pc1", 1)),
        "catalog": {"agent_id": "pc1", "catalog_generation": 9, "boot_id": "boot-a", "sequence": 1,
                    "accounts": [{"local_account_id": "acc-1", "steam_id64": STEAM[0], "display_name": "sneak",
                                  "enabled": True, "binding_status": "manually_bound",
                                  "availability_status": "available"}]},
    })
    assert code == 400 and body["error"] == "session_rejected"
    assert "pc1" not in coord.agents
    code, body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": "boot-a", "agent_token": "token-pc1",
        "process_generation": 1, "registration_generation": 1,
        "observation": to_dict(Observation("pc1", 1, protocol=3)),
    })
    assert code == 200 and body["error"] == "protocol_mismatch" and body["commands"] == []
    name = book.store.db.execute(
        "SELECT display_name FROM catalog_cache WHERE agent_id='pc1' AND local_account_id='acc-1'"
    ).fetchone()[0]
    assert name == before
    book.store.close()


def test_reenrollment_is_required_after_a_generation_reset(tmp_path):
    book = _book(tmp_path)
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    assert coord.handle_heartbeat(_session(1, process_generation=4))[0] == 200
    assert coord.handle_heartbeat(_session(2, process_generation=1, boot_id="wiped"))[0] == 409
    book.revoke_agent("pc1")
    code, _body = coord.handle_heartbeat(_session(3, process_generation=9, boot_id="revoked"))
    assert code == 403
    book.register_agent("pc1", "token-pc1-new")
    assert book.registration_generation("pc1") == 2
    assert coord.handle_heartbeat(_session(4, agent_token="token-pc1", registration_generation=1))[0] == 403
    code, body = coord.handle_heartbeat(_session(
        1, boot_id="fresh", agent_token="token-pc1-new", process_generation=1, registration_generation=2,
    ))
    assert code == 200 and body["ok"] is True
    presence = book.store.db.execute(
        "SELECT process_generation, boot_id FROM agent_presence WHERE agent_id='pc1'"
    ).fetchone()
    assert int(presence["process_generation"]) == 1 and presence["boot_id"] == "fresh"
    book.store.close()


def test_generation_fence_survives_coordinator_restart(tmp_path):
    book = _book(tmp_path)
    path = book.store.path
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    assert coord.handle_heartbeat(_session(1, process_generation=2, boot_id="boot-b"))[0] == 200
    book.store.close()
    store = FleetStore(path)
    restored = Coordinator(store, token=TOKEN, clock=lambda: 100.0)
    restored.assignments = AssignmentBook(store, clock=lambda: 100.0)
    code, body = restored.handle_heartbeat(_session(1501, process_generation=1, boot_id="boot-a"))
    assert code == 409 and body["commands"] == []
    presence = store.db.execute(
        "SELECT boot_id, process_generation FROM agent_presence WHERE agent_id='pc1'"
    ).fetchone()
    assert presence["boot_id"] == "boot-b" and int(presence["process_generation"]) == 2
    store.close()


def test_stale_process_cannot_verify_or_receive_commands(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    book.enqueue(prep, "verify")
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    assert coord.handle_heartbeat(_session(1, process_generation=2, boot_id="boot-b"))[0] == 200
    command_id = book.store.db.execute(
        "SELECT command_id FROM commands WHERE agent_id='pc1' AND type=?",
        (CommandType.VERIFY_ASSIGNMENT.value,),
    ).fetchone()[0]
    stale = _verify_result(command_id, STEAM[0], boot_id="boot-a", verification_id="nope")
    code, body = coord.handle_heartbeat(_session(
        1501, process_generation=1, boot_id="boot-a", results=[to_dict(stale)],
    ))
    assert code == 409 and body["commands"] == []
    assert command_id not in body.get("accepted_results", [])
    slot = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")
    assert slot["verification_status"] != "verified"
    assert book.ready(prep, now=100.0) is False
    book.store.close()


def test_identity_sources_agree_or_the_probe_reports_mismatch():
    steam_a = str(STEAMID64_BASE + 11)
    steam_b = str(STEAMID64_BASE + 22)
    both = IdentityProbe(registry=lambda: (11, "")).probe(
        gsi_steam_id64=steam_a, gsi_fresh=True, expected_steam_id64=steam_a,
    )
    assert both.identity is Identity.GSI and both.steam_id64 == steam_a
    clash = IdentityProbe(registry=lambda: (11, "")).probe(
        gsi_steam_id64=steam_b, gsi_fresh=True, expected_steam_id64=steam_a,
    )
    assert clash.identity is Identity.MISMATCH and clash.steam_id64 == steam_b
    gsi_only = IdentityProbe(registry=lambda: (0, "")).probe(
        gsi_steam_id64=steam_a, gsi_fresh=True, expected_steam_id64=steam_a,
    )
    assert gsi_only.identity is Identity.GSI
    local_only = IdentityProbe(registry=lambda: (11, "")).probe(expected_steam_id64=steam_a)
    assert local_only.identity is Identity.STEAM_LOCAL and local_only.steam_id64 == steam_a
    wrong_local = IdentityProbe(registry=lambda: (22, "")).probe(expected_steam_id64=steam_a)
    assert wrong_local.identity is Identity.MISMATCH and wrong_local.steam_id64 == steam_b


def test_one_measurement_uses_one_gsi_snapshot_and_expected_is_not_proof():
    steam_a = str(STEAMID64_BASE + 11)
    steam_b = str(STEAMID64_BASE + 22)
    calls = {"n": 0}

    def view():
        calls["n"] += 1
        return SimpleNamespace(steam_id64=steam_a, fresh=True)

    backend = object.__new__(WindowsBackend)
    backend.expected = steam_a
    backend.identity = IdentityProbe(registry=lambda: (11, ""))
    backend.gsi = SimpleNamespace(view=view)
    assert backend.measure_identity().identity is Identity.GSI
    assert backend.verify_active_identity().identity is Identity.GSI
    assert calls["n"] == 2
    backend.expected = steam_b
    found = backend.measure_identity()
    assert found.identity is Identity.MISMATCH and found.steam_id64 == steam_a
    backend.expected = steam_a
    backend.gsi = None
    assert backend.measure_identity().identity is Identity.STEAM_LOCAL


def test_agent_restart_increments_generation_and_a_corrupt_counter_fails_closed(tmp_path):
    journal = CommandJournal(tmp_path / "j.db")
    first = AgentService(
        "pc1", _Quiet(), InProcessTransport(SimpleNamespace()), journal, token=TOKEN,
        build_version="b", resource_manifest="m", inline=True, registration_generation=1,
    )
    assert first.process_generation == 1
    second = AgentService(
        "pc1", _Quiet(), InProcessTransport(SimpleNamespace()), CommandJournal(tmp_path / "j.db"),
        token=TOKEN, build_version="b", resource_manifest="m", inline=True, registration_generation=1,
    )
    assert second.process_generation == 2
    journal.db.execute("UPDATE agent_session SET process_generation=-1")
    damaged = AgentService(
        "pc1", _Quiet(), InProcessTransport(SimpleNamespace()), CommandJournal(tmp_path / "j.db"),
        token=TOKEN, build_version="b", resource_manifest="m", inline=True, registration_generation=1,
    )
    assert damaged.process_generation == 0 and damaged._fail_closed is True
    assert damaged.tick() is False
    journal.close()
    second.journal.close()
    damaged.journal.close()


def test_concurrent_delivery_applies_a_terminal_result_once(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    book.note_boot("pc1", "boot-a")
    command = Command(
        f"{prep}/verify/race/pc1", prep, "pc1", CommandType.VERIFY_ASSIGNMENT,
        {"preparation_id": prep, "generation": 1, "seq": 1, "verification_id": "race"},
        "", 1, 240.0, 100.0,
    )
    book.store.add_commands([command])
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    result = _verify_result(command.command_id, STEAM[0], boot_id="boot-a", verification_id="race")
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def deliver(seq: int) -> None:
        try:
            barrier.wait(2)
            coord.handle_heartbeat(_session(seq, results=[to_dict(result)]))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=deliver, args=(1,)), threading.Thread(target=deliver, args=(2,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3)
        assert not thread.is_alive()
    assert not errors
    identities = [row for row in book.events(prep) if row[0] == "identity"]
    assert len(identities) == 1
    slot = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")
    assert slot["verification_status"] == "verified"
    book.store.close()


def test_old_journal_result_does_not_prove_the_new_process(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    command = Command(
        f"{prep}/verify/oldproc/pc1", prep, "pc1", CommandType.VERIFY_ASSIGNMENT,
        {"preparation_id": prep, "generation": 1, "seq": 1, "verification_id": "oldproc"},
        "", 1, 240.0, 100.0,
    )
    book.store.add_commands([command])
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    journal = CommandJournal(tmp_path / "j.db")
    journal.begin(command)
    journal.finish(_verify_result(command.command_id, STEAM[0], boot_id="old-boot", verification_id="oldproc"))
    agent = AgentService(
        "pc1", _Quiet(), InProcessTransport(coord), journal, token=TOKEN,
        build_version="b", resource_manifest="m", inline=True,
        agent_token="token-pc1", registration_generation=1,
    )
    assert agent.process_generation == 1
    assert agent.tick() is True
    follower = AgentService(
        "pc1", _Quiet(), InProcessTransport(coord), journal, token=TOKEN,
        build_version="b", resource_manifest="m", inline=True,
        agent_token="token-pc1", registration_generation=1,
    )
    journal.db.execute("UPDATE journal SET acked=0 WHERE command_id=?", (command.command_id,))
    assert follower.tick() is True
    slot = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")
    assert slot["verification_status"] != "verified"
    assert int(book.store.db.execute(
        "SELECT process_generation FROM agent_presence WHERE agent_id='pc1'"
    ).fetchone()[0]) == 2
    journal.close()
    book.store.close()


def test_four_agents_reject_a_stale_message_after_a_new_process(tmp_path):
    from core.wingman_fleet.roster import FleetRoster
    store = FleetStore(tmp_path / "coord.db")
    coord = Coordinator(store, token=TOKEN, clock=lambda: 100.0)
    book = AssignmentBook(store, identity_ttl_sec=120.0, clock=lambda: 100.0)
    coord.assignments = book
    agents = []
    chosen = []
    for index, steam in enumerate(STEAM, start=1):
        agent_id = f"pc{index}"
        token = book.claim_enrollment(agent_id, book.open_enrollment(agent_id))
        catalog = AccountCatalog(tmp_path / f"{agent_id}.db", agent_id=agent_id)
        catalog.sync_logins(["chosen"], ["chosen"])
        local_id = catalog.by_login("chosen")["local_account_id"]
        catalog.bind(local_id, steam)
        agent = AgentService(
            agent_id, _Quiet(), InProcessTransport(coord), CommandJournal(tmp_path / f"{agent_id}.journal"),
            token=TOKEN, build_version="b", resource_manifest="m", inline=True,
            agent_token=token, catalog=catalog, registration_generation=1,
        )
        agent.identity_probe = lambda steam=steam: SteamIdentity(Identity.GSI, steam)
        agents.append(agent)
        chosen.append((agent_id, local_id, steam, int(catalog.get(local_id)["catalog_revision"]), token, catalog))
        agent.tick()
    prep = book.draft([
        {"slot_id": index, "agent_id": agent_id, "local_account_id": local_id, "steam_id64": steam,
         "expected_catalog_revision": revision}
        for index, (agent_id, local_id, steam, revision, *_rest) in enumerate(chosen, start=1)
    ], links={f"pc{i}": "healthy" for i in range(1, 5)})
    book.begin_prepare(prep, {f"pc{i}": "healthy" for i in range(1, 5)})
    book.enqueue(prep, "prepare")
    for _ in range(2):
        for agent in agents:
            agent.tick()
    book.decide_commit(prep, run_id="run-fence")
    book.enqueue(prep, "commit")
    for _ in range(2):
        for agent in agents:
            agent.tick()
    book.enqueue(prep, "verify")
    for _ in range(2):
        for agent in agents:
            agent.tick()
    links = {agent_id: link.value for agent_id, link in coord.links().items()}
    assert book.ready(prep, now=100.0, links=links) is True
    plan = book.build_run_plan(FleetRoster(), build_version="b", resource_manifest="m", links=links)
    assert [plan.account_for_agent(f"pc{i}").steam_id64 for i in range(1, 5)] == STEAM
    saved = store.db.execute(
        "SELECT result_json FROM commands WHERE agent_id='pc1' AND type=? ORDER BY rowid",
        (CommandType.VERIFY_ASSIGNMENT.value,),
    ).fetchone()
    import json
    old_result = json.loads(saved[0])
    agents[0].identity_probe = lambda: SteamIdentity(
        Identity.MISMATCH, STEAM[1], detail="GSI disagrees with Steam",
    )
    book.enqueue(prep, "verify")
    for _ in range(2):
        for agent in agents:
            agent.tick()
    slot = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")
    assert slot["verification_status"] == "mismatch"
    assert book.ready(prep, now=100.0) is False
    code, body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": agents[0].boot_id, "agent_token": agents[0].agent_token,
        "process_generation": agents[0].process_generation, "registration_generation": 1,
        "observation": to_dict(Observation("pc1", 50)),
        "results": [old_result],
    })
    assert code == 200 and old_result["command_id"] in body["accepted_results"]
    assert next(row for row in book.slots(prep) if row["agent_id"] == "pc1")["verification_status"] == "mismatch"
    old_boot = agents[0].boot_id
    old_generation = agents[0].process_generation
    follower = AgentService(
        "pc1", _Quiet(), InProcessTransport(coord), agents[0].journal, token=TOKEN,
        build_version="b", resource_manifest="m", inline=True,
        agent_token=chosen[0][4], catalog=chosen[0][5], registration_generation=1,
    )
    follower.identity_probe = lambda: SteamIdentity(Identity.GSI, STEAM[0])
    assert follower.process_generation == old_generation + 1
    assert follower.tick() is True
    assert int(store.db.execute(
        "SELECT process_generation FROM agent_presence WHERE agent_id='pc1'"
    ).fetchone()[0]) == follower.process_generation
    display = store.db.execute(
        "SELECT display_name FROM catalog_cache WHERE agent_id='pc1'"
    ).fetchone()[0]
    code, body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": old_boot, "agent_token": follower.agent_token,
        "process_generation": old_generation, "registration_generation": 1,
        "observation": to_dict(Observation("pc1", 1501)),
        "catalog": {"agent_id": "pc1", "catalog_generation": 9, "boot_id": old_boot,
                    "process_generation": old_generation, "sequence": 1501,
                    "accounts": [{"local_account_id": chosen[0][1], "steam_id64": STEAM[0],
                                  "display_name": "stale", "enabled": True,
                                  "binding_status": "manually_bound", "availability_status": "available"}]},
        "results": [old_result],
    })
    assert code == 409 and body["commands"] == []
    assert store.db.execute(
        "SELECT display_name FROM catalog_cache WHERE agent_id='pc1'"
    ).fetchone()[0] == display
    assert store.db.execute(
        "SELECT boot_id, process_generation FROM agent_presence WHERE agent_id='pc1'"
    ).fetchone()["boot_id"] == follower.boot_id
    restarted = Coordinator(store, token=TOKEN, clock=lambda: 100.0)
    restarted.assignments = book
    assert restarted.handle_heartbeat({
        "token": TOKEN, "boot_id": old_boot, "agent_token": follower.agent_token,
        "process_generation": old_generation, "registration_generation": 1,
        "observation": to_dict(Observation("pc1", 1502)),
    })[0] == 409
    agents[0] = follower
    book.enqueue(prep, "verify")
    for _ in range(2):
        for agent in agents:
            agent.tick()
    assert book.current_ready(now=100.0) is True
    plan = book.build_run_plan(FleetRoster(), build_version="b", resource_manifest="m")
    assert [plan.account_for_agent(f"pc{i}").steam_id64 for i in range(1, 5)] == STEAM
    for agent in agents:
        agent.journal.close()
        agent.catalog.close()
    store.close()
