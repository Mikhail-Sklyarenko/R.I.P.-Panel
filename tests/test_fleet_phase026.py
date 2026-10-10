"""Phase 02.6 faults: revisions, vault diagnostics, tokens, TLS, and result durability."""
from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from core.wingman_fleet.assignments import AssignmentBook
from core.wingman_fleet.coordinator import Coordinator
from core.wingman_fleet.models import Command, CommandResult, CommandType, Observation, ResultStatus, to_dict
from core.wingman_fleet.roster import FleetRoster
from core.wingman_fleet.server import FleetServer
from core.wingman_fleet.store import FleetStore
from modules.fleet_accounts.catalog import AccountCatalog
from modules.fleet_agent.credentials import claim_enrollment_token, load_agent_token, store_agent_token
from modules.fleet_agent.host import lan_configuration_ready
from modules.fleet_agent.journal import CommandJournal
from modules.fleet_agent.service import AgentService
from modules.fleet_agent.transport import InProcessTransport
from modules.vault.models import VaultAccountSecret, VaultPayload
from modules.vault.store import vault_login_names
from tests.test_fleet_acceptance import _cert
from tests.test_fleet_assignments import STEAM, _book, _prepare_all, _selection
from tests.test_wingman_fleet_foundation import _Script, _service
from tests.test_wingman_fleet_fsm import TOKEN


def test_catalog_generation_is_not_the_max_account_revision(tmp_path):
    catalog = AccountCatalog(tmp_path / "catalog.db", agent_id="pc1")
    logins = [f"user{index}" for index in range(20)]
    catalog.sync_logins(logins, logins)
    assert catalog.revision() == 20
    small = catalog.by_login("user0")
    assert int(small["catalog_revision"]) == 1
    assert int(small["catalog_revision"]) < catalog.revision()
    catalog.bind(small["local_account_id"], STEAM[0])
    catalog.prepare(
        preparation_id="prep", local_account_id=small["local_account_id"], steam_id64=STEAM[0],
        catalog_revision=int(catalog.get(small["local_account_id"])["catalog_revision"]),
        generation=1, coordinator_generation=1,
    )
    with pytest.raises(Exception):
        catalog.prepare(
            preparation_id="prep", local_account_id=catalog.by_login("user1")["local_account_id"],
            steam_id64=STEAM[1], catalog_revision=1, generation=1, coordinator_generation=1,
        )
    before = catalog.revision()
    catalog.remove_local(catalog.by_login("user19")["local_account_id"])
    assert catalog.revision() == before + 1
    catalog.close()


def test_stale_snapshot_and_empty_catalog_keep_their_head(tmp_path):
    book = _book(tmp_path)
    book.remember_catalog("pc1", {
        "agent_id": "pc1", "catalog_generation": 4, "sequence": 2, "boot_id": "boot",
        "vault_status": "ok", "accounts": [],
    })
    book.remember_catalog("pc1", {
        "agent_id": "pc1", "catalog_generation": 3, "sequence": 9, "boot_id": "old",
        "accounts": [{"local_account_id": "late", "steam_id64": STEAM[0], "display_name": "late"}],
    })
    with book.store._lock:
        head = book.store.db.execute(
            "SELECT catalog_generation, sequence FROM catalog_heads WHERE agent_id='pc1'"
        ).fetchone()
        cached = book.store.db.execute(
            "SELECT COUNT(*) FROM catalog_cache WHERE agent_id='pc1'"
        ).fetchone()
    assert int(head["catalog_generation"]) == 4
    assert int(head["sequence"]) == 2
    assert int(cached[0]) == 0
    book.store.close()


def test_vault_diagnostics_do_not_return_secrets(tmp_path, monkeypatch):
    path = tmp_path / "vault.enc"
    names, code = vault_login_names(path)
    assert names == [] and code == "missing"
    path.write_bytes(b"garbage")
    monkeypatch.setattr("modules.vault.store.decrypt", lambda _raw: (_ for _ in ()).throw(ValueError("wrong key")))
    names, code = vault_login_names(path)
    assert names == [] and code == "bad_key"
    monkeypatch.setattr("modules.vault.store.decrypt", lambda _raw: b"{")
    names, code = vault_login_names(path)
    assert names == [] and code == "corrupt"
    payload = VaultPayload(accounts={
        "Alpha": VaultAccountSecret(login="Alpha", password="p@ss", shared_secret="ss", identity_secret="id"),
    })
    monkeypatch.setattr("modules.vault.store.decrypt", lambda _raw: payload.model_dump_json().encode())
    names, code = vault_login_names(path)
    assert names == ["Alpha"] and code == "ok" and "p@ss" not in names
    catalog = AccountCatalog(tmp_path / "catalog.db", agent_id="pc1")
    issues = catalog.sync_index_payload(json.dumps({"accounts": [{"login": "Alpha"}, {"login": "OnlyIndex"}]}), names)
    assert any(item.startswith("index_without_vault") for item in issues)
    assert "p@ss" not in str(issues)
    catalog.note_vault_status("bad_key")
    assert catalog.vault_status() == "bad_key"
    catalog.close()


