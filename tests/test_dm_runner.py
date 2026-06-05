"""B5: dm_runner + ui_nav (sim), 5× in_dm, artifacts."""

from __future__ import annotations

import json

import pytest

from config.loader import ensure_config, load_config, save_config
from config.paths import get_artifacts_dir
from config.schema import AppConfig
from core.events import EventType
from modules.dm_runner import run, run_in_dm_cycles
from modules.ui_nav.coords import load_nav_coords
from modules.ui_nav.detectors import ScreenState, detect_state
from modules.ui_nav.driver import SimDriver, create_driver
from modules.ui_nav.artifacts import ArtifactStore


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DM_NAV_SIM", "1")
    ensure_config()
    return tmp_path


def test_coords_load_and_scale() -> None:
    c = load_nav_coords("360x270")
    pt = c.click("main_menu_play")
    assert pt.x == 180
    c2 = load_nav_coords("720x540")
    pt2 = c2.click("main_menu_play")
    assert pt2.x == 360


def test_sim_driver_detect_main_menu(data_dir) -> None:
    coords = load_nav_coords()
    art = ArtifactStore("test_sess")
    driver = create_driver(coords, art)
    assert isinstance(driver, SimDriver)
    driver.set_phase("main_menu")
    img = driver.capture()
    assert detect_state(img, ScreenState.MAIN_MENU, coords)


def test_five_in_dm_cycles_sim(data_dir, monkeypatch) -> None:
    monkeypatch.setenv("DM_NAV_SIM", "1")
    cfg = load_config()
    save_config(
        cfg.model_copy(
            update={
                "map_load_delay_sec": 10,
                "game_search_timeout_sec": 10,
                "search_retries": 1,
            }
        )
    )
    events: list[str] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        events.append(event.value)

    sid = "smoke123"
    ok = run_in_dm_cycles(5, ctx={"login": "u1", "session_id": sid, "emit": emit})
    assert ok == 5
    assert events.count("in_dm") == 5
    root = get_artifacts_dir(sid)
    assert (root / "cycles_result.json").is_file()
    result = json.loads((root / "cycles_result.json").read_text(encoding="utf-8"))
    assert result["ok"] == 5
    assert (root / "steps.jsonl").is_file()


def test_dm_run_emits_events(data_dir) -> None:
    emitted: list[EventType] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        emitted.append(event)

    assert run({"login": "acc", "emit": emit, "session_id": "abc"}) is True
    assert EventType.IN_MENU in emitted
    assert EventType.SEARCHING_DM in emitted
    assert EventType.IN_DM in emitted
