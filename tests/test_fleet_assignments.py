"""Four-computer assignment: fencing, idempotency, and no partial readiness."""
from __future__ import annotations

import pytest

from core.wingman_fleet.assignments import AssignmentBook, AssignmentError
from core.wingman_fleet.store import FleetStore

STEAM = [str(76561197960265728 + index) for index in range(1, 5)]
LINKS = {f"pc{index}": "healthy" for index in range(1, 5)}


def _book(tmp_path) -> AssignmentBook:
    store = FleetStore(tmp_path / "c.db")
    book = AssignmentBook(store, clock=lambda: 100.0)
    for index, steam in enumerate(STEAM, start=1):
        agent = f"pc{index}"
        book.register_agent(agent, f"token-{agent}")
        book.remember_catalog(agent, {
            "agent_id": agent,
            "catalog_revision": 3,
            "accounts": [{
                "local_account_id": f"acc-{index}",
                "steam_id64": steam,
                "display_name": agent,
                "enabled": True,
                "binding_status": "manually_bound",
                "availability_status": "available",
            }],
        })
        book.note_presence(agent, protocol=3, seen_at=100.0)
    return book


def _selection(**overrides):
    rows = []
    for index, steam in enumerate(STEAM, start=1):
        row = {
            "slot_id": index,
            "agent_id": f"pc{index}",
            "local_account_id": f"acc-{index}",
            "steam_id64": steam,
            "expected_catalog_revision": 3,
        }
        row.update(overrides.get(index, {}))
        rows.append(row)
    return rows


def _prepare_all(book: AssignmentBook, prep: str) -> None:
    book.begin_prepare(prep, LINKS)
    for index in range(1, 5):
        assert book.note_prepare(prep, f"pc{index}", ok=True) in ("preparing", "prepared")


def test_four_assignments_commit_only_after_every_agent(tmp_path):
    book = _book(tmp_path)
    prep = book.draft(_selection(), links={f"pc{i}": "healthy" for i in range(1, 5)})
    _prepare_all(book, prep)
    assert book.status(prep)["status"] == "prepared"
    assert book.ready(prep) is False
    book.decide_commit(prep, run_id="run-1")
    assert book.ready(prep) is False
    for index in range(1, 4):
        book.note_commit(prep, f"pc{index}", ok=True, generation=1)
        assert book.ready(prep) is False
    book.note_commit(prep, "pc4", ok=True, generation=1)
    for index, steam in enumerate(STEAM, start=1):
        book.note_identity(prep, f"pc{index}", steam, now=100.0, fresh=True)
    assert book.ready(prep, now=100.0) is True
    assert book.ready(prep, now=1000.0) is False
    book.store.close()


def test_duplicate_steam_agent_and_offline_are_rejected(tmp_path):
    book = _book(tmp_path)
    duplicate = _selection()
    duplicate[1]["steam_id64"] = duplicate[0]["steam_id64"]
    with pytest.raises(AssignmentError):
        book.draft(duplicate)
    same_agent = _selection()
    same_agent[1]["agent_id"] = "pc1"
    with pytest.raises(AssignmentError):
        book.draft(same_agent)
    with pytest.raises(AssignmentError):
        book.draft(_selection(), links={"pc1": "healthy", "pc2": "offline", "pc3": "healthy", "pc4": "suspect"})
    disabled = _selection()
    book.remember_catalog("pc3", {
        "agent_id": "pc3", "catalog_revision": 3,
        "accounts": [{
            "local_account_id": "acc-3", "steam_id64": STEAM[2], "display_name": "pc3",
            "enabled": False, "binding_status": "manually_bound", "availability_status": "disabled",
        }],
    })
    with pytest.raises(AssignmentError):
        book.draft(disabled)
    unbound = _selection()
    book.remember_catalog("pc3", {
        "agent_id": "pc3", "catalog_revision": 4,
        "accounts": [{
            "local_account_id": "acc-3", "steam_id64": "", "display_name": "pc3",
            "enabled": True, "binding_status": "unbound", "availability_status": "available",
        }],
    })
    unbound[2]["steam_id64"] = STEAM[2]
    unbound[2]["expected_catalog_revision"] = 4
    with pytest.raises(AssignmentError):
        book.draft(unbound)
    book.store.close()