def test_agent_token_is_protected_and_enrollment_is_one_time(tmp_path):
    secret = "agent-token-value"
    path = tmp_path / "pc1.bin"
    store_agent_token(path, secret)
    assert secret.encode() not in path.read_bytes()
    assert load_agent_token(path) == secret
    store = FleetStore(tmp_path / "c.db")
    coord = Coordinator(store, token=TOKEN, clock=lambda: 1.0)
    book = AssignmentBook(store, clock=lambda: 1.0)
    coord.assignments = book
    code = book.open_enrollment("pc1")
    server = FleetServer(coord, host="127.0.0.1", port=0).start()
    try:
        issued = claim_enrollment_token(f"http://127.0.0.1:{server.port}", "pc1", code)
        with pytest.raises(Exception):
            claim_enrollment_token(f"http://127.0.0.1:{server.port}", "pc1", code)
        with pytest.raises(Exception):
            claim_enrollment_token("http://10.0.0.8:8790", "pc1", "x")
    finally:
        server.stop()
    assert issued != secret
    assert book.registration_state("pc1") == "registered"
    store.close()


def test_cleartext_lan_is_refused_and_lan_ready_is_only_configuration(tmp_path):
    store = FleetStore(tmp_path / "c.db")
    coord = Coordinator(store, token=TOKEN)
    with pytest.raises(RuntimeError):
        FleetServer(coord, host="0.0.0.0", port=0).start()
    assert lan_configuration_ready(
        mode="localhost_development", tls=False, cert_exists=False, ca_exists=False, registrations={},
    ) is False
    assert lan_configuration_ready(
        mode="secure_lan", tls=True, cert_exists=True, ca_exists=True,
        registrations={f"pc{i}": "registered" for i in range(1, 5)},
    ) is True
    assert lan_configuration_ready(
        mode="secure_lan", tls=True, cert_exists=True, ca_exists=True,
        registrations={"pc1": "revoked", "pc2": "registered", "pc3": "registered", "pc4": "registered"},
    ) is False
    store.close()


def test_result_crash_does_not_ack_and_retry_applies_once(tmp_path):
    book = _book(tmp_path)
    prep = book.draft(_selection(), links={f"pc{i}": "healthy" for i in range(1, 5)})
    book.begin_prepare(prep, {f"pc{i}": "healthy" for i in range(1, 5)})
    book.enqueue(prep, "prepare")
    coord = Coordinator(book.store, token=TOKEN, clock=lambda: 100.0)
    coord.assignments = book
    book.register_agent("pc1", "token-pc1")
    real = book.note_prepare
    state = {"failed": False}

    def boom(*args, **kwargs):
        if not state["failed"]:
            state["failed"] = True
            raise sqlite3.OperationalError("injected")
        return real(*args, **kwargs)

    book.note_prepare = boom
    result = CommandResult(f"{prep}/prepare/pc1", ResultStatus.COMPLETED, evidence={"status": "prepared"})
    payload = {
        "token": TOKEN, "boot_id": "boot", "agent_token": "token-pc1",
        "observation": to_dict(Observation("pc1", 1)),
        "results": [to_dict(result)],
    }
    code, body = coord.handle_heartbeat(payload)
    assert code == 200 and result.command_id not in body["accepted_results"]
    pending = book.store.db.execute(
        "SELECT status FROM commands WHERE command_id=?", (result.command_id,)
    ).fetchone()
    assert pending[0] == "pending"
    payload["observation"] = to_dict(Observation("pc1", 2))
    code, body = coord.handle_heartbeat(payload)
    assert result.command_id in body["accepted_results"]
    assert book.slots(prep)[0]["reservation_status"] == "prepared"
    book.store.close()


