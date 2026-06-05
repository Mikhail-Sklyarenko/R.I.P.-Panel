"""B8: drop_picker fixtures + selection/pricing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config.loader import ensure_config
from config.paths import get_artifacts_dir, get_price_cache_path
from config.schema import AppConfig
from core.events import EventType
from modules.drop_picker import pick_care_package
from modules.drop_picker.detector import is_care_package_screen
from modules.drop_picker.ocr import read_all_slots, render_fixture_slot_image
from modules.drop_picker.pricing import get_price_usd, price_slots
from modules.drop_picker.selection import select_top_slots
from modules.drop_picker.slots import load_drop_layout

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "drop_picker"
NAMES = [
    "AK-47 | Redline (Field-Tested)",
    "Glock-18 | Water Elemental (Minimal Wear)",
    "MP9 | Storm (Factory New)",
    "P250 | Sand Dune (Battle-Scarred)",
]


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DROP_PICKER_SIM", "1")
    monkeypatch.setenv("DROP_PRICING_OFFLINE", "1")
    ensure_config()
    return tmp_path


def test_select_top_two_by_heuristic_price() -> None:
    priced = price_slots([(i + 1, n) for i, n in enumerate(NAMES)])
    top = select_top_slots(priced, count=2)
    assert len(top) == 2
    assert top[0].price_usd >= top[1].price_usd
    assert top[0].market_hash_name.startswith("AK-47")


def test_price_cache_db(data_dir) -> None:
    name = "Test Item | Cache (Factory New)"
    p1, s1 = get_price_usd(name)
    p2, s2 = get_price_usd(name)
    assert get_price_cache_path().is_file()
    assert p1 == p2
    assert s2 == "cache"


def test_care_package_detector_on_fixture_image() -> None:
    layout = load_drop_layout("360x270")
    img = render_fixture_slot_image(layout.slots, NAMES)
    assert is_care_package_screen(img, layout)


def test_pick_sim_saves_artifacts_and_emits(data_dir) -> None:
    events: list[tuple[EventType, str]] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        events.append((event, detail))

    cfg = AppConfig(auto_collect_drop=True)
    result = pick_care_package(
        {
            "emit": emit,
            "config": cfg,
            "session_id": "drop1",
            "fixture_dir": FIXTURE_DIR,
        }
    )
    assert result["ok"] is True
    assert "AK-47" in result["picked"][0]
    assert any(e == EventType.DROP_PICKED for e, _ in events)
    root = get_artifacts_dir("drop1")
    assert (root / "drop_selection.json").is_file()
    sel = json.loads((root / "drop_selection.json").read_text(encoding="utf-8"))
    assert sel["picked"] == [1, 2] or sel["picked"] == [1, 3]


def test_ocr_reads_fixture_names(data_dir) -> None:
    layout = load_drop_layout()
    img = render_fixture_slot_image(layout.slots, NAMES)
    rows = read_all_slots(img, layout.slots, fixture_dir=FIXTURE_DIR)
    assert rows[0][1].startswith("AK-47")
