"""csgobot DM rifle autobuy burst + respawn heuristic."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"
if str(_CSGOBOT) not in sys.path:
    sys.path.insert(0, str(_CSGOBOT))

from config import AutoBuyConfig  # noqa: E402
from controls.autobuy import (  # noqa: E402
    AutoBuyState,
    buy_key_for_team,
    resolve_autobuy_enabled,
    resolve_autobuy_interval,
    resolve_respawn_burst_cooldown,
    resolve_respawn_burst_delays,
    resolve_respawn_patrol_freeze,
    resolve_startup_patrol_freeze,
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
    assert pressed == ["f5", "f5"]
    assert state.patrol_freeze_until == pytest.approx(1.0 + cfg.startup_patrol_freeze_sec)


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


def test_spawn_window_schedules_no_immediate_press_on_death() -> None:
    cfg = AutoBuyConfig(
        enabled=True,
        interval_sec=10.0,
        burst_count=1,
        burst_gap_sec=0.0,
        respawn_burst_delays_sec=(0.4, 0.9, 1.4),
        respawn_patrol_freeze_sec=5.0,
        respawn_burst_cooldown_sec=0.5,
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
    assert pressed == ["f5"]

    update_autobuy(
        state,
        config=cfg,
        team="t",
        in_combat=False,
        activated=True,
        now=2.0,
        press=pressed.append,
    )
    assert pressed == ["f5"]
    assert state.patrol_freeze_until == pytest.approx(7.0)

    update_autobuy(
        state,
        config=cfg,
        team="t",
        in_combat=False,
        activated=True,
        now=2.4,
        press=pressed.append,
    )
    assert pressed == ["f5", "f5"]

    update_autobuy(
        state,
        config=cfg,
        team="t",
        in_combat=False,
        activated=True,
        now=2.95,
        press=pressed.append,
    )
    assert pressed == ["f5", "f5", "f5"]

    update_autobuy(
        state,
        config=cfg,
        team="t",
        in_combat=False,
        activated=True,
        now=3.4,
        press=pressed.append,
    )
    assert pressed == ["f5", "f5", "f5", "f5"]


def test_respawn_stagger_respects_cooldown() -> None:
    cfg = AutoBuyConfig(
        enabled=True,
        interval_sec=10.0,
        burst_count=1,
        burst_gap_sec=0.0,
        respawn_burst_delays_sec=(0.2,),
        respawn_burst_cooldown_sec=0.5,
    )
    pressed: list[str] = []
    state = AutoBuyState()

    update_autobuy(
        state,
        config=cfg,
        team="ct",
        in_combat=True,
        activated=True,
        now=0.0,
        press=pressed.append,
    )
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
        team="ct",
        in_combat=True,
        activated=True,
        now=1.1,
        press=pressed.append,
    )
    update_autobuy(
        state,
        config=cfg,
        team="ct",
        in_combat=False,
        activated=True,
        now=1.2,
        press=pressed.append,
    )
    assert pressed == ["f5", "f5"]

    update_autobuy(
        state,
        config=cfg,
        team="ct",
        in_combat=False,
        activated=True,
        now=1.21,
        press=pressed.append,
    )
    assert pressed == ["f5", "f5"]

    update_autobuy(
        state,
        config=cfg,
        team="ct",
        in_combat=True,
        activated=True,
        now=1.3,
        press=pressed.append,
    )
    update_autobuy(
        state,
        config=cfg,
        team="ct",
        in_combat=False,
        activated=True,
        now=1.4,
        press=pressed.append,
    )
    assert pressed == ["f5", "f5"]

    update_autobuy(
        state,
        config=cfg,
        team="ct",
        in_combat=True,
        activated=True,
        now=1.5,
        press=pressed.append,
    )
    update_autobuy(
        state,
        config=cfg,
        team="ct",
        in_combat=False,
        activated=True,
        now=1.6,
        press=pressed.append,
    )
    update_autobuy(
        state,
        config=cfg,
        team="ct",
        in_combat=False,
        activated=True,
        now=1.81,
        press=pressed.append,
    )
    assert pressed == ["f5", "f5", "f5"]


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
    assert pressed.count("f5") == 4


def test_env_resolvers_autobuy(monkeypatch) -> None:
    monkeypatch.setenv("CSGOBOT_AUTO_BUY", "0")
    monkeypatch.setenv("CSGOBOT_AUTO_BUY_INTERVAL", "2")
    monkeypatch.setenv("CSGOBOT_AUTOBUY_RESPAWN_DELAYS_MS", "100,250")
    monkeypatch.setenv("CSGOBOT_AUTOBUY_RESPAWN_COOLDOWN_MS", "800")
    monkeypatch.setenv("CSGOBOT_AUTOBUY_PATROL_FREEZE_MS", "1500")
    monkeypatch.setenv("CSGOBOT_AUTOBUY_STARTUP_FREEZE_MS", "900")
    assert resolve_autobuy_enabled(True) is False
    assert resolve_autobuy_interval(1.0) == 2.0
    assert resolve_respawn_burst_delays() == (0.1, 0.25)
    assert resolve_respawn_burst_cooldown(0.5) == 0.8
    assert resolve_respawn_patrol_freeze(12.0) == 1.5
    assert resolve_startup_patrol_freeze(2.0) == 0.9


def test_create_config_autobuy_defaults(monkeypatch) -> None:
    monkeypatch.delenv("CSGOBOT_AUTO_BUY", raising=False)
    monkeypatch.delenv("CSGOBOT_AUTO_BUY_INTERVAL", raising=False)
    monkeypatch.delenv("CSGOBOT_AUTOBUY_RESPAWN_DELAYS_MS", raising=False)
    monkeypatch.delenv("CSGOBOT_AUTOBUY_RESPAWN_COOLDOWN_MS", raising=False)
    monkeypatch.delenv("CSGOBOT_AUTOBUY_PATROL_FREEZE_MS", raising=False)
    monkeypatch.delenv("CSGOBOT_AUTOBUY_STARTUP_FREEZE_MS", raising=False)
    from run import create_config  # noqa: E402

    cfg = create_config()
    assert cfg.autobuy.enabled is True
    assert cfg.autobuy.interval_sec == 1.0
    assert cfg.autobuy.buy_key == "f5"
    assert cfg.autobuy.burst_count == 2
    assert cfg.autobuy.respawn_burst_delays_sec[0] == 1.5
    assert cfg.autobuy.respawn_burst_cooldown_sec == 0.5
    assert cfg.autobuy.respawn_patrol_freeze_sec == 12.0
    assert cfg.autobuy.startup_patrol_freeze_sec == 2.0
