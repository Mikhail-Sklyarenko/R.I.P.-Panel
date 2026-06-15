"""csgobot HUD map auto-detect (PR-M1)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"
if str(_CSGOBOT) not in sys.path:
    sys.path.insert(0, str(_CSGOBOT))

from map.hud_map_detect import (  # noqa: E402
    MapDetectState,
    detect_map_hud,
    match_ready_visible,
    update_map_hysteresis,
)
from map.parse import normalize_map_text, parse_map_script  # noqa: E402
from map.paths import resolve_map_regions_path, resolve_map_templates_dir  # noqa: E402
from map.regions import load_map_regions  # noqa: E402
from map.template_match import load_map_templates  # noqa: E402

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "csgobot_map"


def _load_fixture(name: str) -> np.ndarray:
    path = _FIXTURES / name
    raw = Image.open(path).convert("RGB")
    if raw.size != (1280, 720):
        raw = raw.resize((1280, 720), Image.Resampling.LANCZOS)
    return np.asarray(raw)


def _detect_set():
    regions = load_map_regions(resolve_map_regions_path())
    templates = load_map_templates(resolve_map_templates_dir())
    return regions, templates


def test_parse_map_script_dust2_variants() -> None:
    for text in (
        "Бой насмерть | Dust II",
        "Deathmatch • Free-for-all • Dust 2",
        "dust2",
    ):
        assert parse_map_script(text) == "dust2"


def test_parse_map_script_mirage() -> None:
    assert parse_map_script("Бой насмерть | Mirage") == "mirage"
    assert parse_map_script("... • Mirage") == "mirage"


def test_parse_map_script_unknown_is_none() -> None:
    assert parse_map_script("Бой насмерть | Inferno") is None
    assert parse_map_script("Бой насмерть | Vertigo") is None
    assert parse_map_script("") is None


def test_normalize_map_text_separators() -> None:
    assert normalize_map_text("A | B • C") == "A B C"


def test_match_ready_visible_on_popup() -> None:
    regions, _ = _detect_set()
    img = _load_fixture("mirage_ready.png")
    assert match_ready_visible(img, regions) is True


def test_match_ready_not_visible_ingame() -> None:
    regions, _ = _detect_set()
    img = _load_fixture("dust2_ingame.png")
    assert match_ready_visible(img, regions) is False


def test_detect_mirage_scoreboard() -> None:
    regions, templates = _detect_set()
    img = _load_fixture("mirage_tab.png")
    script, source = detect_map_hud(img, regions, templates, use_ocr_fallback=False)
    assert script == "mirage"
    assert source == "scoreboard"


def test_detect_dust2_scoreboard() -> None:
    regions, templates = _detect_set()
    img = _load_fixture("dust2_tab.png")
    script, source = detect_map_hud(img, regions, templates, use_ocr_fallback=False)
    assert script == "dust2"
    assert source == "scoreboard"


def test_detect_mirage_match_ready() -> None:
    regions, templates = _detect_set()
    img = _load_fixture("mirage_ready.png")
    script, source = detect_map_hud(img, regions, templates, use_ocr_fallback=False)
    assert script == "mirage"
    assert source == "match_ready"


def test_detect_dust2_match_ready() -> None:
    regions, templates = _detect_set()
    img = _load_fixture("dust2_ready.png")
    script, source = detect_map_hud(img, regions, templates, use_ocr_fallback=False)
    assert script == "dust2"
    assert source == "match_ready"


def test_inferno_falls_back_to_none() -> None:
    regions, templates = _detect_set()
    img = _load_fixture("inferno_tab.png")
    script, source = detect_map_hud(img, regions, templates, use_ocr_fallback=False)
    assert script is None
    assert source is None


def test_ingame_dust2_without_tab_is_none() -> None:
    regions, templates = _detect_set()
    img = _load_fixture("dust2_ingame.png")
    script, _ = detect_map_hud(img, regions, templates, use_ocr_fallback=False)
    assert script is None


def test_map_hysteresis_confirms_after_frames() -> None:
    state = MapDetectState.from_script("generic_dm")
    changed, pending = update_map_hysteresis(
        state,
        "mirage",
        confirm_frames=3,
        lock_after_confirm=True,
    )
    assert changed is None
    assert pending == 1

    changed, _ = update_map_hysteresis(
        state,
        "mirage",
        confirm_frames=3,
        lock_after_confirm=True,
    )
    assert changed is None

    changed, pending = update_map_hysteresis(
        state,
        "mirage",
        confirm_frames=3,
        lock_after_confirm=True,
    )
    assert changed == "mirage"
    assert pending == 3
    assert state.locked is True
    assert state.confirmed_script == "mirage"


def test_map_hysteresis_locked_ignores_later_changes() -> None:
    state = MapDetectState.from_script("generic_dm")
    state.confirmed_script = "mirage"
    state.locked = True
    changed, pending = update_map_hysteresis(
        state,
        "dust2",
        confirm_frames=1,
        lock_after_confirm=True,
    )
    assert changed is None
    assert pending == 0
    assert state.confirmed_script == "mirage"
