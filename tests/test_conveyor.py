"""B10: headless conveyor, farmed_this_week, 3 acc без UI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config.loader import ensure_config, load_config, save_config
from core.conveyor import build_queue, run_night_conveyor
from modules.vault.store import add_account, list_accounts, list_unfarmed_logins
from tests.test_panel_controller import _seed_three


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FAKE_SESSION_SECONDS", "0.08")
    monkeypatch.setenv("DM_NAV_SIM", "1")
    monkeypatch.setenv("LEVEL_DETECT_SIM", "1")
    monkeypatch.setenv("LEVEL_DETECT_AFTER_SEC", "0.15")
    monkeypatch.setenv("DROP_PICKER_SIM", "1")
    monkeypatch.setenv("DROP_PRICING_OFFLINE", "1")
    monkeypatch.setenv("LOOTER_SIM", "1")
    monkeypatch.setenv("COMBAT_SIMPLE_SECONDS", "2")
    ensure_config()
    cfg = load_config()
    cfg.cooldown_between_accounts_sec = 0
    cfg.test_mode = True
    save_config(cfg)
    return tmp_path


def test_build_queue_unfarmed_only(data_dir) -> None:
    _seed_three(data_dir)
    assert len(build_queue()) == 3
    from modules.vault.store import mark_farmed_this_week

    mark_farmed_this_week("user1")
    assert build_queue() == ["user2", "user3"]


def test_conveyor_three_accounts_night_without_ui(data_dir) -> None:
    _seed_three(data_dir)
    logs: list[str] = []
    ok = run_night_conveyor(max_accounts=3, test_mode=True, on_log=logs.append)
    assert ok is True
    joined = "\n".join(logs)
    assert "conveyor: queue 3" in joined
    assert joined.count("farmed_this_week=true") == 3
    assert list_unfarmed_logins() == []
    rows = list_accounts()
    assert all(r.farmed_this_week for r in rows)


def test_conveyor_skips_already_farmed(data_dir) -> None:
    _seed_three(data_dir)
    from modules.vault.store import mark_farmed_this_week

    mark_farmed_this_week("user1")
    mark_farmed_this_week("user2")
    ok = run_night_conveyor(max_accounts=3, test_mode=True)
    assert ok is True
    assert list_unfarmed_logins() == []
