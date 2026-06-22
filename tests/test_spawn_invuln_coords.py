"""Spawn invulnerability panel (НЕУЯЗВИМОСТЬ) color probes."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from modules.ui_nav.coords import NavCoords, load_nav_coords
from modules.ui_nav.detectors import detect_probe_key

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ai_pc" / "1280x720"


def _coords_for_image(img: Image.Image) -> NavCoords:
    coords = load_nav_coords("1280x720")
    if img.width == coords.base_width and img.height == coords.base_height:
        return coords
    return NavCoords(
        base_width=coords.base_width,
        base_height=coords.base_height,
        clicks=coords.clicks,
        detectors=coords.detectors,
        scale_x=img.width / coords.base_width,
        scale_y=img.height / coords.base_height,
        profile=coords.profile,
    )


def test_spawn_invuln_ru_fixture_detects() -> None:
    img = Image.open(_FIXTURES / "spawn_invuln_ru_2026-06.png").convert("RGB")
    coords = _coords_for_image(img)

    assert detect_probe_key(img, coords, "spawn_invuln", min_match=2) is True


def test_spawn_invuln_not_on_in_dm_hud_fixture() -> None:
    img = Image.open(_FIXTURES / "in_dm_hud.png").convert("RGB")
    coords = _coords_for_image(img)

    assert detect_probe_key(img, coords, "spawn_invuln", min_match=2) is False
