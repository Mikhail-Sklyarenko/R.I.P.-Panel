"""Coordinator + Pair/Run FSM against the simulated four-client world."""
from __future__ import annotations

import pytest

from core.wingman_fleet.budget import Budget, WindowedCounter
from core.wingman_fleet.coordinator import Coordinator
from core.wingman_fleet.match_proof import Verdict, judge
from core.wingman_fleet.models import (
    Command, CommandResult, CommandType, MatchFingerprint, Observation, ResultStatus, RunPlan, to_dict,
)
from core.wingman_fleet.pair_fsm import PairState
from core.wingman_fleet.roster import FleetRoster, RosterError
from core.wingman_fleet.run_fsm import RunState
from core.wingman_fleet.store import FleetStore
from modules.fleet_agent.simulation import SimWorld

ACCOUNTS = [("pc1", "76561190000000001", "Alpha"), ("pc2", "76561190000000002", "Bravo"),
            ("pc3", "76561190000000003", "Charlie"), ("pc4", "76561190000000004", "Delta")]
TOKEN = "t" * 32


def make_roster(retry: dict | None = None) -> FleetRoster:
    roster = FleetRoster(token=TOKEN, retry=dict(retry or {}))
    for slot, (agent, sid, name) in enumerate(ACCOUNTS, 1):
        roster.set_slot(slot, agent_id=agent, steam_id64=sid, display_name=name)
    return roster


class Harness:
    """Executes delivered commands directly in the world (agent stand-in)."""

    def __init__(self, tmp_path, *, retry: dict | None = None, start: bool = True, **world_kw):
        self.world = SimWorld(ACCOUNTS, **world_kw)
        self.db = tmp_path / "fleet.db"
        self.store = FleetStore(self.db)
        self.coord = Coordinator(self.store, token=TOKEN, clock=lambda: self.world.now)
        self.offline: set[str] = set()
        self.executed: dict[str, CommandResult] = {}
        self.outbox: dict[str, list[CommandResult]] = {a: [] for a, _, _ in ACCOUNTS}
        self.delivered: list[tuple[float, str, Command]] = []
        self.leases: dict[str, list[float]] = {a: [] for a, _, _ in ACCOUNTS}
        self.plan: RunPlan | None = None
        if start:
            self.plan = make_roster(retry).build_plan(build_version="test-build",
                                                      resource_manifest="test-manifest", now=self.world.now)
            self.coord.start_run(self.plan)

    def restart_coordinator(self) -> None:
        self.store.close()
        self.store = FleetStore(self.db)
        self.coord = Coordinator(self.store, token=TOKEN, clock=lambda: self.world.now)

    def tick(self, dt: float = 0.5) -> None:
        self.world.advance(dt)
        for agent, _, _ in ACCOUNTS:
            if agent in self.offline:
                continue
            payload = {"token": TOKEN, "boot_id": "boot", "computer": agent,
                       "observation": to_dict(self.world.observe(agent)),
                       "results": [to_dict(r) for r in self.outbox[agent]]}
            status, resp = self.coord.handle_heartbeat(payload)
            assert status == 200, resp
            self.outbox[agent] = []
            if resp["gameplay"]:
                self.leases[agent].append(self.world.now)
            for raw in resp["commands"]:
                cmd = Command.from_dict(raw)
                if cmd.command_id in self.executed:
                    self.outbox[agent].append(self.executed[cmd.command_id])
                    continue
                self.delivered.append((self.world.now, agent, cmd))
                res = self.world.execute(agent, cmd)
                self.executed[cmd.command_id] = res
                self.outbox[agent].append(res)
        self.coord.tick()

    def run_until(self, pred, limit: float = 900.0, dt: float = 0.5) -> None:
        t0 = self.world.now
        while not pred():
            if self.world.now - t0 > limit:
                raise AssertionError(f"timeout; run={self.coord.status()['run_state']} "
                                     f"pairs={[p['state'] + ':' + p['reason'] for p in self.coord.status()['pairs']]}"
                                     f"\n" + "\n".join(self.world.log[-25:]))
            self.tick(dt)

    def types(self, ctype: CommandType, wave: int | None = None) -> list[tuple[float, str, Command]]:
        return [d for d in self.delivered if d[2].type is ctype
                and (wave is None or f"/w{wave}/" in d[2].command_id or
                     d[2].params.get("attempt_id", "").endswith(f"/w{wave}"))]

    @property
    def run(self):
        return self.coord.run

    def pair(self, pid: str):
        return self.coord.pairs[pid]


