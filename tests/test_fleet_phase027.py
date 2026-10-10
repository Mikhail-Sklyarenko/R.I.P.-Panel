"""Phase 02.7: operator authority, transaction ownership, and restart fences."""
from __future__ import annotations

import json
import ssl
import threading
import urllib.error
import urllib.request

import pytest

from core.wingman_fleet.assignments import AssignmentBook, AssignmentError
from core.wingman_fleet.coordinator import Coordinator
from core.wingman_fleet.models import (
    Command, CommandResult, CommandType, Identity, Observation, ResultStatus, to_dict,
)
from core.wingman_fleet.roster import FleetRoster
from core.wingman_fleet.server import FleetServer
from core.wingman_fleet.store import FleetStore
from modules.fleet_accounts.catalog import AccountCatalog
from modules.fleet_agent.identity import SteamIdentity
from modules.fleet_agent.journal import CommandJournal
from modules.fleet_agent.service import AgentService
from modules.fleet_agent.transport import InProcessTransport
from tests.test_fleet_acceptance import _cert, _ready
from tests.test_fleet_assignments import LINKS, STEAM, _book, _prepare_all, _selection
from tests.test_wingman_fleet_fsm import TOKEN


class _Backend:
    def __init__(self) -> None:
        self.expected = ""
        self.verified = False
        self._lease = ""
        self.executed: list[object] = []

    def apply_identity_assignment(self, steam_id64: str) -> None:
        if self._lease:
            raise RuntimeError("identity cannot change while gameplay is leased")
        self.expected = steam_id64

    def observe(self):
        return Observation("pc1", 1)

    def execute(self, cmd, ctx):
        self.executed.append(cmd.type)
        raise AssertionError(cmd.type)

    def set_gameplay(self, attempt_id: str) -> None:
        return None

    def safe_stop(self, reason: str) -> None:
        return None


def _json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None,
          payload: dict | None = None, context: ssl.SSLContext | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=2, context=context) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return exc.code, json.loads(raw) if raw else {}


def test_operator_authority_is_not_granted_by_agent_or_fleet_tokens(tmp_path):
    store = FleetStore(tmp_path / "c.db")
    with pytest.raises(ValueError):
        Coordinator(store, token=TOKEN, operator_token=TOKEN)
    coord = Coordinator(store, token=TOKEN, clock=lambda: 100.0)
    book = AssignmentBook(store, clock=lambda: 100.0)
    coord.assignments = book
    assert coord.operator_token != TOKEN
    code = book.open_enrollment("pc1")
    agent_token = book.claim_enrollment("pc1", code)
    server = FleetServer(coord, host="127.0.0.1", port=0).start()
    base = f"http://127.0.0.1:{server.port}"
    try:
        status, body = _json(base + "/v1/status", headers={"X-Operator-Token": coord.operator_token})
        assert status == 200 and body["ok"] is True
        for headers in (
            {"X-Fleet-Token": TOKEN},
            {"X-Operator-Token": agent_token},
            {"X-Operator-Token": TOKEN},
            {"Authorization": f"Bearer {TOKEN}"},
            {"Authorization": f"Bearer {agent_token}"},
        ):
            status, body = _json(base + "/v1/status", headers=headers)
            assert status == 403 and body["ok"] is False
            status, body = _json(base + "/v1/operator", method="POST", headers=headers, payload={"agent_id": "pc1"})
            assert status == 403
        status, body = _json(
            base + "/v1/operator", method="POST",
            headers={"X-Operator-Token": coord.operator_token}, payload={},
        )
        assert status == 400 and body["ok"] is False
        other = book.open_enrollment("pc2")
        status, body = _json(base + "/v1/enroll", method="POST", payload={"agent_id": "pc2", "code": other})
        assert status == 200 and body["ok"] is True
        enrolled = body["agent_token"]
        beat, beat_body = coord.handle_heartbeat({
            "token": TOKEN, "boot_id": "boot", "agent_token": enrolled,
            "process_generation": 1, "registration_generation": book.registration_generation("pc2"),
            "observation": to_dict(Observation("pc2", 1)),
        })
        assert beat == 200 and beat_body["ok"] is True
        denied, _ = coord.handle_heartbeat({
            "token": coord.operator_token, "boot_id": "boot", "agent_token": enrolled,
            "observation": to_dict(Observation("pc2", 2)),
        })
        assert denied == 403
        book.revoke_agent("pc2")
        denied, _ = coord.handle_heartbeat({
            "token": TOKEN, "boot_id": "boot", "agent_token": enrolled,
            "observation": to_dict(Observation("pc2", 3)),
        })
        assert denied == 403
        again = book.claim_enrollment("pc2", book.open_enrollment("pc2"))
        assert again != enrolled
        restored, restored_body = coord.handle_heartbeat({
            "token": TOKEN, "boot_id": "boot-2", "agent_token": again,
            "process_generation": 1, "registration_generation": book.registration_generation("pc2"),
            "observation": to_dict(Observation("pc2", 4)),
        })
        assert restored == 200 and restored_body["ok"] is True
        cert, key = _cert(tmp_path)
        tls = FleetServer(coord, host="127.0.0.1", port=0)
        tls.enable_tls(str(cert), str(key))
        tls.start()
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=str(cert))
        secure = f"https://127.0.0.1:{tls.port}"
        status, body = _json(secure + "/v1/status", headers={"X-Operator-Token": coord.operator_token}, context=context)
        assert status == 200 and body["ok"] is True
        status, _body = _json(secure + "/v1/status", headers={"X-Fleet-Token": TOKEN}, context=context)
        assert status == 403
        tls.stop()
    finally:
        server.stop()
        store.close()


