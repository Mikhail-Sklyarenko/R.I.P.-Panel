"""Phase 01 regressions: cancel epoch, result ACK, ownership, and truthful state."""
from __future__ import annotations

import threading
import urllib.error
import urllib.request
from dataclasses import replace

from core.wingman_fleet import PROTOCOL_VERSION
from core.wingman_fleet.coordinator import Coordinator
from core.wingman_fleet.models import (
    Command, CommandResult, CommandType, GsiView, Identity, Link, LobbyView, MatchFingerprint,
    Observation, ResultStatus, Screen, to_dict,
)
from core.wingman_fleet.pair_fsm import ActiveCommand, PairCtx, PairMachine, PairState
from core.wingman_fleet.run_fsm import RunCtx, RunMachine, RunState
from core.wingman_fleet.server import FleetServer
from core.wingman_fleet.store import FleetStore
from modules.fleet_agent.backend import ExecContext
from modules.fleet_agent.journal import CommandJournal
from modules.fleet_agent.observe import ScreenEvidence
from modules.fleet_agent.preflight import Preflight
from modules.fleet_agent.service import AgentService
from modules.fleet_agent.transport import HttpTransport, TransportError
from tests.test_wingman_fleet_agents import Fleet
from tests.test_wingman_fleet_fsm import TOKEN, Harness, make_roster


def _cmd(cid: str, run: str, agent: str, ctype: CommandType, now: float = 1.0) -> Command:
    return Command(cid, run, agent, ctype, {}, "", 1, 45.0, now)


class _Boom:
    def __init__(self):
        self.stops: list[str] = []
        self.lease = ""

    def observe(self) -> Observation:
        return Observation("pc1", 1)

    def execute(self, cmd: Command, ctx: ExecContext) -> CommandResult:
        raise RuntimeError("disk")

    def set_gameplay(self, attempt_id: str) -> None:
        self.lease = attempt_id

    def safe_stop(self, reason: str) -> None:
        self.stops.append(reason)


class _Script:
    def __init__(self, body=None, error: str = ""):
        self.body = body or {"ok": True, "accepted_results": [], "commands": [], "run_id": "", "server_time": 1.0}
        self.error = error
        self.calls = 0

    def heartbeat(self, payload):
        self.calls += 1
        if self.error:
            raise TransportError(self.error)
        return dict(self.body)


def _service(tmp_path, backend, transport, *, now=None) -> AgentService:
    clock = (lambda: now[0]) if now is not None else (lambda: 0.0)
    return AgentService("pc1", backend, transport, CommandJournal(tmp_path / "j.db"), token=TOKEN,
                        build_version="b", resource_manifest="m", inline=True, clock=clock, wall=clock)


def _menu(agent: str, sid: str, name: str) -> Observation:
    return Observation(
        agent, 1, protocol=PROTOCOL_VERSION, build_version="test-build", resource_manifest="test-manifest",
        steam_running=True, cs2_running=True, steam_id64=sid, identity=Identity.STEAM_LOCAL,
        screen=Screen.MAIN_MENU, preflight_ok=True, lobby=LobbyView((name,), True, "", ""),
    )


# ----- queue and cancel ----------------------------------------------------------------------

def test_command_runs_once_and_redelivery_does_not_repeat(tmp_path):
    f = Fleet(tmp_path)
    agent = f.agents["pc1"]
    agent._rotate_run(f.plan.run_id)
    cmd = _cmd("once", f.plan.run_id, "pc1", CommandType.LEAVE_LOBBY, f.world.now)
    agent._accept(cmd, f.world.now)
    agent.drain()
    agent._accept(cmd, f.world.now)
    agent.drain()
    assert f.backends["pc1"].executed.count("once") == 1
    assert agent.journal.unacked()[0].command_id == "once"