def test_late_release_and_restart_do_not_invent_a_new_run(tmp_path):
    book = _book(tmp_path)
    prep = book.draft(_selection(), links={f"pc{i}": "healthy" for i in range(1, 5)})
    _prepare_all(book, prep)
    book.decide_commit(prep, run_id="run-keep")
    for index in range(1, 5):
        book.note_commit(prep, f"pc{index}", ok=True, generation=1)
    assert book.note_release(prep, "pc1", ok=True, generation=99) == "committed"
    assert book.slots(prep)[0]["reservation_status"] == "committed"
    path = book.store.path
    book.store.close()
    restored = AssignmentBook(FleetStore(path), clock=lambda: 100.0)
    assert restored.status(prep)["status"] == "committed"
    assert restored.status(prep)["run_id"] == "run-keep"
    with pytest.raises(Exception):
        restored.decide_commit(prep, run_id="run-other")
    restored.store.close()


def test_one_offline_agent_blocks_ready_and_a_foreign_result_is_ignored(tmp_path):
    store = FleetStore(tmp_path / "coord.db")
    coord = Coordinator(store, token=TOKEN, clock=lambda: 100.0)
    book = AssignmentBook(store, identity_ttl_sec=120.0, clock=lambda: 100.0)
    coord.assignments = book
    agents = []
    for index, steam in enumerate(STEAM, start=1):
        agent_id = f"pc{index}"
        token = book.claim_enrollment(agent_id, book.open_enrollment(agent_id))
        catalog = AccountCatalog(tmp_path / f"{agent_id}.db", agent_id=agent_id)
        catalog.sync_logins(["chosen"], ["chosen"])
        local_id = catalog.by_login("chosen")["local_account_id"]
        catalog.bind(local_id, steam)
        transport = InProcessTransport(coord)
        agent = AgentService(
            agent_id, _Quiet(), transport, CommandJournal(tmp_path / f"{agent_id}.journal"),
            token=TOKEN, build_version="b", resource_manifest="m", inline=True,
            agent_token=token, catalog=catalog,
        )
        agent.identity_probe = (lambda steam=steam: _Identity(steam))
        agents.append((agent, transport, local_id, steam, int(catalog.get(local_id)["catalog_revision"])))
        agent.tick()
    agents[0][1].down = True
    assert agents[0][0].tick() is False
    prep = book.draft([
        {"slot_id": index, "agent_id": f"pc{index}", "local_account_id": item[2], "steam_id64": item[3],
         "expected_catalog_revision": item[4]}
        for index, item in enumerate(agents, start=1)
    ], links={f"pc{i}": "healthy" for i in range(1, 5)})
    book.begin_prepare(prep, {f"pc{i}": "healthy" for i in range(1, 5)})
    book.enqueue(prep, "prepare")
    for _ in range(2):
        for agent, _transport, *_rest in agents[1:]:
            agent.tick()
    assert book.status(prep)["status"] != "ready"
    foreign = CommandResult(f"{prep}/prepare/pc2", ResultStatus.COMPLETED, evidence={"status": "prepared"})
    code, body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": agents[0][0].boot_id, "agent_token": agents[0][0].agent_token,
        "observation": to_dict(Observation("pc1", 3)),
        "results": [to_dict(foreign)],
    })
    assert code == 200 and foreign.command_id not in body.get("accepted_results", [])
    for agent, _transport, *_rest in agents:
        agent.journal.close()
        agent.catalog.close()
    store.close()


def test_revoked_registration_has_no_shared_token_path_and_unregistered_is_rejected(tmp_path):
    store = FleetStore(tmp_path / "c.db")
    coord = Coordinator(store, token=TOKEN, clock=lambda: 1.0)
    book = AssignmentBook(store, clock=lambda: 1.0)
    coord.assignments = book
    code, _body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": "boot",
        "observation": to_dict(Observation("pc1", 1)),
    })
    assert code == 403
    book.register_agent("pc1", "own-token")
    book.revoke_agent("pc1")
    code, _body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": "boot", "agent_token": "own-token",
        "observation": to_dict(Observation("pc1", 1)),
    })
    assert code == 403
    store.close()