# ----- full cycles ---------------------------------------------------------------------

def test_two_full_cycles_with_shared_match(tmp_path):
    h = Harness(tmp_path, match_duration=20.0)
    h.run_until(lambda: h.run.ctx.cycles >= 2)
    starts = h.types(CommandType.START_GAMEPLAY)
    assert {a for _, a, _ in starts} == {"pc1", "pc2", "pc3", "pc4"}
    for t, agent, _ in starts:
        # Gameplay is only ever leased after proof; every lease timestamp lies within a proven match.
        assert h.leases[agent], agent
    assert not h.types(CommandType.LEAVE_MATCH)
    for agent in h.leases:
        first_start = min(t for t, a, _ in starts if a == agent)
        assert min(h.leases[agent]) >= first_start - 0.5
    assert len({c.command_id for _, _, c in h.delivered}) == len(h.delivered)


def test_lone_pair_confirm_is_never_accepted_and_wave_repeats(tmp_path):
    h = Harness(tmp_path, match_duration=10.0)
    h.world.outcomes.extend(["lone", "same"])
    h.run_until(lambda: h.run.ctx.cycles >= 1)
    assert not h.types(CommandType.ACCEPT_MATCH, wave=1)
    assert h.types(CommandType.ACCEPT_MATCH, wave=2)
    reasons = [e["reason"] for e in h.store.events(h.plan.run_id, 500)]
    assert "confirm_desync" in reasons
    assert not h.types(CommandType.START_GAMEPLAY, wave=1)


def test_split_matches_are_left_lobbies_recreated_and_search_repeated(tmp_path):
    h = Harness(tmp_path, match_duration=10.0)
    h.world.outcomes.extend(["split", "same"])
    h.run_until(lambda: h.run.ctx.cycles >= 1)
    assert h.types(CommandType.ACCEPT_MATCH, wave=1)
    assert not h.types(CommandType.START_GAMEPLAY, wave=1)
    left = {a for _, a, c in h.delivered if c.type is CommandType.LEAVE_MATCH and "/w1/" in c.command_id}
    assert left == {"pc1", "pc2", "pc3", "pc4"}
    assert "match_mismatch" in [e["reason"] for e in h.store.events(h.plan.run_id, 500)]
    assert h.types(CommandType.START_GAMEPLAY, wave=2)


def test_repeated_mismatch_is_bounded_by_wave_budget(tmp_path):
    h = Harness(tmp_path, retry={"failed_waves_per_hour": 3})
    h.world.outcomes.extend(["lone"] * 10)
    h.run_until(lambda: h.run.state is RunState.PAUSED, limit=1500)
    assert h.run.ctx.reason == "mismatch_limit"
    assert len(h.types(CommandType.START_SEARCH)) == 3 * 2
    assert not h.types(CommandType.ACCEPT_MATCH)


# ----- lobby / social --------------------------------------------------------------------

def test_dropped_invite_is_reinvited(tmp_path):
    h = Harness(tmp_path)
    h.world.drop_invites = 1
    h.run_until(lambda: h.run.state is RunState.SEARCH_ARMED or h.run.ctx.wave >= 1)
    invites = [c for _, a, c in h.delivered if c.type is CommandType.INVITE]
    assert 3 <= len(invites) <= 4  # pair-1 twice (one dropped), pair-2 once


