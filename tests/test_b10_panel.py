"""B10: UI counters, Get LVL, start_selected."""

from __future__ import annotations

import pytest

from config.loader import ensure_config
from modules.vault.store import mark_farmed_this_week
from panel.controller import PanelController
from tests.test_panel_controller import _seed_three


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEAM_LEVEL_SIM", "1")
    ensure_config()
    return tmp_path


def test_farmed_counter(data_dir) -> None:
    _seed_three(data_dir)
    ctrl = PanelController(None, test_mode=True)
    assert ctrl.farmed_count == 0
    mark_farmed_this_week("user1")
    mark_farmed_this_week("user2")
    ctrl.reload_accounts()
    assert ctrl.farmed_count == 2


def test_get_lvl_updates_vault(data_dir, monkeypatch) -> None:
    _seed_three(data_dir)
    ctrl = PanelController(None, test_mode=False)
    monkeypatch.setattr(ctrl, "get_selected_logins", lambda: ["user1"])
    ctrl.get_lvl_selected()
    ctrl.reload_accounts()
    assert ctrl.accounts[0].level >= 1
