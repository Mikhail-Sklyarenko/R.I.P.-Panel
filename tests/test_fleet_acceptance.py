"""Phase 02.6: identity proof, explicit roster freeze, and four simulated agents."""
from __future__ import annotations

import datetime
import ipaddress

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from core.wingman_fleet.assignments import AssignmentBook, AssignmentError
from core.wingman_fleet.coordinator import Coordinator
from core.wingman_fleet.models import CommandType, Identity, Observation
from core.wingman_fleet.roster import FleetRoster
from core.wingman_fleet.server import FleetServer
from core.wingman_fleet.store import FleetStore
from modules.fleet_accounts.catalog import AccountCatalog
from modules.fleet_agent.identity import SteamIdentity
from modules.fleet_agent.journal import CommandJournal
from modules.fleet_agent.service import AgentService
from modules.fleet_agent.transport import HttpTransport, InProcessTransport, TransportError
from tests.test_fleet_assignments import STEAM, _book, _prepare_all, _selection
from tests.test_wingman_fleet_foundation import _Script, _service
from tests.test_wingman_fleet_fsm import TOKEN


def _ready(book: AssignmentBook):
    prep = book.draft(_selection(), links={f"pc{i}": "healthy" for i in range(1, 5)})
    _prepare_all(book, prep)
    book.decide_commit(prep, run_id="run-ready")
    for index in range(1, 5):
        book.note_commit(prep, f"pc{index}", ok=True, generation=1)
    return prep