def test_transaction_owner_does_not_adopt_another_thread(tmp_path):
    store = FleetStore(tmp_path / "c.db")
    book = AssignmentBook(store, clock=lambda: 100.0)
    holding = threading.Event()
    writer_finished = threading.Event()
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def owner() -> None:
        try:
            barrier.wait(2)
            with store.transaction():
                holding.set()
                if writer_finished.wait(0.5):
                    raise RuntimeError("joined")
                raise RuntimeError("injected")
        except RuntimeError as exc:
            if str(exc) != "injected":
                errors.append(exc)
        except BaseException as exc:
            errors.append(exc)

    def writer() -> None:
        try:
            barrier.wait(2)
            assert holding.wait(2)
            book.register_agent("pc1", "token-pc1")
            writer_finished.set()
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=owner), threading.Thread(target=writer)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3)
    assert not errors
    assert writer_finished.is_set()
    assert book.registration_state("pc1") == "registered"
    try:
        with store.transaction():
            book.register_agent("pc2", "token-pc2")
            raise RuntimeError("rollback")
    except RuntimeError:
        pass
    assert book.registration_state("pc2") == "unregistered"
    store.close()


def test_heartbeat_and_revoke_do_not_deadlock(tmp_path):
    store = FleetStore(tmp_path / "c.db")
    coord = Coordinator(store, token=TOKEN, clock=lambda: 100.0)
    book = AssignmentBook(store, clock=lambda: 100.0)
    coord.assignments = book
    book.register_agent("pc1", "token-pc1")
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def beat() -> None:
        try:
            barrier.wait(2)
            for seq in range(1, 25):
                coord.handle_heartbeat({
                    "token": TOKEN, "boot_id": "boot", "agent_token": "token-pc1",
                    "process_generation": 1, "registration_generation": 1,
                    "observation": to_dict(Observation("pc1", seq)),
                })
        except BaseException as exc:
            errors.append(exc)

    def revoke() -> None:
        try:
            barrier.wait(2)
            book.revoke_agent("pc1")
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=beat), threading.Thread(target=revoke)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3)
        assert not thread.is_alive()
    assert not errors
    assert book.registration_state("pc1") == "revoked"
    store.close()


