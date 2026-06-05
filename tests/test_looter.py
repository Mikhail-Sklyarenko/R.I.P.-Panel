"""Looter wrapper: LOOTER_SIM, vault, exit code 1 → loot_ok."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.loader import ensure_config, load_config, save_config
from core.events import EventType
from modules.looter import send_trade
from modules.looter.runner import (
    looter_dir,
    looter_script_path,
    run_looter_core,
)
from modules.vault.store import add_account

FIXTURE_MAFILE = Path(__file__).parent / "fixtures" / "sample_mafile.json"


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    ensure_config()
    return tmp_path


@pytest.fixture
def vault_account(data_dir):
    add_account(
        login="test_user",
        password="loot_pass",
        mafile_path=FIXTURE_MAFILE,
    )


def _ctx(login: str = "test_user", **extra):
    events: list[tuple[EventType, str]] = []

    def emit(event: EventType, detail: str = "", *, drop_log: bool = False) -> None:
        events.append((event, detail))

    base = {
        "login": login,
        "emit": emit,
        "config": load_config(),
        **extra,
    }
    return base, events


def test_looter_sim_exit_1_loot_ok(data_dir, vault_account, monkeypatch) -> None:
    monkeypatch.setenv("LOOTER_SIM", "1")
    monkeypatch.setenv("LOOTER_SIM_EXIT", "1")
    cfg = load_config()
    cfg.trade_offer_link = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=abc"
    save_config(cfg)

    ctx, events = _ctx()
    out = send_trade(ctx)
    assert out["ok"] is True
    assert events[-1][0] is EventType.LOOT_OK
    assert "exit=1" in events[-1][1]
    assert "looter_core.js" in events[-1][1]


def test_looter_sim_exit_minus_1_failed(data_dir, vault_account, monkeypatch) -> None:
    monkeypatch.setenv("LOOTER_SIM", "1")
    monkeypatch.setenv("LOOTER_SIM_EXIT", "-1")
    cfg = load_config()
    cfg.trade_offer_link = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=abc"
    save_config(cfg)

    ctx, events = _ctx()
    out = send_trade(ctx)
    assert out["ok"] is False
    assert events[-1][0] is EventType.LOOT_FAILED


def test_auto_collect_drop_false_skips_node(data_dir, vault_account, monkeypatch) -> None:
    monkeypatch.delenv("LOOTER_SIM", raising=False)
    cfg = load_config()
    cfg.auto_collect_drop = False
    cfg.trade_offer_link = ""
    save_config(cfg)

    ctx, events = _ctx()
    out = send_trade(ctx)
    assert out.get("skipped") is True
    assert events[-1][0] is EventType.LOOT_OK
    assert "auto_collect_drop=false" in events[-1][1]


def test_missing_trade_link_fails(data_dir, vault_account, monkeypatch) -> None:
    monkeypatch.setenv("LOOTER_SIM", "1")
    cfg = load_config()
    cfg.trade_offer_link = ""
    save_config(cfg)

    ctx, events = _ctx()
    out = send_trade(ctx)
    assert out["ok"] is False
    assert events[-1][0] is EventType.LOOT_FAILED


def test_run_looter_core_cwd_is_vendor_looter(
    data_dir, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("LOOTER_SIM", "1")
    result = run_looter_core(
        login="a",
        password="b",
        shared_secret="c",
        identity_secret="d",
        trade_offer_link="https://example.com/trade",
    )
    assert result.exit_code == 1
    assert looter_dir().is_dir()
    assert looter_script_path().is_file()


def test_looter_script_under_vendor_not_parent() -> None:
    script = looter_script_path()
    assert "vendor/looter" in script.as_posix()
    assert script.name == "looter_core.js"
