"""Orchestrator: 2 acc sequential DONE + events.jsonl."""

from __future__ import annotations

import json
import os

import pytest

from config.loader import ensure_config, load_config, save_config
from config.paths import get_events_log_path
from core.orchestrator import Orchestrator
from core.session_state import SessionState
from core.session_fsm import run_session


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FAKE_SESSION_SECONDS", "0.25")
    ensure_config()
    cfg = load_config()
    cfg.cooldown_between_accounts_sec = 0
    save_config(cfg)
    return tmp_path


def test_run_session_fake_reaches_done(data_dir) -> None:
    logs: list[str] = []
    final = run_session(
        "acc_a",
        test_mode=True,
        on_main=logs.append,
        on_drop=lambda _m: None,
    )
    assert final is SessionState.DONE
    assert any("DONE" in line for line in logs)
    assert get_events_log_path().exists()
    lines = get_events_log_path().read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 5
    last = json.loads(lines[-1])
    assert last["type"] == "session_done"
    assert last["login"] == "acc_a"


def test_orchestrator_two_accounts_sequential_done(data_dir) -> None:
    main: list[str] = []
    drop: list[str] = []
    orch = Orchestrator(
        test_mode=True,
        ui_callback=main.append,
        drop_callback=drop.append,
    )
    orch.enqueue(["acc_one", "acc_two"])
    assert orch.wait_until_idle(timeout=30.0)

    done_lines = [m for m in main if "DONE" in m]
    assert len(done_lines) == 2
    assert done_lines[0].startswith("[acc_one]")
    assert done_lines[1].startswith("[acc_two]")

    events_path = get_events_log_path()
    assert events_path.is_file()
    types = [
        json.loads(line)["type"]
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert types.count("session_done") == 2
    assert "drop_picked" in types
    assert "loot_ok" in types

    joined_drop = "\n".join(drop)
    assert "vendor/looter/looter_core.js" in joined_drop


def test_looter_fake_message_in_session(data_dir) -> None:
    drop: list[str] = []
    run_session("solo", test_mode=True, on_drop=drop.append)
    assert any("looter_core.js" in d for d in drop)