def test_stale_deadline_and_stale_run_are_rejected(tmp_path):
    f = Fleet(tmp_path)
    agent = f.agents["pc1"]
    agent._rotate_run(f.plan.run_id)
    old = Command("old", f.plan.run_id, "pc1", CommandType.INVITE, {}, "", 1, 10.0, f.world.now - 50)
    agent._accept(old, f.world.now)
    agent.drain()
    assert agent.journal.known("old")[1].status is ResultStatus.EXPIRED
    foreign = _cmd("foreign", "run-other", "pc1", CommandType.INVITE, f.world.now)
    agent._accept(foreign, f.world.now)
    agent.drain()
    assert agent.journal.known("foreign")[1].status is ResultStatus.FAILED
    assert f.backends["pc1"].executed == []


def test_safe_stop_drops_queue_and_second_stop_is_safe(tmp_path):
    f = Fleet(tmp_path)
    agent = f.agents["pc1"]
    agent._rotate_run(f.plan.run_id)
    f.world.clients["pc1"].worker_running = True
    agent._accept(_cmd("queued", f.plan.run_id, "pc1", CommandType.INVITE, f.world.now), f.world.now)
    agent._accept(_cmd("stop-1", f.plan.run_id, "pc1", CommandType.SAFE_STOP, f.world.now), f.world.now)
    agent.drain()
    assert "queued" not in f.backends["pc1"].executed
    assert agent.journal.known("queued")[1].status is ResultStatus.FAILED
    assert not f.world.clients["pc1"].worker_running
    assert agent.session_stopped
    agent._accept(_cmd("stop-2", f.plan.run_id, "pc1", CommandType.SAFE_STOP, f.world.now), f.world.now)
    assert agent.journal.known("stop-2")[1].status is ResultStatus.COMPLETED
    agent._accept(_cmd("after", f.plan.run_id, "pc1", CommandType.INVITE, f.world.now), f.world.now)
    agent.drain()
    assert "after" not in f.backends["pc1"].executed


def test_new_run_does_not_resume_cancelled_session(tmp_path):
    f = Fleet(tmp_path)
    agent = f.agents["pc1"]
    agent._rotate_run("run-a")
    agent._accept(_cmd("old", "run-a", "pc1", CommandType.INVITE, f.world.now), f.world.now)
    agent._accept(_cmd("stop", "run-a", "pc1", CommandType.SAFE_STOP, f.world.now), f.world.now)
    agent._rotate_run("run-b")
    assert not agent.session_stopped
    agent._accept(_cmd("old-again", "run-a", "pc1", CommandType.INVITE, f.world.now), f.world.now)
    fresh = _cmd("fresh", "run-b", "pc1", CommandType.LEAVE_LOBBY, f.world.now)
    agent._accept(fresh, f.world.now)
    agent.drain()
    assert "old" not in f.backends["pc1"].executed
    assert "old-again" not in f.backends["pc1"].executed
    assert f.backends["pc1"].executed == ["stop", "fresh"]