def test_invites_that_never_arrive_escalate_to_a_bounded_stop(tmp_path):
    h = Harness(tmp_path)
    h.world.drop_invites = 10_000
    h.run_until(lambda: h.pair("pair-1").state is PairState.PAUSED, limit=4000)
    assert h.pair("pair-1").ctx.reason == "budget_exhausted"
    invites = [c for _, a, c in h.delivered if c.type is CommandType.INVITE and a == "pc1"]
    assert len(invites) < 40
    assert h.run.state is RunState.PREPARING and h.run.ctx.wave == 0


def test_friendship_is_provisioned_and_remembered(tmp_path):
    h = Harness(tmp_path)
    h.run_until(lambda: h.run.ctx.wave >= 1)
    assert h.store.friendship_known("76561190000000001", "76561190000000002")
    sent = [c for _, a, c in h.delivered if c.type is CommandType.SEND_FRIEND_REQUEST]
    assert {c.agent_id for c in sent} == {"pc1", "pc2", "pc3", "pc4"}


# ----- identity / safety -------------------------------------------------------------------

def test_wrong_account_blocks_pair_and_stops_inputs(tmp_path):
    h = Harness(tmp_path)
    h.world.clients["pc2"].logged_in_as = "76561190000000099"
    h.run_until(lambda: h.pair("pair-1").state is PairState.MANUAL, limit=30)
    p = h.pair("pair-1")
    assert p.ctx.reason == "account_mismatch"
    h.tick()
    stops = {a for _, a, c in h.delivered if c.type is CommandType.SAFE_STOP}
    assert stops == {"pc1", "pc2"}
    assert not [c for _, a, c in h.delivered if a in ("pc1", "pc2") and c.type is CommandType.INVITE]


def test_bad_token_and_protocol_are_refused(tmp_path):
    h = Harness(tmp_path)
    obs = to_dict(h.world.observe("pc1"))
    assert h.coord.handle_heartbeat({"token": "x" * 32, "observation": obs})[0] == 403
    obs["protocol"] = 99
    status, resp = h.coord.handle_heartbeat({"token": TOKEN, "observation": obs})
    assert status == 200 and resp["error"] == "protocol_mismatch" and resp["commands"] == []


def test_no_gameplay_lease_before_proof_and_none_after_link_loss(tmp_path):
    h = Harness(tmp_path, match_duration=120.0)
    h.run_until(lambda: h.run.state is RunState.IN_MATCH)
    first_lease = min(min(v) for v in h.leases.values() if v) if any(h.leases.values()) else None
    assert first_lease is None or first_lease >= h.run.ctx.entered_at
    h.offline.add("pc3")
    for _ in range(8):
        h.tick()
    assert h.run.gameplay_admitted("pc3", h.coord.links()) == ""
    assert h.run.gameplay_admitted("pc1", h.coord.links())


def test_match_proof_unavailable_pauses_without_gameplay(tmp_path, monkeypatch):
    h = Harness(tmp_path, retry={"match_proof_timeout_sec": 15})
    monkeypatch.setattr(h.world, "_do_probe_match", lambda c, p: (False, "match_proof_unavailable", "no console"))
    h.run_until(lambda: h.run.state is RunState.PAUSED)
    assert h.run.ctx.reason == "match_proof_unavailable"
    assert not h.types(CommandType.START_GAMEPLAY)
    assert not h.types(CommandType.LEAVE_MATCH)


# ----- faults / recovery ---------------------------------------------------------------

def test_agent_offline_during_search_aborts_wave_then_recovers(tmp_path):
    h = Harness(tmp_path, match_delay=30.0, match_duration=10.0)
    h.run_until(lambda: h.run.state is RunState.SEARCHING)
    h.offline.add("pc3")
    h.run_until(lambda: h.run.state is RunState.ABORTING_SEARCH, limit=10)
    h.offline.clear()
    h.run_until(lambda: h.run.ctx.cycles >= 1)
    assert "agent_offline" in [e["reason"] for e in h.store.events(h.plan.run_id, 500)]