def test_prepare_commit_and_release_are_idempotent_and_fenced(tmp_path):
    book = _book(tmp_path)
    prep = book.draft(_selection(), links=LINKS)
    book.begin_prepare(prep, LINKS)
    book.note_prepare(prep, "pc1", ok=True)
    assert book.note_prepare(prep, "pc1", ok=True) == "preparing"
    for index in range(2, 5):
        book.note_prepare(prep, f"pc{index}", ok=True)
    run_id = book.decide_commit(prep, run_id="run-9")
    assert book.decide_commit(prep, run_id="run-9") == run_id
    with pytest.raises(AssignmentError):
        book.note_commit(prep, "pc1", ok=True, generation=0)
    with pytest.raises(AssignmentError):
        book.note_commit(prep, "pc1", ok=True, generation=2)
    book.note_commit(prep, "pc1", ok=True, generation=1)
    assert book.note_commit(prep, "pc1", ok=True, generation=1) == "committed"
    with pytest.raises(AssignmentError):
        book.release(prep)
    assert book.begin_release(prep) == "aborting"
    for index in range(1, 5):
        book.note_release(prep, f"pc{index}", ok=True)
    assert book.status(prep)["status"] == "released"
    assert book.begin_release(prep) == "released"
    book.store.close()


def test_one_rejection_does_not_become_ready_and_blocks_reuse_until_release(tmp_path):
    book = _book(tmp_path)
    prep = book.draft(_selection(), links=LINKS)
    book.begin_prepare(prep, LINKS)
    book.note_prepare(prep, "pc1", ok=True)
    book.note_prepare(prep, "pc2", ok=True)
    assert book.note_prepare(prep, "pc3", ok=False, detail="disk") == "aborting"
    assert book.ready(prep) is False
    with pytest.raises(AssignmentError):
        book.draft(_selection(), links=LINKS)
    assert book.begin_release(prep) == "aborting"
    for index in range(1, 5):
        book.note_release(prep, f"pc{index}", ok=True)
    again = book.draft(_selection(), links=LINKS)
    assert again != prep
    book.store.close()


def test_commit_decision_survives_restart_without_acks(tmp_path):
    book = _book(tmp_path)
    prep = book.draft(_selection(), links=LINKS)
    _prepare_all(book, prep)
    book.decide_commit(prep, run_id="run-kept")
    path = book.store.path
    book.store.close()
    restored = AssignmentBook(FleetStore(path), clock=lambda: 100.0)
    state = restored.status(prep)
    assert state["status"] == "committed"
    assert state["run_id"] == "run-kept"
    assert restored.ready(prep) is False
    assert all(slot["reservation_status"] == "prepared" for slot in state["slots"])
    restored.store.close()


def test_stale_catalog_and_active_run_block_changes(tmp_path):
    book = _book(tmp_path)
    stale = _selection()
    stale[0]["expected_catalog_revision"] = 1
    with pytest.raises(AssignmentError):
        book.draft(stale)
    from tests.test_wingman_fleet_fsm import make_roster
    plan = make_roster().build_plan(build_version="b", resource_manifest="m", now=1.0)
    book.store.save_run(plan)
    with pytest.raises(AssignmentError):
        book.draft(_selection(), links=LINKS)
    book.store.close()


def test_agent_credentials_do_not_transfer(tmp_path):
    book = _book(tmp_path)
    book.register_agent("pc1", "token-pc1")
    assert book.authenticate("pc1", "token-pc1") is True
    assert book.authenticate("pc2", "token-pc1") is False
    with pytest.raises(AssignmentError):
        book.register_agent("pc1", "other-token")
    book.revoke_agent("pc1")
    assert book.authenticate("pc1", "token-pc1") is False
    book.store.close()


def test_identity_mismatch_never_reports_ready(tmp_path):
    book = _book(tmp_path)
    prep = book.draft(_selection(), links=LINKS)
    _prepare_all(book, prep)
    book.decide_commit(prep, run_id="run-id")
    for index in range(1, 5):
        book.note_commit(prep, f"pc{index}", ok=True, generation=1)
    book.note_identity(prep, "pc1", STEAM[1], now=100.0, fresh=True)
    for index in range(2, 5):
        book.note_identity(prep, f"pc{index}", STEAM[index - 1], now=100.0, fresh=True)
    assert book.status(prep)["status"] != "ready"
    assert book.ready(prep) is False
    book.store.close()