def test_https_wrong_name_and_expired_certificate_fail(tmp_path):
    from modules.fleet_agent.transport import HttpTransport, TransportError
    cert, key = _cert(tmp_path, san="192.0.2.10")
    store = FleetStore(tmp_path / "c.db")
    coord = Coordinator(store, token=TOKEN, clock=lambda: 1.0)
    server = FleetServer(coord, host="127.0.0.1", port=0)
    server.enable_tls(str(cert), str(key))
    server.start()
    try:
        with pytest.raises(TransportError):
            HttpTransport(f"https://127.0.0.1:{server.port}", ca_file=str(cert)).heartbeat({
                "token": TOKEN, "observation": {"agent_id": "pc1", "sequence": 1, "protocol": 3},
            })
    finally:
        server.stop()
    old = tmp_path / "old"
    old.mkdir()
    expired, expired_key = _cert(old, expired=True)
    server2 = FleetServer(coord, host="127.0.0.1", port=0)
    server2.enable_tls(str(expired), str(expired_key))
    server2.start()
    try:
        with pytest.raises(TransportError):
            HttpTransport(f"https://127.0.0.1:{server2.port}", ca_file=str(expired)).heartbeat({
                "token": TOKEN, "observation": {"agent_id": "pc1", "sequence": 1, "protocol": 3},
            })
    finally:
        server2.stop()
        store.close()


def test_assignment_threads_do_not_depend_on_sleep(tmp_path):
    catalog = AccountCatalog(tmp_path / "catalog.db", agent_id="pc1")
    catalog.sync_logins(["alpha"], ["alpha"])
    local_id = catalog.by_login("alpha")["local_account_id"]
    catalog.bind(local_id, STEAM[0])
    started = threading.Barrier(2)
    release = threading.Event()

    def hold():
        started.wait(timeout=2)
        assert release.wait(timeout=2)

    worker = threading.Thread(target=hold)
    worker.start()
    started.wait(timeout=2)
    revision = int(catalog.get(local_id)["catalog_revision"])
    outcome: list[str] = []

    def prepare():
        outcome.append(catalog.prepare(
            preparation_id="prep", local_account_id=local_id, steam_id64=STEAM[0],
            catalog_revision=revision, generation=1, coordinator_generation=1,
        ))

    other = threading.Thread(target=prepare)
    other.start()
    other.join(timeout=2)
    release.set()
    worker.join(timeout=2)
    assert outcome == ["prepared"]
    catalog.close()


def test_verify_uses_the_agent_probe_not_the_coordinator_hint(tmp_path):
    catalog = AccountCatalog(tmp_path / "catalog.db", agent_id="pc1")
    catalog.sync_logins(["alpha"], ["alpha"])
    local_id = catalog.by_login("alpha")["local_account_id"]
    catalog.bind(local_id, STEAM[0])
    agent = _service(tmp_path, _Quiet(), _Script(), now=[0.0])
    agent.catalog = catalog
    agent.identity_probe = lambda: _Identity(STEAM[0])
    agent._accept(Command(
        "prep/verify/1/pc1", "prep", "pc1", CommandType.VERIFY_ASSIGNMENT,
        {"preparation_id": "prep", "local_account_id": local_id, "steam_id64": STEAM[0],
         "observed_steam_id64": STEAM[1], "verification_id": "v1", "generation": 1},
        "", 1, 45.0, 1.0,
    ), 1.0)
    result = agent.journal.unacked()[0]
    assert result.evidence["observed_steam_id64"] == STEAM[0]
    assert result.evidence["source"] == "gsi"
    assert STEAM[1] not in result.evidence["observed_steam_id64"]
    catalog.close()
    agent.journal.close()


def test_identity_assignment_does_not_mark_verified_or_four_pc(tmp_path):
    from modules.fleet_agent.host import FleetHost
    from modules.fleet_agent.live import WindowsBackend
    backend = object.__new__(WindowsBackend)
    backend.expected = ""
    backend._pending_identity = ""
    backend._lease = ""
    backend._lock = threading.RLock()
    backend.apply_identity_assignment(STEAM[0])
    assert backend.expected == STEAM[0]
    assert not hasattr(backend, "verified")
    status = FleetHost().status()
    assert status["four_pc_proven"] is False
    assert status["lan_ready"] is False


class _Quiet:
    def observe(self):
        return Observation("pc1", 1)

    def execute(self, cmd, ctx):
        raise AssertionError(cmd.type)

    def set_gameplay(self, attempt_id: str) -> None:
        return None

    def safe_stop(self, reason: str) -> None:
        return None


class _Identity:
    def __init__(self, steam: str):
        self.steam_id64 = steam
        self.identity = type("Kind", (), {"value": "gsi"})()
