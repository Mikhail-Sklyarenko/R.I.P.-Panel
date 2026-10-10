"""Phase 02.0: durable operator stop, agent latch, and lease fencing."""
from __future__ import annotations

import sqlite3
import threading

from core.wingman_fleet.coordinator import Coordinator
from core.wingman_fleet.models import CommandType, Link, Observation, to_dict
from core.wingman_fleet.run_fsm import RunState
from core.wingman_fleet.store import FleetStore
from modules.fleet_agent.backend import ExecContext
from modules.fleet_agent.journal import CommandJournal, JournalCorrupt
from modules.fleet_agent.live import WindowsBackend
from modules.fleet_agent.input_supervisor import InputOwner, InputSupervisor
from modules.fleet_agent.service import AgentService
from tests.test_wingman_fleet_fsm import TOKEN, make_roster
from tests.test_wingman_fleet_foundation import _Script, _cmd, _service


def test_operator_stop_survives_coordinator_restart_before_any_lease(tmp_path):
    store = FleetStore(tmp_path / "c.db")
    coord = Coordinator(store, token=TOKEN, clock=lambda: 10.0)
    plan = make_roster().build_plan(build_version="b", resource_manifest="m", now=10.0)
    coord.start_run(plan)
    coord.run.ctx.state = RunState.IN_MATCH
    coord.run.ctx.attempt_id = "wave-1"
    first = coord.agent_command("pc1", CommandType.SAFE_STOP, request_key="stop-1")
    again = coord.agent_command("pc1", CommandType.SAFE_STOP, request_key="stop-1")
    other = coord.agent_command("pc1", CommandType.SCREENSHOT, request_key="shot-1")
    assert first.command_id == again.command_id
    assert other.command_id != first.command_id
    assert first.command_id.startswith(f"{plan.run_id}/operator/")
    store.close()

    restored = FleetStore(tmp_path / "c.db")
    coord2 = Coordinator(restored, token=TOKEN, clock=lambda: 10.0)
    assert coord2.run.gameplay_admitted("pc1", {"pc1": Link.HEALTHY}) == ""
    assert "pc2" not in coord2.run.ctx.operator_stopped
    code, resp = coord2.handle_heartbeat({
        "token": TOKEN, "boot_id": "boot",
        "observation": to_dict(Observation("pc1", 1, steam_running=True, cs2_running=True)),
    })
    assert code == 200 and resp["gameplay"] is None
    assert any(command["command_id"] == first.command_id for command in resp["commands"])
    restored.close()


def test_failed_stop_transaction_does_not_report_success(tmp_path):
    store = FleetStore(tmp_path / "c.db")
    coord = Coordinator(store, token=TOKEN, clock=lambda: 10.0)
    plan = make_roster().build_plan(build_version="b", resource_manifest="m", now=10.0)
    coord.start_run(plan)
    store.db.execute(
        "CREATE TRIGGER fail_stop BEFORE INSERT ON operator_stops "
        "BEGIN SELECT RAISE(ROLLBACK, 'disk full'); END"
    )
    try:
        coord.agent_command("pc1", CommandType.SAFE_STOP, request_key="boom")
        raise AssertionError("stop was reported after a failed transaction")
    except sqlite3.IntegrityError:
        pass
    store.db.execute("DROP TRIGGER fail_stop")
    assert store.operator_stopped_agents(plan.run_id) == []
    assert store.db.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 0
    assert coord.run.ctx.operator_stopped == []
    store.close()


def test_agent_stop_latch_survives_process_restart(tmp_path):
    journal = tmp_path / "j.db"
    agent = _service(tmp_path, _Hold(), _Script(), now=[0.0])
    agent.journal.close()
    agent.journal = CommandJournal(journal)
    agent._rotate_run("run-a")
    agent._accept(_cmd("stop", "run-a", "pc1", CommandType.SAFE_STOP), 1.0)
    assert agent.session_stopped
    agent.journal.close()

    revived = AgentService(
        "pc1", _Hold(), _Script({"ok": True, "commands": [], "accepted_results": [], "run_id": "run-a",
                                 "server_time": 2.0, "gameplay": {"attempt_id": "wave", "ttl_sec": 1.5}}),
        CommandJournal(journal), token=TOKEN, build_version="b", resource_manifest="m", inline=True,
    )
    assert revived.session_stopped
    assert revived.run_id == "run-a"
    assert revived.tick() is True
    assert revived.lease_attempt == ""
    revived._rotate_run("")
    assert revived.session_stopped
    revived._rotate_run("run-b")
    assert revived.session_stopped is False
    revived.journal.close()