def test_old_verify_after_restart_does_not_restore_ready(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    for index in range(1, 5):
        book.note_boot(f"pc{index}", "boot-a")
    for index, steam in enumerate(STEAM, start=1):
        book.note_identity(
            prep, f"pc{index}", steam, now=100.0, fresh=True, source="gsi",
            boot_id="boot-a", seq=5, generation=1, verification_id="v-a",
        )
    assert book.ready(prep, now=100.0) is True
    command = Command(
        f"{prep}/verify/old/pc1", prep, "pc1", CommandType.VERIFY_ASSIGNMENT,
        {"preparation_id": prep, "generation": 1, "seq": 5, "verification_id": "v-a"},
        "", 1, 240.0, 100.0,
    )
    book.store.add_commands([command])
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    result = CommandResult(command.command_id, ResultStatus.COMPLETED, evidence={
        "status": "verified", "observed_steam_id64": STEAM[0], "source": "gsi",
        "fresh": True, "verification_id": "v-a", "boot_id": "boot-a",
    })
    code, body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": "boot-b", "agent_token": "token-pc1",
        "process_generation": 1, "registration_generation": 1,
        "observation": to_dict(Observation("pc1", 1)),
        "results": [to_dict(result)],
    })
    assert code == 200 and command.command_id in body["accepted_results"]
    slot = next(row for row in book.slots(prep) if row["agent_id"] == "pc1")
    assert slot["verification_status"] != "verified"
    assert int(slot["verification_seq"] or 0) == 0
    assert book.ready(prep, now=100.0) is False
    assert book.current_ready(now=100.0) is False
    book.note_identity(
        prep, "pc1", STEAM[0], now=100.0, fresh=True, source="gsi",
        boot_id="boot-b", seq=1, generation=1, verification_id="v-b",
    )
    assert book.ready(prep, now=100.0) is True
    book.store.close()


def test_new_boot_publishes_catalog_when_sequence_restarts(tmp_path):
    book = _book(tmp_path)
    first = {
        "agent_id": "pc1", "catalog_generation": 3, "boot_id": "boot-a", "sequence": 1500,
        "accounts": [{
            "local_account_id": "acc-1", "steam_id64": STEAM[0], "display_name": "old",
            "enabled": True, "binding_status": "manually_bound", "availability_status": "available",
        }],
    }
    book.remember_catalog("pc1", first)
    restarted = dict(first, boot_id="boot-b", sequence=1)
    restarted["accounts"] = [dict(first["accounts"][0], display_name="new")]
    book.remember_catalog("pc1", restarted)
    name = book.store.db.execute(
        "SELECT display_name FROM catalog_cache WHERE agent_id=? AND local_account_id=?",
        ("pc1", "acc-1"),
    ).fetchone()[0]
    assert name == "new"
    stale = dict(restarted, sequence=0)
    stale["accounts"] = [dict(first["accounts"][0], display_name="stale")]
    book.remember_catalog("pc1", stale)
    name = book.store.db.execute(
        "SELECT display_name FROM catalog_cache WHERE agent_id=? AND local_account_id=?",
        ("pc1", "acc-1"),
    ).fetchone()[0]
    assert name == "new"
    anonymous = dict(restarted, boot_id="", sequence=0)
    anonymous["accounts"] = [dict(first["accounts"][0], display_name="anonymous")]
    book.remember_catalog("pc1", anonymous)
    name = book.store.db.execute(
        "SELECT display_name FROM catalog_cache WHERE agent_id=? AND local_account_id=?",
        ("pc1", "acc-1"),
    ).fetchone()[0]
    assert name == "new"
    book.store.close()


def test_empty_vault_does_not_mark_index_accounts_present(tmp_path):
    catalog = AccountCatalog(tmp_path / "catalog.db", agent_id="pc1")
    catalog.sync_logins(["alpha"], None)
    local = catalog.by_login("alpha")["local_account_id"]
    catalog.bind(local, STEAM[0])
    assert int(catalog.get(local)["vault_present"]) == 1
    issues = catalog.sync_logins(["alpha"], [])
    row = catalog.get(local)
    assert row is not None
    assert row["steam_id64"] == STEAM[0]
    assert int(row["vault_present"]) == 0
    assert "index_without_vault:alpha" in issues
    catalog.close()