def test_two_drain_threads_execute_each_command_once_in_order(tmp_path):
    f = Fleet(tmp_path)
    agent = f.agents["pc1"]
    agent._rotate_run(f.plan.run_id)
    ids = [f"n{i}" for i in range(6)]
    for cid in ids:
        agent._accept(_cmd(cid, f.plan.run_id, "pc1", CommandType.LEAVE_LOBBY, f.world.now), f.world.now)
    threads = [threading.Thread(target=agent.drain) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
    assert all(not thread.is_alive() for thread in threads)
    assert f.backends["pc1"].executed == ids


def test_popped_command_does_not_run_after_the_epoch_moves(tmp_path):
    f = Fleet(tmp_path)
    agent = f.agents["pc1"]
    agent._rotate_run(f.plan.run_id)
    agent._accept(_cmd("popped", f.plan.run_id, "pc1", CommandType.INVITE, f.world.now), f.world.now)
    cmd, epoch = agent.queue.popleft()
    agent._rotate_run("run-next")
    agent._run(cmd, epoch)
    assert "popped" not in f.backends["pc1"].executed
    assert agent.journal.known("popped")[1].status is ResultStatus.FAILED


def test_backend_exception_is_a_failure(tmp_path):
    backend = _Boom()
    agent = _service(tmp_path, backend, _Script())
    agent._accept(_cmd("boom", "run", "pc1", CommandType.INVITE), 0.0)
    agent.drain()
    result = agent.journal.known("boom")[1]
    assert result.status is ResultStatus.FAILED
    assert result.succeeded is False
    assert backend.stops == ["invite crashed"]


def test_shutdown_is_idempotent_and_blocks_the_queue(tmp_path):
    f = Fleet(tmp_path)
    agent = f.agents["pc1"]
    agent._rotate_run(f.plan.run_id)
    agent._accept(_cmd("q", f.plan.run_id, "pc1", CommandType.INVITE, f.world.now), f.world.now)
    agent.shutdown()
    agent.shutdown()
    assert f.backends["pc1"].stops.count("agent shutdown") == 1
    assert "q" not in f.backends["pc1"].executed
    agent.drain()
    assert "q" not in f.backends["pc1"].executed


def test_gameplay_lease_expires_and_does_not_extend_itself(tmp_path):
    now = [0.0]
    backend = _Boom()
    agent = _service(tmp_path, backend, _Script(), now=now)
    agent._set_lease({"attempt_id": "wave", "ttl_sec": 1.5}, 0.0)
    now[0] = 1.4
    agent.enforce_lease()
    assert agent.lease_attempt == "wave"
    now[0] = 1.6
    agent.enforce_lease()
    assert agent.lease_attempt == ""
    agent.enforce_lease()
    assert agent.lease_attempt == ""


# ----- network -------------------------------------------------------------------------------

def test_false_ok_without_accepted_list_does_not_ack(tmp_path):
    backend = _Boom()
    transport = _Script({"ok": False, "error": "nope"})
    agent = _service(tmp_path, backend, transport)
    cmd = _cmd("r1", "run", "pc1", CommandType.INVITE)
    assert agent.journal.begin(cmd)
    agent.journal.finish(CommandResult("r1", ResultStatus.COMPLETED))
    assert agent.tick() is False
    assert [r.command_id for r in agent.journal.unacked()] == ["r1"]


def test_transport_outage_keeps_the_result(tmp_path):
    agent = _service(tmp_path, _Boom(), _Script(error="down"))
    assert agent.journal.begin(_cmd("r2", "run", "pc1", CommandType.INVITE))
    agent.journal.finish(CommandResult("r2", ResultStatus.FAILED, "command_failed"))
    assert agent.tick() is False
    assert [r.command_id for r in agent.journal.unacked()] == ["r2"]


def test_protocol_mismatch_records_result_but_sends_no_commands(tmp_path):
    store = FleetStore(tmp_path / "c.db")
    coord = Coordinator(store, token=TOKEN, clock=lambda: 10.0)
    plan = make_roster().build_plan(build_version="b", resource_manifest="m", now=10.0)
    coord.start_run(plan)
    cmd = coord.agent_command("pc1", CommandType.SCREENSHOT)
    obs = to_dict(Observation("pc1", 1, protocol=99))
    code, resp = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": "boot", "observation": obs,
        "results": [to_dict(CommandResult(cmd.command_id, ResultStatus.COMPLETED))],
    })
    assert code == 200 and resp["ok"] is False and resp["error"] == "protocol_mismatch"
    assert resp["commands"] == []
    assert resp["accepted_results"] == [cmd.command_id]
    assert store.results(plan.run_id)[cmd.command_id].status is ResultStatus.COMPLETED
    store.close()


def test_wrong_agent_cannot_complete_another_agents_command(tmp_path):
    store = FleetStore(tmp_path / "c.db")
    coord = Coordinator(store, token=TOKEN, clock=lambda: 10.0)
    plan = make_roster().build_plan(build_version="b", resource_manifest="m", now=10.0)
    coord.start_run(plan)
    cmd = coord.agent_command("pc1", CommandType.SCREENSHOT)
    other = coord.agent_command("pc2", CommandType.SCREENSHOT)
    code, resp = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": "b2", "observation": to_dict(Observation("pc2", 1)),
        "results": [to_dict(CommandResult(cmd.command_id, ResultStatus.COMPLETED, detail="stolen"))],
    })
    assert code == 200 and resp["ok"] is True
    assert cmd.command_id not in resp["accepted_results"]
    assert [c.command_id for c in store.pending_for("pc1", plan.run_id)] == [cmd.command_id]
    assert coord.handle_heartbeat({"token": "x" * 32, "observation": to_dict(Observation("pc1", 1))})[0] == 403
    stored = store.record_result(CommandResult(other.command_id, ResultStatus.FAILED, "command_failed"),
                                 agent_id="pc2", run_id=plan.run_id)
    assert stored
    rows = {row["command_id"]: row["status"] for row in store.command_rows(plan.run_id, limit=10)}
    assert rows[other.command_id] == "failed"
    assert rows[cmd.command_id] == "pending"
    store.close()


