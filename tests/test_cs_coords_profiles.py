"""CS2 ui_nav coords profiles by cs_resolution."""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from modules.ui_nav.coords import (
    load_nav_coords,
    load_nav_coords_for_hwnd,
    resolve_cs_coords_path,
)
from modules.ui_nav.detectors import ScreenState, detect_state
from modules.ui_nav.errors import UiNavError
from modules.drop_picker.slots import load_drop_layout
from modules.drop_picker.errors import DropPickerError


def test_resolve_cs_coords_path_360() -> None:
    path = resolve_cs_coords_path("360x270")
    assert path.name == "coords_360x270.yaml"
    assert path.is_file()


def test_resolve_cs_coords_path_1280() -> None:
    path = resolve_cs_coords_path("1280x720")
    assert path.name == "coords_1280x720.yaml"
    assert path.is_file()


def test_resolve_cs_coords_path_missing_raises() -> None:
    with pytest.raises(UiNavError, match="coords profile missing"):
        resolve_cs_coords_path("9999x8888")


def test_load_nav_coords_1280_scale_one_to_one() -> None:
    coords = load_nav_coords("1280x720")
    assert coords.profile == "1280x720"
    assert coords.scale_x == pytest.approx(1.0)
    assert coords.scale_y == pytest.approx(1.0)
    pt = coords.click("main_menu_play")
    assert pt.x == 736
    assert pt.y == 20


def test_load_nav_coords_360_unchanged() -> None:
    coords = load_nav_coords("360x270")
    assert coords.scale_x == pytest.approx(1.0)
    assert coords.click("main_menu_play") == coords.clicks["main_menu_play"]


def test_load_nav_coords_for_hwnd_warns_on_client_mismatch(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    warnings: list[str] = []

    def fake_client_size(_hwnd: int) -> tuple[int, int]:
        return 375, 308

    monkeypatch.setattr("modules.ui_nav.window.client_size", fake_client_size)
    load_nav_coords_for_hwnd(99, "360x270", on_warn=warnings.append)
    assert any("375x308" in w for w in warnings)


def test_load_drop_layout_1280() -> None:
    layout = load_drop_layout("1280x720")
    assert layout.profile == "1280x720"
    assert len(layout.slots) == 4


def test_load_drop_layout_missing_raises() -> None:
    with pytest.raises(DropPickerError, match="drop slots profile missing"):
        load_drop_layout("640x480")


def test_main_menu_detects_1280x720_synthetic_probes() -> None:
    coords = load_nav_coords("1280x720")
    img = Image.new("RGB", (1280, 720), color=(20, 22, 28))
    draw = ImageDraw.Draw(img)
    for probe in coords.probes("main_menu"):
        draw.rectangle(
            (probe.x - 2, probe.y - 2, probe.x + 2, probe.y + 2),
            fill=probe.rgb,
        )
    assert detect_state(img, ScreenState.MAIN_MENU, coords, min_match=2) is True


def test_main_menu_detects_armoryfarm_fixture() -> None:
    from config.paths import get_app_root

    fixture = (
        get_app_root()
        / "tests"
        / "fixtures"
        / "ai_pc"
        / "1280x720"
        / "main_menu_play_dm.png"
    )
    if not fixture.is_file():
        pytest.skip("armoryfarm fixture missing")
    coords = load_nav_coords("1280x720")
    img = Image.open(fixture).convert("RGB")
    assert img.size == (1280, 720)
    assert detect_state(img, ScreenState.MAIN_MENU, coords, min_match=2) is True
