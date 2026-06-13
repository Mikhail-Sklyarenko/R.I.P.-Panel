"""csgobot DM rifle autobuy burst + respawn heuristic."""

from __future__ import annotations

import sys
from pathlib import Path

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"
if str(_CSGOBOT) not in sys.path:
    sys.path.insert(0, str(_CSGOBOT))

from config import AutoBuyConfig  # noqa: E402
from controls.autobuy import (  # noqa: E402
    AutoBuyState,
    buy_key_for_team,
    resolve_autobuy_enabled,
    resolve_autobuy_interval,
    update_autobuy,
)


def test_buy_key_uses_team_agnostic_default() -> None:
    cfg = AutoBuyConfig(buy_key="insert", ct_key="f9", t_key="f10")
    assert buy_key_for_team("ct", cfg) == "insert"
    assert buy_key_for_team("t", cfg) == "insert"


def test_startup_burst_fires_once() -> None:
    cfg = AutoBuyConfig(enabled=True, burst_count=2, burst_gap_sec=0.0)
    pressed: list[str] = []
    state = AutoBuyState()

    state = update_autobuy(
        state,
        config=cfg,
        team="ct",
        in_combat=False,
        activated=True,
        now=1.0,
        press=pressed.append,
    )
    assert state.started is True
    assert pressed == ["insert", "insert"]


def test_periodic_burst_respects_interval() -> None:
    cfg = AutoBuyConfig(
        enabled=True,
        interval_sec=1.0,
        burst_count=1,
        burst_gap_sec=0.0,
    )
    pressed: list[str] = []
    state = AutoBuyState()

    update_autobuy(
        state,
        config=cfg,
        team="ct",
        in_combat=False,
        activated=True,
        now=10.0,
        press=pressed.append,
    )
    assert len(pressed) == 1

    state = update_autobuy(
        state,
        config=cfg,
        team="ct",
        in_combat=False,
        activated=True,
        now=10.5,
        press=pressed.append,
    )
    assert len(pressed) == 1

    update_autobuy(
        state,
        config=cfg,
        team="ct",
        in_combat=False,
        activated=True,
        now=11.1,
        press=pressed.append,
    )
    assert len(pressed) == 2


def test_respawn_burst_on_combat_end() -> None:
    cfg = AutoBuyConfig(
        enabled=True,
        interval_sec=10.0,
        burst_count=1,
        burst_gap_sec=0.0,
        respawn_burst_count=3,
        respawn_burst_cooldown_sec=1.0,
    )
    pressed: list[str] = []
    state = AutoBuyState()

    update_autobuy(
        state,
        config=cfg,
        team="t",
        in_combat=True,
        activated=True,
        now=1.0,
        press=pressed.append,
    )
    assert len(pressed) == 1

    update_autobuy(
        state,
        config=cfg,
        team="t",
        in_combat=False,
        activated=True,
        now=2.0,
        press=pressed.append,
    )
    assert len(pressed) == 4


def test_team_change_triggers_burst() -> None:
    cfg = AutoBuyConfig(enabled=True, burst_count=2, burst_gap_sec=0.0)
    pressed: list[str] = []
    state = AutoBuyState()

    update_autobuy(
        state,
        config=cfg,
        team="ct",
        in_combat=False,
        activated=True,
        now=1.0,
        press=pressed.append,
    )
    update_autobuy(
        state,
        config=cfg,
        team="t",
        in_combat=False,
        activated=True,
        now=2.0,
        press=pressed.append,
    )
    assert pressed.count("insert") == 4


def test_env_resolvers_autobuy(monkeypatch) -> None:
    monkeypatch.setenv("CSGOBOT_AUTO_BUY", "0")
    monkeypatch.setenv("CSGOBOT_AUTO_BUY_INTERVAL", "2")
    assert resolve_autobuy_enabled(True) is False
    assert resolve_autobuy_interval(1.0) == 2.0


def test_create_config_autobuy_defaults(monkeypatch) -> None:
    monkeypatch.delenv("CSGOBOT_AUTO_BUY", raising=False)
    monkeypatch.delenv("CSGOBOT_AUTO_BUY_INTERVAL", raising=False)
    from run import create_config  # noqa: E402

    cfg = create_config()
    assert cfg.autobuy.enabled is True
    assert cfg.autobuy.interval_sec == 1.0
    assert cfg.autobuy.buy_key == "insert"
    assert cfg.autobuy.burst_count == 2