def test_fresh_false_match_is_not_ready(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    for index, steam in enumerate(STEAM, start=1):
        book.note_identity(prep, f"pc{index}", steam, now=100.0, fresh=False, source="gsi")
    assert book.ready(prep, now=100.0) is False
    book.store.close()


def test_four_fresh_gsi_matches_are_ready_until_link_or_clock_breaks(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    for index, steam in enumerate(STEAM, start=1):
        book.note_identity(prep, f"pc{index}", steam, now=100.0, fresh=True, source="gsi", boot_id="boot")
    links = {f"pc{i}": "healthy" for i in range(1, 5)}
    assert book.ready(prep, now=100.0, links=links) is True
    assert book.ready(prep, now=99.0, links=links) is False
    book.note_identity(prep, "pc1", STEAM[0], now=100.0, fresh=True, source="gsi", boot_id="boot")
    for index, steam in enumerate(STEAM[1:], start=2):
        book.note_identity(prep, f"pc{index}", steam, now=100.0, fresh=True, source="gsi", boot_id="boot")
    assert book.ready(prep, now=100.0, links=links) is True
    book.note_link("pc3", "suspect")
    assert book.ready(prep, now=100.0, links=links) is False
    book.note_link("pc3", "healthy")
    for index, steam in enumerate(STEAM, start=1):
        book.note_identity(prep, f"pc{index}", steam, now=100.0, fresh=True, source="gsi", boot_id="boot", seq=2)
    assert book.ready(prep, now=100.0, links=links) is True
    book.note_identity(prep, "pc1", STEAM[0], now=50.0, fresh=True, source="gsi", boot_id="boot", seq=1)
    assert book.ready(prep, now=100.0, links=links) is True
    book.note_boot("pc1", "restarted")
    assert book.ready(prep, now=100.0, links=links) is False
    book.store.close()


def test_manual_source_and_mismatch_block_ready(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    for index, steam in enumerate(STEAM, start=1):
        source = "manual" if index == 1 else "gsi"
        book.note_identity(prep, f"pc{index}", steam, now=100.0, fresh=True, source=source)
    assert book.ready(prep, now=100.0) is False
    book.note_identity(prep, "pc1", STEAM[1], now=100.0, fresh=True, source="steam_local")
    assert book.status(prep)["status"] != "ready"
    book.store.close()


def test_revoked_agent_cannot_fall_back_to_the_shared_token(tmp_path):
    store = FleetStore(tmp_path / "c.db")
    coord = Coordinator(store, token=TOKEN, clock=lambda: 10.0)
    book = AssignmentBook(store, clock=lambda: 10.0)
    coord.assignments = book
    book.register_agent("pc1", "secret-1")
    book.revoke_agent("pc1")
    code, _body = coord.handle_heartbeat({
        "token": TOKEN, "agent_token": "secret-1", "boot_id": "boot",
        "observation": {"agent_id": "pc1", "sequence": 1, "protocol": 3},
    })
    assert code == 403
    code, _body = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": "boot",
        "observation": {"agent_id": "pc1", "sequence": 1, "protocol": 3},
    })
    assert code == 403
    store.close()


def test_run_plan_is_frozen_from_the_assignment(tmp_path):
    book = _book(tmp_path)
    prep = _ready(book)
    for index, steam in enumerate(STEAM, start=1):
        book.note_identity(prep, f"pc{index}", steam, now=100.0, fresh=True, source="gsi")
    roster = FleetRoster(slots={
        1: {"agent_id": "other", "steam_id64": STEAM[0], "display_name": "E", "friend_code": "1"},
        2: {"agent_id": "pc2", "steam_id64": STEAM[1], "display_name": "F", "friend_code": "2"},
        3: {"agent_id": "pc3", "steam_id64": STEAM[2], "display_name": "G", "friend_code": "3"},
        4: {"agent_id": "pc4", "steam_id64": STEAM[3], "display_name": "H", "friend_code": "4"},
    })
    plan = book.build_run_plan(roster, build_version="b", resource_manifest="m",
                               links={f"pc{i}": "healthy" for i in range(1, 5)})
    assert plan.run_id == "run-ready"
    assert plan.account_for_agent("pc1").steam_id64 == STEAM[0]
    assert plan.account_for_agent("pc1").account_id == "pc1:acc-1"
    assert roster.slots[1]["agent_id"] == "pc1"
    assert roster.slots[1]["local_account_id"] == "acc-1"
    book.remember_catalog("pc1", {
        "agent_id": "pc1", "catalog_generation": 9, "sequence": 2,
        "accounts": [{
            "local_account_id": "acc-1", "steam_id64": STEAM[0], "display_name": "changed",
            "enabled": True, "binding_status": "manually_bound", "availability_status": "available",
            "account_revision": 9,
        }],
    })
    assert plan.account_for_agent("pc1").display_name != "changed"
    with pytest.raises(AssignmentError):
        book.build_run_plan(roster, build_version="b", resource_manifest="m",
                            links={"pc1": "offline", "pc2": "healthy", "pc3": "healthy", "pc4": "healthy"})
    book.store.close()


def test_assignment_survives_a_cancelled_gameplay_context(tmp_path):
    catalog = AccountCatalog(tmp_path / "catalog.db", agent_id="pc1")
    catalog.sync_logins(["alpha"], ["alpha"])
    account = catalog.by_login("alpha")["local_account_id"]
    catalog.bind(account, STEAM[0])
    revision = int(catalog.get(account)["catalog_revision"])
    agent = _service(tmp_path, _Quiet(), _Script(), now=[0.0])
    agent.catalog = catalog
    agent.cancel.set()
    agent.run_id = ""
    from core.wingman_fleet.models import Command
    agent._accept(Command(
        "prep/prepare/pc1", "prep", "pc1", CommandType.PREPARE_ASSIGNMENT,
        {"preparation_id": "prep", "local_account_id": account, "steam_id64": STEAM[0],
         "catalog_revision": revision, "generation": 1, "coordinator_generation": 1},
        "", 1, 45.0, 1.0,
    ), 1.0)
    agent.drain()
    assert catalog.reservation("prep")["status"] == "prepared"
    catalog.close()
    agent.journal.close()


class _Quiet:
    def observe(self):
        return Observation("pc1", 1)

    def execute(self, cmd, ctx):
        raise AssertionError(cmd.type)

    def set_gameplay(self, attempt_id: str) -> None:
        return None

    def safe_stop(self, reason: str) -> None:
        return None


def _cert(tmp_path, *, expired: bool = False, san: str = "127.0.0.1"):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "fleet-test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(days=2) if expired else now - datetime.timedelta(minutes=1)
    end = now - datetime.timedelta(days=1) if expired else now + datetime.timedelta(days=1)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(start).not_valid_after(end)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(san))]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ))
    return cert_path, key_path


