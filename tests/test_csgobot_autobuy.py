"""csgobot DM rifle autobuy pulse."""

from __future__ import annotations

import sys
from pathlib import Path

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"
if str(_CSGOBOT) not in sys.path:
    sys.path.insert(0, str(_CSGOBOT))

from config import AutoBuyConfig  # noqa: E402
from controls.autobuy import (  # noqa: E402
    buy_key_for_team,
    maybe_autobuy_pulse,
    resolve_autobuy_enabled,
    resolve_autobuy_interval,
)


def test_buy_key_for_team() -> None:
    cfg = AutoBuyConfig(ct_key="f9", t_key="f10")
    assert buy_key_for_team("ct", cfg) == "f9"
    assert buy_key_for_team("t", cfg) == "f10"


def test_autobuy_pulse_respects_interval() -> None:
    cfg = AutoBuyConfig(enabled=True, interval_sec=3.0)
    pressed: list[str] = []

    last = maybe_autobuy_pulse(
        config=cfg,
        team="ct",
        activated=True,
        now=10.0,
        last_pulse=0.0,
        press=pressed.append,
    )
    assert last == 10.0
    assert pressed == ["f9"]

    last2 = maybe_autobuy_pulse(
        config=cfg,
        team="ct",
        activated=True,
        now=11.0,
        last_pulse=last,
        press=pressed.append,
    )
    assert last2 == 10.0
    assert len(pressed) == 1


def test_autobuy_skipped_when_inactive_or_unstuck() -> None:
    cfg = AutoBuyConfig(enabled=True, interval_sec=1.0)
    pressed: list[str] = []

    maybe_autobuy_pulse(
        config=cfg,
        team="t",
        activated=False,
        now=5.0,
        last_pulse=0.0,
        press=pressed.append,
    )
    assert pressed == []

    maybe_autobuy_pulse(
        config=cfg,
        team="t",
        activated=True,
        now=5.0,
        last_pulse=0.0,
        press=pressed.append,
        unstuck_running=True,
    )
    assert pressed == []


def test_env_resolvers_autobuy(monkeypatch) -> None:
    monkeypatch.setenv("CSGOBOT_AUTO_BUY", "0")
    monkeypatch.setenv("CSGOBOT_AUTO_BUY_INTERVAL", "5")
    assert resolve_autobuy_enabled(True) is False
    assert resolve_autobuy_interval(3.0) == 5.0


def test_create_config_autobuy_defaults(monkeypatch) -> None:
    monkeypatch.delenv("CSGOBOT_AUTO_BUY", raising=False)
    monkeypatch.delenv("CSGOBOT_AUTO_BUY_INTERVAL", raising=False)
    from run import create_config  # noqa: E402

    cfg = create_config()
    assert cfg.autobuy.enabled is True
    assert cfg.autobuy.interval_sec == 3.0
    assert cfg.autobuy.ct_key == "f9"
    assert cfg.autobuy.t_key == "f10"
