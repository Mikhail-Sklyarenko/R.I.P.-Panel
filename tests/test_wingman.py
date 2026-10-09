from dataclasses import replace
import pytest
from config.schema import AppConfig, GameMode
from modules.wingman.engine import Observation, Phase, RoundEngine
from modules.wingman.economy import Item, plan_buy, PurchaseTransaction


def obs(**changes):
    return replace(Observation(1, 10., "match-one", 0, "de_inferno", Phase.LIVE,
                               True, True, "T", 800, False, "carried_self"), **changes)


@pytest.mark.parametrize("team,bomb,objective", [
    ("T", "carried_self", "plant"), ("T", "carried_other", "support_carrier"),
    ("T", "dropped", "recover_bomb"), ("T", "planted", "defend_bomb"),
    ("CT", "planted", "defuse"), ("CT", "carried_other", "defend_site")])
def test_objectives_and_enemy_filter(team, bomb, objective):
    d = RoundEngine().update(obs(team=team, bomb=bomb), now=10)
    assert d.objective == objective
    assert d.combat and d.navigation
    assert d.enemy_team != team


@pytest.mark.parametrize("changes", [
    {"observed_at": 9.}, {"observed_at": 11.}, {"observed_at": float("nan")},
    {"own_player": False}, {"alive": False}, {"connected": False},
    {"map_id": "de_dust2"}, {"team": "unknown"}, {"bomb": "unknown"},
    {"phase": Phase.OVER}, {"phase": Phase.FINISHED}, {"phase": Phase.WARMUP}])
def test_nonplaying_states_release_input(changes):
    d = RoundEngine().update(obs(**changes), now=10)
    assert d.release_inputs and not d.combat and not d.navigation


def test_purchase_once_per_round_and_side_switch():
    e = RoundEngine()
    o = obs(phase=Phase.FREEZE, buy_allowed=True)
    assert e.update(o, now=10).buy_key
    assert not e.update(replace(o, sequence=2, observed_at=10.1), now=10.1).buy_key
    d = e.update(replace(o, sequence=3, observed_at=11, round_number=1, team="CT"), now=11)
    assert d.buy_key and d.enemy_team == "T"


def test_death_cannot_resume_same_round_from_spectator_or_bad_alive_frame():
    e = RoundEngine()
    e.update(obs(alive=False), now=10)
    assert not e.update(obs(sequence=2, observed_at=10.1), now=10.1).combat
    assert e.update(obs(sequence=3, observed_at=11, round_number=1), now=11).combat


def test_finished_match_does_not_restart_from_delayed_live_state():
    e = RoundEngine()
    e.update(obs(phase=Phase.FINISHED), now=10)
    assert not e.update(obs(sequence=2, observed_at=10.1), now=10.1).combat
    assert e.update(obs(sequence=3, observed_at=11, match_id="next"), now=11).combat


def test_duplicate_or_regressed_observations_are_rejected():
    e = RoundEngine()
    e.update(obs(round_number=2), now=10)
    assert e.update(obs(), now=10).release_inputs
    assert e.update(obs(sequence=2, observed_at=10.1, round_number=1), now=10.1).release_inputs


CAT = {i.name: i for i in [Item("rifle", 2000, "primary"), Item("smg", 1000, "primary"),
                           Item("armor", 600, "armor"), Item("kit", 400, "kit", ("CT",))]}


def test_buy_respects_budget_existing_slots_and_side():
    p = plan_buy(money=1800, team="T", owned=(), catalog=CAT,
                 priority=("rifle", "smg", "armor", "kit"))
    assert [i.name for i in p] == ["smg", "armor"]
    assert plan_buy(money=1800, team="T", owned=("primary", "armor"),
                    catalog=CAT, priority=tuple(CAT)) == ()


@pytest.mark.parametrize("money", [None, -1, True, "800", 999999])
def test_uncertain_money_never_buys(money):
    assert not plan_buy(money=money, team="T", owned=(), catalog=CAT, priority=tuple(CAT))


def test_transaction_never_repeats_unconfirmed_purchase():
    t = PurchaseTransaction([CAT["smg"], CAT["armor"]])
    assert t.next_item(now=0, money=1800, owned=(), buy_allowed=True).name == "smg"
    assert t.next_item(now=1, money=1800, owned=(), buy_allowed=True) is None
    assert t.next_item(now=2, money=1800, owned=(), buy_allowed=True) is None
    assert t.failed


def test_transaction_confirms_inventory_and_balance_before_next_purchase():
    t = PurchaseTransaction([CAT["smg"], CAT["armor"]])
    t.next_item(now=0, money=1800, owned=(), buy_allowed=True)
    assert t.next_item(now=.1, money=800, owned=(), buy_allowed=True) is None
    assert t.next_item(now=.2, money=800, owned=("smg",), buy_allowed=True).name == "armor"


def test_closing_buy_period_cancels_basket():
    t = PurchaseTransaction([CAT["smg"]])
    assert t.next_item(now=0, money=1800, owned=(), buy_allowed=False) is None
    assert t.failed


def test_default_and_roundtrip_mode():
    assert AppConfig().game_mode == GameMode.DEATHMATCH
    assert AppConfig.model_validate(AppConfig(game_mode=GameMode.WINGMAN).model_dump()).game_mode == GameMode.WINGMAN


def test_wingman_never_launches_dm_or_steam(tmp_path, monkeypatch):
    from config.loader import save_config
    from core import session_fsm as fsm
    from core.session_state import SessionState
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    save_config(AppConfig(game_mode=GameMode.WINGMAN))
    def forbidden(ctx):
        pytest.fail("Wingman fell through to a DM/launcher hook")
    monkeypatch.setattr(fsm, "_hook_launcher", forbidden)
    monkeypatch.setattr(fsm, "_hook_dm_to_match", forbidden)
    messages = []
    state = fsm.run_session("fixture-account", test_mode=False, on_main=messages.append)
    assert state == SessionState.FAILED
    assert any("Напарники" in m for m in messages)


def test_complete_synthetic_cycle():
    from pathlib import Path
    from tools.replay_wingman import replay
    decisions = replay(Path(__file__).parent / "fixtures/wingman/synthetic_match.jsonl")
    assert len(decisions) == 16
    assert sum(d["buy_key"] is not None for d in decisions) == 3
    assert decisions[3]["objective"] == "plant"
    assert decisions[4]["objective"] == "defend_bomb"
    assert not decisions[8]["combat"] and not decisions[9]["combat"]
    assert decisions[12]["enemy_team"] == "T"
    assert decisions[13]["objective"] == "defuse"
    assert decisions[-1]["state"] == "finished"


def test_side_glitch_cannot_change_round_identity():
    e = RoundEngine()
    e.update(obs(), now=10)
    assert e.update(obs(sequence=2, observed_at=10.1, team="CT"), now=10.1).release_inputs
    assert e.round_key[2] == "T"
