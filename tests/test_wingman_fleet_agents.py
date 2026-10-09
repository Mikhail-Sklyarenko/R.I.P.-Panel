"""Four real AgentService instances + coordinator over the simulated world."""
from __future__ import annotations

import json
import urllib.request

from core.wingman_fleet.coordinator import Coordinator
from core.wingman_fleet.models import Command, CommandType, ResultStatus
from core.wingman_fleet.run_fsm import RunState
from core.wingman_fleet.server import FleetServer
from core.wingman_fleet.store import FleetStore
from modules.fleet_agent.journal import CommandJournal
from modules.fleet_agent.service import AgentService
from modules.fleet_agent.simulation import SimWorld
from modules.fleet_agent.transport import HttpTransport, InProcessTransport, TransportError
from tests.test_wingman_fleet_fsm import ACCOUNTS, TOKEN, make_roster


class LossyTransport(InProcessTransport):
    """Delivers the request but loses every `every`-th response (ACK lost)."""

    def __init__(self, coordinator, every: int):
        super().__init__(coordinator)
        self.every, self.n = every, 0

    def heartbeat(self, payload):
        body = super().heartbeat(payload)
        self.n += 1
        if self.every and self.n % self.every == 0:
            raise TransportError("response lost")
        return body


class Fleet:
    def __init__(self, tmp_path, *, lossy_every: int = 0, retry=None, **world_kw):
        self.tmp = tmp_path
        self.world = SimWorld(ACCOUNTS, **world_kw)
        self.store = FleetStore(tmp_path / "fleet.db")
        self.coord = Coordinator(self.store, token=TOKEN, clock=lambda: self.world.now)
        self.lossy_every = lossy_every
        self.backends = {a: self.world.backend(a) for a, _, _ in ACCOUNTS}
        self.transports = {}
        self.agents = {a: self._agent(a) for a, _, _ in ACCOUNTS}
        self.plan = make_roster(retry).build_plan(build_version="test-build", resource_manifest="test-manifest",
                                                  now=self.world.now)
        self.coord.start_run(self.plan)

    def _agent(self, agent_id: str) -> AgentService:
        t = LossyTransport(self.coord, self.lossy_every) if self.lossy_every else InProcessTransport(self.coord)
        self.transports[agent_id] = t
        journal = CommandJournal(self.tmp / f"journal-{agent_id}.db")
        return AgentService(agent_id, self.backends[agent_id], t, journal, token=TOKEN,
                            build_version="test-build", resource_manifest="test-manifest", inline=True,
                            clock=lambda: self.world.now, wall=lambda: self.world.now)

    def restart_agent(self, agent_id: str) -> None:
        self.agents[agent_id].journal.close()
        self.agents[agent_id] = self._agent(agent_id)

    def tick(self, dt=0.5):
        self.world.advance(dt)
        for a in self.agents.values():
            a.tick()
        self.coord.tick()

    def run_until(self, pred, limit=900.0):
        t0 = self.world.now
        while not pred():
            assert self.world.now - t0 <= limit, (self.coord.status()["run_state"],
                                                  [p["state"] for p in self.coord.status()["pairs"]],
                                                  self.world.log[-20:])
            self.tick()

    @property
    def run(self):
        return self.coord.run

    def executions(self, ctype: CommandType) -> list[str]:
        return [line for line in self.world.log if f" {ctype.value} ->" in line]


def test_four_agents_complete_two_cycles(tmp_path):
    f = Fleet(tmp_path, match_duration=20.0)
    f.run_until(lambda: f.run.ctx.cycles >= 2)
    assert len(f.executions(CommandType.START_GAMEPLAY)) == 8
    assert all(a.lease_attempt == "" for a in f.agents.values())


