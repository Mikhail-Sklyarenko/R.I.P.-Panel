"""Team-select coords + probes calibrated from operator screenshots."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from modules.ui_nav.coords import NavCoords, load_nav_coords
from modules.ui_nav.detectors import _probe_match, detect_probe_key

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


def test_team_select_ru_fixture_detects_and_clicks_button_text() -> None:
    img = Image.open(_FIXTURES / "team_select_ru_2026-06.png").convert("RGB")
    coords = _coords_for_image(img)

    assert detect_probe_key(img, coords, "team_select", min_match=2) is True

    pt = coords.click("team_random")
    r, g, b = img.getpixel((pt.x, pt.y))
    assert r > 200 and g > 200 and b > 200, f"team_random should hit button text, got {(r, g, b)}"


def test_team_select_legacy_fixture_still_matches() -> None:
    img = Image.open(_FIXTURES / "team_select.png").convert("RGB")
    coords = _coords_for_image(img)

    assert detect_probe_key(img, coords, "team_select", min_match=2) is True

    pt = coords.click("team_random")
    probe = next(p for p in coords.probes("team_select") if p.x == pt.x and p.y == pt.y)
    assert _probe_match(img, probe) or img.getpixel((pt.x, pt.y))[0] > 180
