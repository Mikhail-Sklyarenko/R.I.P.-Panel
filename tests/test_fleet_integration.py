"""Assignment commands travel on the existing heartbeat and do not start gameplay."""
from __future__ import annotations

from core.wingman_fleet.assignments import AssignmentBook
from core.wingman_fleet.coordinator import Coordinator
from core.wingman_fleet.models import Command, CommandResult, CommandType, Observation, ResultStatus, to_dict
from core.wingman_fleet.store import FleetStore
from modules.fleet_accounts.catalog import AccountCatalog
from panel.fleet_desk import FleetDesk
from tests.test_wingman_fleet_foundation import _Script, _service
from tests.test_wingman_fleet_fsm import TOKEN

STEAM = "76561197960265729"


def test_assignment_command_is_delivered_without_a_run_and_is_idempotent(tmp_path):
    catalog = AccountCatalog(tmp_path / "catalog.db", agent_id="pc1")
    catalog.sync_logins(["alpha"], ["alpha"])
    account = catalog.by_login("alpha")["local_account_id"]
    catalog.bind(account, STEAM)
    revision = int(catalog.get(account)["catalog_revision"])
    agent = _service(tmp_path, _Backend(), _Script(), now=[0.0])
    agent.catalog = catalog
    command = Command(
        "prep/prepare/pc1", "prep", "pc1", CommandType.PREPARE_ASSIGNMENT,
        {"preparation_id": "prep", "local_account_id": account, "steam_id64": STEAM,
         "catalog_revision": revision, "generation": 1, "coordinator_generation": 1},
        "", 1, 45.0, 1.0,
    )
    agent._accept(command, 1.0)
    agent.drain()
    agent._accept(command, 1.0)
    agent.drain()
    assert catalog.reservation("prep")["status"] == "prepared"
    assert agent.lease_attempt == ""
    catalog.close()
    agent.journal.close()


def test_coordinator_accepts_assignment_result_without_an_active_run(tmp_path):
    store = FleetStore(tmp_path / "c.db")
    coord = Coordinator(store, token=TOKEN, clock=lambda: 10.0)
    book = AssignmentBook(store, clock=lambda: 10.0)
    coord.assignments = book
    book.register_agent("pc1", "agent-secret")
    command = Command(
        "prep/prepare/pc1", "prep", "pc1", CommandType.PREPARE_ASSIGNMENT, {}, "", 1, 45.0, 10.0,
    )
    store.add_commands([command])
    denied, _ = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": "boot", "agent_token": "wrong",
        "observation": to_dict(Observation("pc1", 1)),
    })
    assert denied == 403
    code, resp = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": "boot", "agent_token": "agent-secret",
        "observation": to_dict(Observation("pc1", 1)),
    })
    assert code == 200 and resp["ok"] is True
    assert [item["command_id"] for item in resp["commands"]] == ["prep/prepare/pc1"]
    code, resp = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": "boot", "agent_token": "agent-secret",
        "observation": to_dict(Observation("pc1", 2)),
        "results": [to_dict(CommandResult("prep/prepare/pc1", ResultStatus.FAILED, "assignment_rejected", "disk"))],
    })
    assert code == 200 and "prep/prepare/pc1" in resp["accepted_results"]
    old, old_body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": "legacy", "agent_token": "agent-secret",
        "observation": to_dict(Observation("pc1", 3, protocol=2)),
    })
    assert old == 200 and old_body["ok"] is False and old_body["commands"] == []
    store.close()


def test_desk_does_not_claim_success_when_validation_fails(tmp_path):
    book = AssignmentBook(FleetStore(tmp_path / "c.db"), clock=lambda: 10.0)
    desk = FleetDesk(book)
    desk.prepare([{
        "slot_id": 1, "agent_id": "pc1", "local_account_id": "missing",
        "steam_id64": STEAM, "expected_catalog_revision": 1,
    }], {"pc1": "offline"})
    assert desk.error
    assert "ready" not in desk.notice
    assert book.current() == ""
    book.store.close()


class _Backend:
    def observe(self):
        return Observation("pc1", 1)

    def execute(self, cmd, ctx):
        raise AssertionError("assignment must not enter the game backend")

    def set_gameplay(self, attempt_id: str) -> None:
        return None

    def safe_stop(self, reason: str) -> None:
        return None