def test_lost_ack_is_recovered_after_coordinator_restart(tmp_path):
    f = Fleet(tmp_path)
    f.run_until(lambda: any(b.executed for b in f.backends.values()), limit=40)
    agent_id = next(aid for aid, backend in f.backends.items() if backend.executed)
    cid = f.backends[agent_id].executed[0]
    f.agents[agent_id].journal.requeue_result(cid)
    f.store.close()
    store = FleetStore(f.tmp / "fleet.db")
    coord = Coordinator(store, token=TOKEN, clock=lambda: f.world.now)
    f.transports[agent_id].coordinator = coord
    assert f.agents[agent_id].tick() is True
    assert all(result.command_id != cid for result in f.agents[agent_id].journal.unacked())
    assert cid in store.results(f.plan.run_id)
    store.close()


def test_link_loss_then_restore_accepts_the_same_run(tmp_path):
    f = Fleet(tmp_path, match_duration=200.0)
    f.run_until(lambda: f.run.state is RunState.IN_MATCH and all(
        client.worker_running for client in f.world.clients.values()))
    f.transports["pc2"].down = True
    for _ in range(8):
        f.tick()
    assert f.agents["pc2"].offline
    assert not f.agents["pc2"].session_stopped
    f.transports["pc2"].down = False
    f.run_until(lambda: f.world.clients["pc2"].worker_running, limit=40)


def test_http_rejects_bad_json_and_bad_auth(tmp_path):
    store = FleetStore(tmp_path / "http.db")
    coord = Coordinator(store, token=TOKEN)
    server = FleetServer(coord, host="127.0.0.1", port=0).start()
    try:
        url = f"http://127.0.0.1:{server.port}/v1/heartbeat"
        req = urllib.request.Request(url, data=b"{", method="POST")
        try:
            urllib.request.urlopen(req, timeout=2)
            raise AssertionError("bad json was accepted")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
        agent = AgentService(
            "pc1", _Boom(), HttpTransport(f"http://127.0.0.1:{server.port}"),
            CommandJournal(tmp_path / "hj.db"), token="nope-nope-nope-nope-nope",
            build_version="b", resource_manifest="m", inline=True,
        )
        assert agent.tick() is False
        assert "403" in agent.last_error
    finally:
        server.stop()
        store.close()


# ----- state ---------------------------------------------------------------------------------

def test_post_match_timeout_is_not_a_successful_cycle(tmp_path):
    plan = make_roster().build_plan(build_version="b", resource_manifest="m", now=0.0)
    agents = plan.agent_ids
    links = {agent: Link.HEALTHY for agent in agents}
    stuck = {agent: Observation(agent, 1, screen=Screen.IN_MATCH, cs2_running=True, steam_running=True,
                                identity=Identity.STEAM_LOCAL) for agent in agents}
    timeout = RunMachine(plan, {}, RunCtx(state=RunState.POST_MATCH, entered_at=0.0))
    timeout.step(200.0, stuck, links, {}, 200.0)
    assert timeout.ctx.cycles == 0
    assert timeout.ctx.failed_cycles == 1
    assert timeout.state is RunState.PREPARING

    done = RunMachine(plan, {}, RunCtx(state=RunState.POST_MATCH, entered_at=0.0))
    menu = {agent: Observation(agent, 1, screen=Screen.MAIN_MENU, cs2_running=True, steam_running=True,
                               identity=Identity.STEAM_LOCAL) for agent in agents}
    done.step(1.0, menu, links, {}, 1.0)
    assert done.ctx.cycles == 1
    assert done.ctx.failed_cycles == 0