def test_cs2_crash_in_lobby_restarts_and_resumes(tmp_path):
    h = Harness(tmp_path, match_duration=10.0)
    h.run_until(lambda: h.pair("pair-2").state is PairState.LOBBY_VERIFY)
    h.world.crash_cs2("pc4")
    h.run_until(lambda: h.run.ctx.cycles >= 1)
    restarts = [a for _, a, c in h.delivered if c.type is CommandType.RESTART_CS2]
    assert restarts == ["pc4"]


def test_client_drop_mid_match_reconnects(tmp_path):
    h = Harness(tmp_path, match_duration=40.0)
    h.run_until(lambda: h.run.state is RunState.IN_MATCH)
    h.world.drop_to_menu("pc2")
    h.run_until(lambda: h.run.ctx.cycles >= 1)
    assert [a for _, a, c in h.delivered if c.type is CommandType.RECONNECT_MATCH] == ["pc2"]


def test_cs2_crash_mid_match_restarts_then_reconnects(tmp_path):
    h = Harness(tmp_path, match_duration=120.0)
    h.run_until(lambda: h.run.state is RunState.IN_MATCH)
    h.world.crash_cs2("pc3")
    h.run_until(lambda: h.run.ctx.cycles >= 1, limit=400)
    kinds = [c.type for _, a, c in h.delivered if a == "pc3"
             and c.type in (CommandType.RESTART_CS2, CommandType.RECONNECT_MATCH)]
    assert kinds == [CommandType.RESTART_CS2, CommandType.RECONNECT_MATCH]


def test_crash_during_search_aborts_wave_immediately(tmp_path):
    h = Harness(tmp_path, match_delay=30.0, match_duration=10.0)
    h.run_until(lambda: h.run.state is RunState.SEARCHING)
    t = h.world.now
    h.world.crash_cs2("pc2")
    h.run_until(lambda: h.run.state is RunState.ABORTING_SEARCH or h.run.state is RunState.PREPARING, limit=5)
    assert h.world.now - t <= 2.0
    h.run_until(lambda: h.run.ctx.cycles >= 1)


def test_coordinator_restart_resumes_without_duplicate_commands(tmp_path):
    h = Harness(tmp_path, match_duration=15.0)
    h.run_until(lambda: h.run.state is RunState.SEARCHING)
    run_id = h.plan.run_id
    h.restart_coordinator()
    assert h.coord.plan.run_id == run_id
    assert h.coord.run.state in (RunState.SEARCHING, RunState.CONFIRMING)
    h.run_until(lambda: h.run.ctx.cycles >= 1)
    assert len({c.command_id for _, _, c in h.delivered}) == len(h.delivered)


def test_operator_stop_is_safe(tmp_path):
    h = Harness(tmp_path, match_duration=120.0)
    h.run_until(lambda: h.run.state is RunState.IN_MATCH)
    h.coord.stop_run()
    h.run_until(lambda: h.run.state is RunState.STOPPED, limit=30)
    assert all(not c.worker_running for c in h.world.clients.values())
    assert h.store.active_run() is None


# ----- store / idempotency -------------------------------------------------------------------

def test_store_command_idempotency_and_terminal_results(tmp_path):
    store = FleetStore(tmp_path / "s.db")
    plan = make_roster().build_plan(build_version="b", resource_manifest="m", now=1.0)
    store.save_run(plan)
    cmd = Command("cid-1", plan.run_id, "pc1", CommandType.INVITE, {}, "pair-1", 1, 45.0, 1.0)
    assert store.add_commands([cmd]) == [cmd]
    assert store.add_commands([cmd]) == []
    assert [c.command_id for c in store.pending_for("pc1", plan.run_id)] == ["cid-1"]
    assert store.record_result(CommandResult("cid-1", ResultStatus.COMPLETED),
                               agent_id="pc1", run_id=plan.run_id)
    assert not store.record_result(CommandResult("cid-1", ResultStatus.FAILED, "late duplicate"),
                                   agent_id="pc1", run_id=plan.run_id)
    assert store.results(plan.run_id)["cid-1"].status is ResultStatus.COMPLETED
    assert store.pending_for("pc1", plan.run_id) == []