def test_corrupt_session_fails_closed(tmp_path):
    path = tmp_path / "j.db"
    journal = CommandJournal(path)
    journal.db.execute("INSERT INTO agent_session(id, run_id, stopped, generation, updated_at) VALUES(1,'run',2,1,0)")
    journal.close()
    agent = AgentService(
        "pc1", _Hold(), _Script(), CommandJournal(path), token=TOKEN,
        build_version="b", resource_manifest="m", inline=True,
    )
    assert agent.session_stopped and agent._fail_closed
    agent._accept(_cmd("go", "run-b", "pc1", CommandType.INVITE), 1.0)
    agent.drain()
    assert agent.journal.known("go") is None
    agent._rotate_run("run-b")
    assert agent.session_stopped
    agent.journal.close()
    assert JournalCorrupt is not None


class _Hold:
    def __init__(self):
        self.leases: list[str] = []
        self.generation_seen: list[int] = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def observe(self):
        return Observation("pc1", 1)

    def execute(self, cmd, ctx: ExecContext):
        from core.wingman_fleet.models import CommandResult, ResultStatus
        return CommandResult(cmd.command_id, ResultStatus.COMPLETED)

    def set_gameplay(self, attempt_id: str, generation: int = 0) -> None:
        if attempt_id:
            self.entered.set()
            self.release.wait(2)
        if self.generation_seen and generation < self.generation_seen[-1]:
            self.leases.append(f"ignored:{attempt_id}")
            return
        self.generation_seen.append(generation)
        self.leases.append(attempt_id)

    def safe_stop(self, reason: str) -> None:
        return None


def test_stale_lease_apply_cannot_overwrite_a_newer_one(tmp_path):
    backend = _Hold()
    body = {"ok": True, "commands": [], "accepted_results": [], "run_id": "run-a", "server_time": 1.0,
            "gameplay": {"attempt_id": "wave", "ttl_sec": 1.5}}
    agent = _service(tmp_path, backend, _Script(body))
    agent._rotate_run("run-a")
    worker = threading.Thread(target=agent.tick)
    worker.start()
    assert backend.entered.wait(2)
    agent._accept(_cmd("stop", "run-a", "pc1", CommandType.SAFE_STOP), 1.0)
    backend.release.set()
    worker.join(2)
    assert agent.lease_attempt == ""
    assert "ignored:wave" in backend.leases
    assert backend.leases[-1] == ""


def test_only_one_run_can_be_active(tmp_path):
    store = FleetStore(tmp_path / "c.db")
    plan = make_roster().build_plan(build_version="b", resource_manifest="m", now=1.0)
    store.save_run(plan)
    other = make_roster().build_plan(build_version="b", resource_manifest="m", now=2.0)
    store.save_run(other)
    active = store.db.execute("SELECT run_id FROM runs WHERE active=1").fetchall()
    assert active == [(other.run_id,)]
    store.close()


def test_windows_backend_ignores_an_older_lease_generation(tmp_path):
    live = object.__new__(WindowsBackend)
    live._lock = threading.RLock()
    live._lease = ""
    live._lease_generation = 0
    live.log = lambda _message: None
    live.admission = tmp_path / "admission.json"
    live.inputs = InputSupervisor(release=lambda: None)
    live.set_gameplay("wave", 2)
    live.set_gameplay("older", 1)
    assert live.inputs.gameplay_attempt == "wave"
    assert live.inputs.owner is InputOwner.GAMEPLAY
    live.set_gameplay("", 3)
    assert live.inputs.owner is InputOwner.NONE
    live.set_gameplay("wave", 2)
    assert live.inputs.owner is InputOwner.NONE