def test_prepare_requires_registered_fresh_agents(tmp_path):
    book = _book(tmp_path)
    with pytest.raises(AssignmentError):
        book.draft(_selection())
    prep = book.draft(_selection(), links=LINKS)
    with pytest.raises(AssignmentError):
        book.begin_prepare(prep, {})
    book.note_presence("pc2", protocol=3, seen_at=90.0)
    with pytest.raises(AssignmentError):
        book.begin_prepare(prep, LINKS)
    book.note_presence("pc2", protocol=3, seen_at=100.0)
    book.revoke_agent("pc3")
    with pytest.raises(AssignmentError):
        book.begin_prepare(prep, LINKS)
    book.register_agent("pc3", "token-pc3")
    book.note_presence("pc4", protocol=2, seen_at=100.0)
    with pytest.raises(AssignmentError):
        book.begin_prepare(prep, LINKS)
    book.note_presence("pc4", protocol=3, seen_at=100.0)
    book.store.db.execute("UPDATE catalog_heads SET received_at=-50 WHERE agent_id='pc1'")
    assert book._cached("pc1", "acc-1") is not None
    with pytest.raises(AssignmentError):
        book.begin_prepare(prep, LINKS)
    book.store.close()


def test_ready_follows_presence_not_a_caller_supplied_link_map(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    for index, steam in enumerate(STEAM, start=1):
        book.note_identity(prep, f"pc{index}", steam, now=100.0, fresh=True, source="gsi")
    assert book.current_ready(now=100.0) is True
    roster = FleetRoster()
    plan = book.build_run_plan(roster, build_version="b", resource_manifest="m")
    assert plan.account_for_agent("pc1").steam_id64 == STEAM[0]
    book.note_presence("pc2", protocol=3, seen_at=90.0)
    assert book.current_ready(now=100.0) is False
    with pytest.raises(AssignmentError):
        book.build_run_plan(roster, build_version="b", resource_manifest="m", links=LINKS)
    book.note_presence("pc2", protocol=3, seen_at=100.0)
    book.note_link("pc2", "suspect")
    assert book.current_ready(now=100.0) is False
    with pytest.raises(AssignmentError):
        book.build_run_plan(roster, build_version="b", resource_manifest="m")
    book.store.close()


def test_commit_applies_expected_steam_without_verifying_it(tmp_path):
    catalog = AccountCatalog(tmp_path / "catalog.db", agent_id="pc1")
    catalog.sync_logins(["chosen"], ["chosen"])
    local = catalog.by_login("chosen")["local_account_id"]
    catalog.bind(local, STEAM[0])
    revision = int(catalog.get(local)["catalog_revision"])
    backend = _Backend()
    agent = AgentService(
        "pc1", backend, InProcessTransport(Coordinator(FleetStore(tmp_path / "unused.db"), token=TOKEN)),
        CommandJournal(tmp_path / "j.db"), token=TOKEN, build_version="b", resource_manifest="m",
        inline=True, catalog=catalog,
    )
    prepare = Command(
        "prep/prepare/pc1", "prep", "pc1", CommandType.PREPARE_ASSIGNMENT,
        {"preparation_id": "prep", "local_account_id": local, "steam_id64": STEAM[0],
         "catalog_revision": revision, "generation": 1, "coordinator_generation": 1},
        "", 1, 45.0, 1.0,
    )
    commit = Command(
        "prep/commit/pc1", "prep", "pc1", CommandType.COMMIT_ASSIGNMENT,
        {"preparation_id": "prep", "local_account_id": local, "steam_id64": STEAM[0],
         "generation": 1, "run_id": "run-1"},
        "", 1, 45.0, 1.0,
    )
    assert agent._apply_assignment(prepare).status is ResultStatus.COMPLETED
    backend._lease = "attempt"
    refused = agent._apply_assignment(commit)
    assert refused.status is ResultStatus.FAILED
    assert catalog.reservation("prep")["status"] == "prepared"
    assert backend.expected == ""
    backend._lease = ""
    assert agent._apply_assignment(commit).status is ResultStatus.COMPLETED
    assert backend.expected == STEAM[0]
    assert backend.verified is False
    agent._install_expected(STEAM[1], 0)
    assert backend.expected == STEAM[0]
    restored = _Backend()
    AgentService(
        "pc1", restored, agent.transport, CommandJournal(tmp_path / "j2.db"),
        token=TOKEN, build_version="b", resource_manifest="m", inline=True, catalog=catalog,
    )
    assert restored.expected == STEAM[0]
    assert restored.verified is False
    catalog.close()
    agent.journal.close()


def test_restarted_coordinator_and_agents_keep_the_committed_identity(tmp_path):
    store = FleetStore(tmp_path / "c.db")
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
        backend = _Backend()
        agent = AgentService(
            agent_id, backend, InProcessTransport(coord), CommandJournal(tmp_path / f"{agent_id}.journal"),
            token=TOKEN, build_version="b", resource_manifest="m", inline=True,
            agent_token=token, catalog=catalog, registration_generation=1,
        )
        agent.identity_probe = lambda steam=steam: SteamIdentity(Identity.GSI, steam)
        agents.append(agent)
        chosen.append((agent_id, local_id, steam, int(catalog.get(local_id)["catalog_revision"]), token, catalog, backend))
        agent.tick()
    prep = book.draft([
        {"slot_id": index, "agent_id": agent_id, "local_account_id": local_id, "steam_id64": steam,
         "expected_catalog_revision": revision}
        for index, (agent_id, local_id, steam, revision, *_rest) in enumerate(chosen, start=1)
    ], links=LINKS)
    book.begin_prepare(prep, LINKS)
    book.enqueue(prep, "prepare")
    for _ in range(2):
        for agent in agents:
            agent.tick()
    book.decide_commit(prep, run_id="run-restart")
    book.enqueue(prep, "commit")
    for _ in range(2):
        for agent in agents:
            agent.tick()
    assert book.ready(prep, now=100.0) is False
    for agent_id, _local, steam, *_rest, backend in chosen:
        assert backend.expected == steam
        assert backend.verified is False
        assert backend.executed == []
    book.enqueue(prep, "verify")
    for _ in range(2):
        for agent in agents:
            agent.tick()
    assert book.current_ready(now=100.0) is True
    restarted = Coordinator(store, token=TOKEN, clock=lambda: 100.0)
    restarted.assignments = book
    assert book.current_ready(now=100.0) is True
    plan = book.build_run_plan(FleetRoster(), build_version="b", resource_manifest="m", links={})
    assert plan.account_for_agent("pc1").steam_id64 == STEAM[0]
    for index, (agent_id, _local, steam, _revision, token, catalog, backend) in enumerate(chosen):
        assert plan.account_for_agent(agent_id).steam_id64 == backend.expected == steam
        assert backend.executed == []
        fresh = _Backend()
        follower = AgentService(
            agent_id, fresh, InProcessTransport(restarted), agents[index].journal,
            token=TOKEN, build_version="b", resource_manifest="m", inline=True,
            agent_token=token, catalog=catalog, registration_generation=1,
        )
        follower.identity_probe = agents[index].identity_probe
        assert fresh.expected == steam and fresh.verified is False
        follower.tick()
        agents[index] = follower
    assert book.current_ready(now=100.0) is False
    book.enqueue(prep, "verify")
    for _ in range(2):
        for agent in agents:
            agent.tick()
    assert book.current_ready(now=100.0) is True
    plan = book.build_run_plan(FleetRoster(), build_version="b", resource_manifest="m", links={})
    restarted.start_run(plan)
    assert restarted.plan.run_id == "run-restart"
    for agent, (_agent_id, _local, steam, _revision, _token, catalog, _backend) in zip(agents, chosen):
        assert agent.backend.expected == steam
        assert agent.backend.verified is False
        assert agent.backend.executed == []
        catalog.close()
    store.close()