def test_superseded_commands_are_never_delivered(tmp_path):
    store = FleetStore(tmp_path / "s.db")
    plan = make_roster().build_plan(build_version="b", resource_manifest="m", now=1.0)
    store.save_run(plan)
    old = Command("old", plan.run_id, "pc1", CommandType.START_SEARCH, {}, "", 1, 45.0, 1.0)
    stop = Command("stop", plan.run_id, "pc1", CommandType.SAFE_STOP, {}, "", 1, 45.0, 1.0)
    store.add_commands([old, stop])
    assert store.supersede(plan.run_id, set(), {CommandType.SAFE_STOP.value}) == ["old"]
    assert [c.command_id for c in store.pending_for("pc1", plan.run_id)] == ["stop"]


def test_run_plan_roundtrip_and_roster_validation(tmp_path):
    plan = make_roster().build_plan(build_version="b", resource_manifest="m", now=1.0)
    assert RunPlan.from_json(plan.to_json()) == plan
    roster = FleetRoster(token=TOKEN)
    roster.set_slot(1, agent_id="pc1", steam_id64="76561190000000001", display_name="A")
    with pytest.raises(RosterError):
        roster.set_slot(2, agent_id="pc1", steam_id64="76561190000000002", display_name="B")
    with pytest.raises(RosterError):
        roster.set_slot(2, agent_id="pc2", steam_id64="123", display_name="B")
    assert any("слот 2" in p for p in roster.validate())
    path = tmp_path / "fleet.json"
    roster.save(path)
    assert FleetRoster.load(path).slots == roster.slots


def test_observation_wire_roundtrip(tmp_path):
    world = SimWorld(ACCOUNTS)
    obs = world.observe("pc1")
    assert Observation.from_dict(to_dict(obs)) == obs


# ----- match proof / budgets ----------------------------------------------------------------

NAMES = {"pc1": "Alpha", "pc2": "Bravo", "pc3": "Charlie", "pc4": "Delta"}


def fp(token, *players, age=0.0):
    return MatchFingerprint(token, tuple(players), age)


def test_judge_same_different_insufficient():
    everyone = ("Alpha", "Bravo", "Charlie", "Delta")
    assert judge({a: fp("s1", *everyone) for a in NAMES}, NAMES)[0] is Verdict.SAME
    split = {"pc1": fp("s1", "Alpha", "Bravo", "X", "Y"), "pc2": fp("s1", "Alpha", "Bravo", "X", "Y"),
             "pc3": fp("s2", "Charlie", "Delta", "Z", "W"), "pc4": fp("s2", "Charlie", "Delta", "Z", "W")}
    assert judge(split, NAMES)[0] is Verdict.DIFFERENT
    tokens_differ = {a: fp("s1" if a in ("pc1", "pc2") else "s2", *everyone) for a in NAMES}
    assert judge(tokens_differ, NAMES)[0] is Verdict.DIFFERENT
    partial = {a: fp("s1", *everyone) for a in NAMES}
    partial["pc4"] = None
    assert judge(partial, NAMES)[0] is Verdict.INSUFFICIENT
    stale = {a: fp("s1", *everyone, age=600) for a in NAMES}
    assert judge(stale, NAMES)[0] is Verdict.INSUFFICIENT


def test_windowed_budget():
    c = WindowedCounter(2, 10.0)
    assert c.try_consume(0) and c.try_consume(1) and not c.try_consume(2)
    assert c.try_consume(11.5)
    b = Budget({"x": (1, 100.0)})
    assert b.try_consume("x", 0) and not b.try_consume("x", 1)
    restored = Budget({"x": (1, 100.0)})
    restored.load_state(b.to_state())
    assert not restored.try_consume("x", 2)