def test_unconfirmed_search_does_not_abort_the_wave():
    plan = make_roster().build_plan(build_version="b", resource_manifest="m", now=0.0)
    agents = plan.agent_ids
    leaders = [pair.leader.agent_id for pair in plan.pairs]
    issued = {agent: f"search-{agent}" for agent in leaders}
    links = {agent: Link.HEALTHY for agent in agents}

    def obs(screen: Screen = Screen.MAIN_MENU, stable: float = 0.0):
        return {agent: Observation(agent, 1, steam_running=True, cs2_running=True,
                                   identity=Identity.STEAM_LOCAL, screen=screen, screen_stable_sec=stable)
                for agent in agents}

    waiting = RunMachine(plan, {}, RunCtx(state=RunState.SEARCH_ARMED, entered_at=0.0, issued=dict(issued)))
    unconfirmed = {cid: CommandResult(cid, ResultStatus.UNCONFIRMED, "effect_unconfirmed")
                   for cid in issued.values()}
    waiting.step(1.0, obs(), links, unconfirmed, 1.0)
    assert waiting.state is RunState.SEARCH_ARMED

    waiting.step(2.0, obs(Screen.SEARCHING, 1.0), links, unconfirmed, 2.0)
    assert waiting.state is RunState.SEARCHING

    failed = RunMachine(plan, {}, RunCtx(state=RunState.SEARCH_ARMED, entered_at=0.0, issued=dict(issued)))
    bad = dict(unconfirmed)
    bad[issued[leaders[0]]] = CommandResult(issued[leaders[0]], ResultStatus.FAILED, "search_not_started")
    failed.step(1.0, obs(), links, bad, 1.0)
    assert failed.state is RunState.PREPARING
    assert failed.ctx.reason == "search_not_started"

    late = RunMachine(plan, {}, RunCtx(state=RunState.SEARCH_ARMED, entered_at=0.0, issued=dict(issued)))
    late.step(46.0, obs(), links, unconfirmed, 46.0)
    assert late.state is RunState.PREPARING
    assert late.ctx.reason == "search_desync"


def test_repeated_unconfirmed_clicks_stay_bounded(tmp_path):
    plan = make_roster().build_plan(build_version="test-build", resource_manifest="test-manifest", now=0.0)
    pair = plan.pairs[0]
    machine = PairMachine(plan, pair, PairCtx(state=PairState.LOBBY_CONFIGURE))
    obs = {
        pair.leader.agent_id: _menu(pair.leader.agent_id, pair.leader.steam_id64, pair.leader.display_name),
        pair.follower.agent_id: _menu(pair.follower.agent_id, pair.follower.steam_id64, pair.follower.display_name),
    }
    links = {pair.leader.agent_id: Link.HEALTHY, pair.follower.agent_id: Link.HEALTHY}
    results: dict[str, CommandResult] = {}
    now = 0.0
    issued = 0
    for _ in range(40):
        active = machine.ctx.active
        if active is not None:
            results[active.command_id] = CommandResult(
                active.command_id, ResultStatus.UNCONFIRMED, "effect_unconfirmed")
        issued += len(machine.step(now, obs, links, results))
        if machine.state in (PairState.RECOVER_CS2, PairState.RECOVER_STEAM, PairState.PAUSED, PairState.MANUAL):
            break
        now += 7.0
    assert machine.state is not PairState.READY
    assert machine.state in (PairState.RECOVER_CS2, PairState.RECOVER_STEAM, PairState.PAUSED, PairState.MANUAL)
    assert issued < 20


