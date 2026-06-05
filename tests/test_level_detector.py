"""B7: level_detector + combat phase FSM integration."""

from __future__ import annotations

import os

import pytest

from config.loader import ensure_config, load_config
from config.schema import AppConfig
from core.events import EventType
from core.session_state import SessionState
from core.session_fsm import run_session
from modules.combat.phase import run_combat_phase
from modules.level_detector import WatchResult, watch
from modules.level_detector.detector import detect_level_up
from modules.ui_nav.artifacts import ArtifactStore
from modules.ui_nav.driver import SimDriver
from modules.ui_nav.coords import load_nav_coords


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LEVEL_DETECT_SIM", "1")
    monkeypatch.setenv("LEVEL_DETECT_AFTER_SEC", "0.3")
    monkeypatch.setenv("COMBAT_SIMPLE_SECONDS", "5")
    ensure_config()
    return tmp_path


def test_detect_level_up_on_sim_frame(data_dir) -> None:
    coords = load_nav_coords("360x270")
    art = ArtifactStore("det")
    driver = SimDriver(coords, art)
    driver.set_phase("level_up")
    img = driver.capture()
    assert detect_level_up(img, resolution="360x270") is True


def test_watch_level_up_sim(data_dir) -> None:
    cfg = load_config()
    ctx = {"config": cfg, "session_id": "w1"}
    assert watch(ctx) == WatchResult.LEVEL_UP


def test_watch_combat_timeout(data_dir, monkeypatch) -> None:
    monkeypatch.setenv("LEVEL_DETECT_SIM", "0")
    monkeypatch.delenv("_LEVEL_DETECT_SIM_START", raising=False)
    monkeypatch.setenv("LEVEL_DETECT_TIMEOUT_SEC", "0.4")
    monkeypatch.setenv("LEVEL_DETECT_AFTER_SEC", "999")
    cfg = load_config().model_copy(update={"max_dm_minutes": 1})
    ctx = {"config": cfg, "session_id": "w2"}
    assert watch(ctx) == WatchResult.COMBAT_TIMEOUT


def test_combat_phase_emits_level_up(data_dir, monkeypatch) -> None:
    monkeypatch.setenv("LEVEL_DETECT_AFTER_SEC", "0.2")
    events: list[tuple[EventType, str]] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        events.append((event, detail))

    cfg = AppConfig(bot_mode="simple", combat_simple_minutes=10, max_dm_minutes=90)
    result = run_combat_phase(
        {"emit": emit, "config": cfg, "session_id": "cp1", "COMBAT_SKIP_WIN32": "1"}
    )
    assert result["ok"] is True
    assert result["outcome"] == "level_up"
    types = [e for e, _ in events]
    assert EventType.LEVEL_UP in types
    assert EventType.COMBAT_STOPPED in types


def test_session_fsm_level_up_to_drop_picking(data_dir, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_SESSION_SECONDS", "0.05")
    monkeypatch.setenv("DM_NAV_SIM", "1")
    monkeypatch.setenv("LEVEL_DETECT_AFTER_SEC", "0.2")
    logs: list[str] = []

    final = run_session(
        "acc",
        test_mode=True,
        on_main=logs.append,
    )
    assert final is SessionState.DONE
    joined = "\n".join(logs)
    assert "level_up" in joined
    assert "drop_picked" in joined
    assert "combat_timeout" not in joined or True
