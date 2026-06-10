"""Panel controller: vault accounts, thread-safe logs."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from config.loader import ensure_config
from modules.vault.store import add_account
from panel.controller import PanelController


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    ensure_config()
    return tmp_path


def _write_mafile(path: Path, login: str) -> None:
    path.write_text(
        json.dumps(
            {
                "account_name": login,
                "shared_secret": "dGVzdF9zaGFyZWQ=",
                "identity_secret": "dGVzdF9pZGVudGl0eQ==",
            }
        ),
        encoding="utf-8",
    )


def _seed_three(data_dir: Path) -> None:
    for i in range(1, 4):
        login = f"user{i}"
        ma = data_dir / f"{login}.mafile.json"
        _write_mafile(ma, login)
        add_account(login=login, password=f"pass{i}", mafile_path=ma)


def test_load_three_accounts_from_vault(data_dir) -> None:
    _seed_three(data_dir)
    ctrl = PanelController(None, test_mode=False)
    assert len(ctrl.accounts) == 3
    assert ctrl.accounts[0].login == "user1"
    assert ctrl.accounts[0].level == 0
    assert ctrl.accounts[0].xp == 0
    assert ctrl.accounts[0].farmed_this_week is False


def test_test_mode_mock_when_vault_empty(data_dir) -> None:
    ctrl = PanelController(None, test_mode=True)
    assert len(ctrl.accounts) == 3
    assert ctrl.accounts[0].login == "mock_acc_1"


def test_append_log_thread_safe(data_dir) -> None:
    ctrl = PanelController(None, test_mode=True)
    lines: list[str] = []

    class FakeLog:
        def configure(self, **kwargs) -> None:
            pass

        def insert(self, _pos: str, text: str) -> None:
            lines.append(text)

        def see(self, _pos: str) -> None:
            pass

    ctrl.bind_log_widgets(FakeLog(), FakeLog())
    ctrl.append_log("line-a")

    def worker() -> None:
        ctrl.append_log("line-b")

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    ctrl._drain_log_queue()
    assert any("line-a" in x for x in lines)
    assert any("line-b" in x for x in lines)


def test_start_farm_queues_orchestrator(data_dir) -> None:
    _seed_three(data_dir)
    from config.loader import load_config, save_config

    cfg = load_config()
    cfg.test_mode = True
    save_config(cfg)
    ctrl = PanelController(None, test_mode=False)
    buf: list[str] = []

    class FakeLog:
        def configure(self, **kwargs) -> None:
            pass

        def insert(self, _pos: str, text: str) -> None:
            buf.append(text)

        def see(self, _pos: str) -> None:
            pass

    ctrl.bind_log_widgets(FakeLog(), FakeLog())
    ctrl.start_farm()
    ctrl._drain_log_queue()
    joined = "".join(buf)
    assert "orchestrator: queued" in joined
    ctrl.stop_farm()


def test_start_farm_warns_empty_trade_link(data_dir) -> None:
    _seed_three(data_dir)
    from config.loader import load_config, save_config

    cfg = load_config()
    cfg.test_mode = True
    cfg.auto_collect_drop = True
    cfg.trade_offer_link = ""
    save_config(cfg)
    ctrl = PanelController(None, test_mode=False)
    buf: list[str] = []

    class FakeLog:
        def configure(self, **kwargs) -> None:
            pass

        def insert(self, _pos: str, text: str) -> None:
            buf.append(text)

        def see(self, _pos: str) -> None:
            pass

    ctrl.bind_log_widgets(FakeLog(), FakeLog())
    ctrl.start_farm()
    ctrl._drain_log_queue()
    joined = "".join(buf)
    assert "trade_offer_link empty" in joined
    assert "LOOT WILL FAIL" in joined
    ctrl.stop_farm()