def test_empty_lobby_is_not_a_wrong_roster():
    plan = make_roster().build_plan(build_version="test-build", resource_manifest="test-manifest", now=0.0)
    pair = plan.pairs[0]
    empty = {
        pair.leader.agent_id: replace(_menu(pair.leader.agent_id, pair.leader.steam_id64, pair.leader.display_name),
                                      lobby=LobbyView()),
        pair.follower.agent_id: replace(
            _menu(pair.follower.agent_id, pair.follower.steam_id64, pair.follower.display_name), lobby=LobbyView()),
    }
    links = {pair.leader.agent_id: Link.HEALTHY, pair.follower.agent_id: Link.HEALTHY}
    configure = PairMachine(plan, pair, PairCtx(state=PairState.LOBBY_CONFIGURE))
    commands = configure.step(1.0, empty, links, {})
    assert configure.state is PairState.LOBBY_CONFIGURE
    assert all(command.type is not CommandType.LEAVE_LOBBY for command in commands)

    reset = PairMachine(plan, pair, PairCtx(state=PairState.LOBBY_RESET))
    assert reset.step(1.0, empty, links, {}) == []
    assert reset.state is PairState.LOBBY_RESET

    stranger = {
        agent: replace(view, lobby=LobbyView(("Stranger", "Other"), True, "", ""))
        for agent, view in empty.items()
    }
    wrong = PairMachine(plan, pair, PairCtx(state=PairState.LOBBY_CONFIGURE))
    wrong.step(1.0, stranger, links, {})
    assert wrong.state is PairState.LOBBY_RESET


def test_protocol_v2_serves_all_four_agents_and_drops_an_old_agent(tmp_path):
    store = FleetStore(tmp_path / "c.db")
    coord = Coordinator(store, token=TOKEN, clock=lambda: 10.0)
    plan = make_roster().build_plan(build_version="b", resource_manifest="m", now=10.0)
    coord.start_run(plan)
    commands = {agent_id: coord.agent_command(agent_id, CommandType.SCREENSHOT) for agent_id in plan.agent_ids}
    for index, agent_id in enumerate(plan.agent_ids):
        code, resp = coord.handle_heartbeat({
            "token": TOKEN, "boot_id": f"boot-{agent_id}",
            "observation": to_dict(Observation(agent_id, 1, protocol=PROTOCOL_VERSION)),
        })
        assert code == 200 and resp["ok"] is True and resp["protocol"] == 2
        assert [command["agent_id"] for command in resp["commands"]] == [agent_id]
    code, old = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": "legacy",
        "observation": to_dict(Observation("pc1", 2, protocol=1)),
        "results": [to_dict(CommandResult("missing", ResultStatus.UNCONFIRMED, "effect_unconfirmed"))],
    })
    assert code == 200 and old["ok"] is False and old["error"] == "protocol_mismatch"
    assert old["commands"] == [] and old["protocol"] == PROTOCOL_VERSION
    assert old["accepted_results"] == []
    code, current = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": "boot-pc2",
        "observation": to_dict(Observation("pc2", 2, protocol=PROTOCOL_VERSION)),
    })
    assert code == 200 and current["ok"] is True and current["commands"]
    code, ack = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": "boot-pc4",
        "observation": to_dict(Observation("pc4", 2, protocol=PROTOCOL_VERSION)),
        "results": [to_dict(CommandResult(commands["pc4"].command_id, ResultStatus.UNCONFIRMED,
                                          "effect_unconfirmed"))],
    })
    assert code == 200 and ack["ok"] is True
    assert commands["pc4"].command_id in ack["accepted_results"]
    assert store.results(plan.run_id)[commands["pc4"].command_id].status is ResultStatus.UNCONFIRMED
    code, bad = coord.handle_heartbeat({
        "token": TOKEN, "boot_id": "boot-pc3",
        "observation": to_dict(Observation("pc3", 2, protocol=PROTOCOL_VERSION)),
        "results": [{"command_id": "x", "status": "clicked"}],
    })
    assert code == 400
    store.close()


def test_unconfirmed_click_waits_for_observation(tmp_path):
    plan = make_roster().build_plan(build_version="test-build", resource_manifest="test-manifest", now=0.0)
    pair = plan.pairs[0]
    machine = PairMachine(plan, pair, PairCtx(
        state=PairState.LOBBY_CONFIGURE,
        active=ActiveCommand("c1", pair.leader.agent_id, "configure_lobby", 0.0, "lobby_configure"),
    ))
    obs = {
        pair.leader.agent_id: _menu(pair.leader.agent_id, pair.leader.steam_id64, pair.leader.display_name),
        pair.follower.agent_id: _menu(pair.follower.agent_id, pair.follower.steam_id64, pair.follower.display_name),
    }
    links = {pair.leader.agent_id: Link.HEALTHY, pair.follower.agent_id: Link.HEALTHY}
    result = CommandResult("c1", ResultStatus.UNCONFIRMED, "effect_unconfirmed")
    assert result.succeeded is False and result.terminal
    commands = machine.step(10.0, obs, links, {"c1": result})
    assert commands == []
    assert machine.state is PairState.LOBBY_CONFIGURE
    assert machine.ctx.step_index == 0
    assert machine.ctx.stage_attempts == 0
    assert machine.ctx.last_failure == ""
    assert machine.ctx.confirm_until == 16.0