def test_lost_acks_never_execute_a_command_twice(tmp_path):
    f = Fleet(tmp_path, lossy_every=3, match_duration=15.0)
    f.run_until(lambda: f.run.ctx.cycles >= 1, limit=1500)
    executed = [cid for b in f.backends.values() for cid in b.executed]
    assert executed and len(executed) == len(set(executed))
    redelivered = sum(t.n // t.every for t in f.transports.values())
    assert redelivered > 10


def test_partition_in_match_revokes_lease_then_resumes(tmp_path):
    f = Fleet(tmp_path, match_duration=200.0)
    f.run_until(lambda: f.run.state is RunState.IN_MATCH and all(
        c.worker_running for c in f.world.clients.values()))
    f.transports["pc2"].down = True
    for _ in range(4):  # 2 s > lease TTL (1.5 s)
        f.tick()
    assert f.agents["pc2"].lease_attempt == ""
    assert not f.world.clients["pc2"].worker_running
    assert f.world.clients["pc1"].worker_running
    for _ in range(4):  # beyond OFFLINE: automation cancelled and inputs released
        f.tick()
    assert f.agents["pc2"].offline and "coordinator offline" in f.backends["pc2"].stops
    f.transports["pc2"].down = False
    f.run_until(lambda: f.world.clients["pc2"].worker_running, limit=30)
    f.run_until(lambda: f.run.ctx.cycles >= 1, limit=400)


def test_start_gameplay_without_lease_is_rejected(tmp_path):
    f = Fleet(tmp_path)
    agent = f.agents["pc1"]
    cmd = Command("manual-1", f.plan.run_id, "pc1", CommandType.START_GAMEPLAY, {"attempt_id": "x"},
                  "", 1, 45.0, f.world.now)
    agent._accept(cmd, f.world.now)
    agent.drain()
    state, res = agent.journal.known("manual-1")
    assert res.status is ResultStatus.REJECTED and res.reason == "gameplay_not_admitted"
    assert not f.world.clients["pc1"].worker_running


def test_expired_command_is_not_executed(tmp_path):
    f = Fleet(tmp_path)
    agent = f.agents["pc1"]
    cmd = Command("old-1", f.plan.run_id, "pc1", CommandType.LEAVE_LOBBY, {}, "", 1, 45.0, f.world.now - 100)
    agent._accept(cmd, f.world.now)
    agent.drain()
    assert agent.journal.known("old-1")[1].status is ResultStatus.EXPIRED
    assert not f.executions(CommandType.LEAVE_LOBBY)


def test_agent_restart_reports_interrupted_command_instead_of_rerunning(tmp_path):
    f = Fleet(tmp_path)
    agent = f.agents["pc3"]
    cmd = Command("mid-1", f.plan.run_id, "pc3", CommandType.INVITE, {}, "", 1, 45.0, f.world.now)
    assert agent.journal.begin(cmd)  # crash before finish
    f.restart_agent("pc3")
    state, res = f.agents["pc3"].journal.known("mid-1")
    assert state == "done" and res.status is ResultStatus.FAILED
    f.agents["pc3"]._accept(cmd, f.world.now)
    f.agents["pc3"].drain()
    assert not f.executions(CommandType.INVITE)


def test_safe_stop_preempts_and_releases(tmp_path):
    f = Fleet(tmp_path)
    agent = f.agents["pc1"]
    f.world.clients["pc1"].worker_running = True
    agent._accept(Command("stop-1", f.plan.run_id, "pc1", CommandType.SAFE_STOP, {}, "", 1, 10.0, f.world.now),
                  f.world.now)
    assert not f.world.clients["pc1"].worker_running


def test_http_server_roundtrip(tmp_path):
    store = FleetStore(tmp_path / "http.db")
    coord = Coordinator(store, token=TOKEN)
    server = FleetServer(coord, host="127.0.0.1", port=0).start()
    try:
        world = SimWorld(ACCOUNTS)
        journal = CommandJournal(tmp_path / "j.db")
        agent = AgentService("pc1", world.backend("pc1"), HttpTransport(f"http://127.0.0.1:{server.port}"),
                             journal, token=TOKEN, build_version="b", resource_manifest="m", inline=True)
        assert agent.tick()
        assert abs(agent.clock_offset) < 1.0
        req = urllib.request.Request(f"http://127.0.0.1:{server.port}/v1/status",
                                     headers={"X-Fleet-Token": TOKEN})
        with urllib.request.urlopen(req, timeout=2) as resp:
            status = json.loads(resp.read())
        assert status["agents"]["pc1"]["link"] == "healthy"
        bad = AgentService("pc1", world.backend("pc1"), HttpTransport(f"http://127.0.0.1:{server.port}"),
                           CommandJournal(tmp_path / "j2.db"), token="w" * 32, build_version="b",
                           resource_manifest="m", inline=True)
        assert not bad.tick() and "403" in bad.last_error
    finally:
        server.stop()