def test_https_accepts_a_trusted_certificate_and_rejects_a_bad_one(tmp_path):
    cert, key = _cert(tmp_path)
    store = FleetStore(tmp_path / "c.db")
    coord = Coordinator(store, token=TOKEN, clock=lambda: 1.0)
    server = FleetServer(coord, host="127.0.0.1", port=0)
    server.enable_tls(str(cert), str(key))
    server.start()
    try:
        body = HttpTransport(f"https://127.0.0.1:{server.port}", ca_file=str(cert)).heartbeat({
            "token": TOKEN, "boot_id": "tls", "observation": {"agent_id": "pc1", "sequence": 1, "protocol": 3},
        })
        assert body["ok"] is True
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        other, other_key = _cert(other_dir)
        with pytest.raises(TransportError):
            HttpTransport(f"https://127.0.0.1:{server.port}", ca_file=str(other)).heartbeat({
                "token": TOKEN, "boot_id": "tls2", "observation": {"agent_id": "pc1", "sequence": 2, "protocol": 3},
            })
    finally:
        server.stop()
        store.close()


def test_four_simulated_agents_commit_and_freeze_a_run_plan(tmp_path):
    store = FleetStore(tmp_path / "coord.db")
    coord = Coordinator(store, token=TOKEN, clock=lambda: 100.0)
    book = AssignmentBook(store, identity_ttl_sec=120.0, clock=lambda: 100.0)
    coord.assignments = book
    agents = []
    chosen = []
    for index, steam in enumerate(STEAM, start=1):
        agent_id = f"pc{index}"
        code = book.open_enrollment(agent_id)
        token = book.claim_enrollment(agent_id, code)
        catalog = AccountCatalog(tmp_path / f"{agent_id}.db", agent_id=agent_id)
        catalog.sync_logins(["skip", "chosen"], ["skip", "chosen"])
        catalog.bind(catalog.by_login("skip")["local_account_id"], str(76561197960265728 + 20 + index))
        chosen_id = catalog.by_login("chosen")["local_account_id"]
        catalog.bind(chosen_id, steam)
        catalog.set_enabled(chosen_id, True)
        agent = AgentService(
            agent_id, _Quiet(), InProcessTransport(coord), CommandJournal(tmp_path / f"{agent_id}.journal"),
            token=TOKEN, build_version="b", resource_manifest="m", inline=True, agent_token=token, catalog=catalog,
        )
        agent.identity_probe = lambda steam=steam: SteamIdentity(Identity.GSI, steam)
        agents.append(agent)
        chosen.append((agent_id, chosen_id, steam, int(catalog.get(chosen_id)["catalog_revision"])))
        agent.tick()
    prep = book.draft([
        {"slot_id": index, "agent_id": agent_id, "local_account_id": local_id, "steam_id64": steam,
         "expected_catalog_revision": revision}
        for index, (agent_id, local_id, steam, revision) in enumerate(chosen, start=1)
    ], links={f"pc{i}": "healthy" for i in range(1, 5)})
    book.begin_prepare(prep)
    book.enqueue(prep, "prepare")
    for _ in range(2):
        for agent in agents:
            agent.tick()
    assert book.status(prep)["status"] == "prepared"
    book.decide_commit(prep, run_id="run-e2e")
    book.enqueue(prep, "commit")
    for _ in range(2):
        for agent in agents:
            agent.tick()
    assert all(slot["reservation_status"] == "committed" for slot in book.slots(prep))
    book.enqueue(prep, "verify")
    for _ in range(2):
        for agent in agents:
            agent.tick()
    links = {agent_id: link.value for agent_id, link in coord.links().items()}
    assert book.ready(prep, now=100.0, links=links) is True
    roster = FleetRoster()
    plan = book.build_run_plan(roster, build_version="b", resource_manifest="m", links=links)
    coord.start_run(plan)
    assert coord.plan.run_id == "run-e2e"
    assert coord.plan.account_for_agent("pc2").account_id.endswith(chosen[1][1])
    assert "password" not in str(book.status(prep))
    for agent in agents:
        agent.journal.close()
        agent.catalog.close()
    store.close()