def test_preflight_cache_expires_without_rerunning_expensive_checks():
    calls = {"slow": 0, "fast": 0}

    def slow():
        calls["slow"] += 1
        return True, "installed"

    def fast():
        calls["fast"] += 1
        return True, "up"

    clock = [0.0]
    preflight = Preflight([("slow", slow, 30.0), ("fast", fast, 1.0)], clock=lambda: clock[0])
    preflight.run()
    clock[0] = 31.0
    cached = {item.code: item for item in preflight.cached()}
    assert cached["slow"].ok is False and cached["slow"].detail == "stale"
    observed = {item.code: item for item in preflight.refresh_for_observation()}
    assert calls == {"slow": 1, "fast": 2}
    assert observed["slow"].detail == "stale"
    assert observed["fast"].ok is True


def test_stale_gsi_and_old_fingerprint_are_not_ready(monkeypatch, tmp_path):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    from config.loader import ensure_config
    ensure_config()
    from PIL import Image
    from modules.fleet_agent.live import WindowsBackend

    backend = WindowsBackend(agent_id="pc1", capture=lambda: Image.new("RGB", (8, 8)))
    try:
        class _Gsi:
            def __init__(self, age: float):
                self.age = age

            def view(self):
                return GsiView(age_sec=self.age, steam_id64="76561198000000010", mode="scrimcomp2v2",
                               map_id="de_inferno", map_phase="live")

            def roster_names(self):
                return ("Alpha", "Bravo")

            def server_token(self):
                return "10.0.0.8:27015"

            def close(self):
                return None

        backend.gsi = _Gsi(9.0)
        ok, detail = backend._check_gsi()
        assert ok is False and "stale" in detail
        backend.gsi = _Gsi(0.4)
        assert backend._check_gsi()[0] is True

        monkeypatch.setattr("modules.fleet_agent.live.steam_running", lambda: True)
        monkeypatch.setattr("modules.fleet_agent.live.cs2_running", lambda: True)
        monkeypatch.setattr("modules.fleet_agent.live.time.sleep", lambda _s: None)
        backend._last_fp = MatchFingerprint("old-server", ("Alpha", "Bravo"), 0.0)
        backend._lobby = LobbyView(("Alpha",), True, "wingman", "de_inferno")
        backend.observer.classify = lambda *args, **kwargs: ScreenEvidence(Screen.MAIN_MENU, 1.0, "menu")
        observed = backend.observe()
        assert observed.lobby.members == ()
        assert observed.fingerprint is None
        assert backend._last_fp is None

        backend.observer.click_point = lambda name: (4, 4)
        monkeypatch.setattr("modules.ui_nav.window.find_cs2_hwnd", lambda: 1)
        monkeypatch.setattr("modules.ui_nav.actions.click_client", lambda *args, **kwargs: None)
        clicked = backend._click_seq(
            _cmd("click", "run", "pc1", CommandType.CONFIGURE_LOBBY),
            ExecContext(threading.Event(), lambda: 0.0, lambda: ""),
            ["play"],
        )
        assert clicked.status is ResultStatus.UNCONFIRMED
        assert clicked.succeeded is False
        assert backend._lobby.members == ()
    finally:
        backend.close()


def test_journal_reopen_keeps_terminal_result(tmp_path):
    path = tmp_path / "journal.db"
    journal = CommandJournal(path)
    cmd = _cmd("mid", "run", "pc1", CommandType.INVITE)
    assert journal.begin(cmd)
    journal.close()
    reopened = CommandJournal(path)
    state, result = reopened.known("mid")
    assert state == "done" and result.status is ResultStatus.FAILED
    assert reopened.begin(cmd) is False
    reopened.close()


# ----- four agents ---------------------------------------------------------------------------

def test_four_agents_addressing_stop_restart_and_sqlite(tmp_path):
    f = Fleet(tmp_path, match_duration=25.0)
    for _ in range(3):
        f.tick()
    status = f.coord.status()
    assert set(status["agents"]) == {"pc1", "pc2", "pc3", "pc4"}
    assert all(item["link"] == "healthy" for item in status["agents"].values())

    shot = f.coord.agent_command("pc1", CommandType.SCREENSHOT)
    f.tick()
    f.tick()
    assert shot.command_id in f.backends["pc1"].executed
    assert shot.command_id not in f.backends["pc2"].executed
    stolen = CommandResult(shot.command_id, ResultStatus.COMPLETED, detail="from-pc3")
    code, resp = f.coord.handle_heartbeat({
        "token": TOKEN, "boot_id": "outsider", "computer": "pc3",
        "observation": to_dict(f.world.observe("pc3")),
        "results": [to_dict(stolen)],
    })
    assert code == 200
    assert shot.command_id not in resp["accepted_results"]
    stored = f.store.results(f.plan.run_id).get(shot.command_id)
    assert stored is None or stored.detail != "from-pc3"

    f.coord.stop_run()
    f.run_until(lambda: f.run.state is RunState.STOPPED, limit=30)
    assert all(agent.lease_attempt == "" for agent in f.agents.values())
    assert all(agent.session_stopped for agent in f.agents.values())
    f.agents["pc1"]._accept(_cmd("late", f.plan.run_id, "pc1", CommandType.INVITE, f.world.now), f.world.now)
    f.agents["pc1"].drain()
    assert "late" not in f.backends["pc1"].executed
    before = [cid for backend in f.backends.values() for cid in backend.executed]

    f.store.close()
    store = FleetStore(f.tmp / "fleet.db")
    coord = Coordinator(store, token=TOKEN, clock=lambda: f.world.now)
    for transport in f.transports.values():
        transport.coordinator = coord
    for _ in range(4):
        f.world.advance(0.5)
        for agent in f.agents.values():
            agent.tick()
        coord.tick()
    after = [cid for backend in f.backends.values() for cid in backend.executed]
    assert after == before
    assert len(after) == len(set(after))
    rows = store.command_rows(f.plan.run_id, limit=200)
    assert rows
    assert any(row["status"] in {"completed", "failed", "expired"} for row in rows)
    assert len({row["command_id"] for row in rows}) == len(rows)
    store.close()


def test_restarting_an_agent_replaces_the_single_service(tmp_path):
    f = Fleet(tmp_path)
    first = f.agents["pc4"]
    f.restart_agent("pc4")
    assert f.agents["pc4"] is not first
    assert list(f.agents) == ["pc1", "pc2", "pc3", "pc4"]


def test_host_stop_joins_before_a_second_shutdown(tmp_path):
    from modules.fleet_agent.host import FleetHost

    order: list[str] = []

    class _Agent:
        agent_id = "pc1"

        def stop(self):
            order.append("stop")

        def shutdown(self):
            order.append("shutdown")

    def _thread():
        order.append("thread")

    host = FleetHost()
    host.agent = _Agent()
    host._thread = threading.Thread(target=_thread)
    host._thread.start()
    host.stop()
    assert order.index("stop") < order.index("shutdown")
    assert host.agent is None


def test_harness_duplicate_result_stays_terminal(tmp_path):
    h = Harness(tmp_path)
    cmd = h.coord.agent_command("pc1", CommandType.SCREENSHOT)
    assert h.store.record_result(CommandResult(cmd.command_id, ResultStatus.COMPLETED),
                                 agent_id="pc1", run_id=h.plan.run_id)
    assert not h.store.record_result(CommandResult(cmd.command_id, ResultStatus.FAILED, "late"),
                                     agent_id="pc1", run_id=h.plan.run_id)
    assert not h.store.record_result(CommandResult(cmd.command_id, ResultStatus.COMPLETED),
                                     agent_id="pc2", run_id=h.plan.run_id)
    assert h.store.results(h.plan.run_id)[cmd.command_id].status is ResultStatus.COMPLETED
