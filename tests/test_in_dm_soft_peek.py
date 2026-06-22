"""in_dm soft_peek: 1/2 probes × 3 polls, timeout logging, retry fast-path."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from config.schema import AppConfig
from core.events import EventType
from modules.ui_nav.coords import load_nav_coords
from modules.ui_nav.detectors import (
    InDmWaitResult,
    ScreenState,
    detect_probe_key,
    detect_state,
    wait_for_in_dm,
)

AI_PC_1280 = Path(__file__).resolve().parent / "fixtures" / "ai_pc" / "1280x720"
from modules.ui_nav.errors import UiNavTimeoutError


def test_armoryfarm_in_dm_hud_fixture_strict_and_soft() -> None:
    coords = load_nav_coords("1280x720")
    img = Image.open(AI_PC_1280 / "in_dm_hud.png").convert("RGB")
    img720 = img.resize((1280, 720), Image.Resampling.LANCZOS)
    assert detect_state(img720, ScreenState.IN_DM, coords) is True
    assert detect_state(img720, ScreenState.IN_DM, coords, min_match=1) is True

    team = Image.open(AI_PC_1280 / "team_select.png").convert("RGB")
    team720 = team.resize((1280, 720), Image.Resampling.LANCZOS)
    assert detect_state(team720, ScreenState.IN_DM, coords) is False
    assert detect_probe_key(team720, coords, "team_select", min_match=2) is True


def _soft_in_dm_image_one_probe(coords) -> Image.Image:
    """Only first in_dm probe matches (soft 1/2, not strict)."""
    img = Image.new("RGB", (360, 270), (100, 100, 100))
    probes = coords.probes("in_dm")
    if probes:
        img.putpixel((probes[0].x, probes[0].y), probes[0].rgb)
    if len(probes) > 1:
        p1 = probes[1]
        img.putpixel((p1.x, p1.y), (100, 100, 100))
    return img


def test_wait_for_in_dm_soft_peek_after_three_polls() -> None:
    coords = load_nav_coords("360x270")
    img = _soft_in_dm_image_one_probe(coords)
    driver = MagicMock()
    driver.capture.return_value = img
    artifacts = MagicMock()
    progress: list[str] = []

    with patch("modules.ui_nav.detectors.time.sleep"):
        result = wait_for_in_dm(
            driver,
            coords,
            artifacts,
            timeout_sec=30.0,
            poll_sec=0.01,
            soft_min_match=1,
            soft_peek_polls=3,
            on_progress=progress.append,
        )

    assert result == InDmWaitResult(strict_ok=False, soft_peek=True, attempts=3)
    artifacts.log_step.assert_any_call(
        "in_dm_soft_peek_ok",
        attempt=3,
        consecutive=3,
    )
    assert any("in_dm soft_peek confirmed after 3 polls" in line for line in progress)


def test_wait_for_in_dm_strict_early() -> None:
    coords = load_nav_coords("360x270")
    img = Image.new("RGB", (360, 270), (0, 0, 0))
    for probe in coords.probes("in_dm"):
        img.putpixel((probe.x, probe.y), probe.rgb)
    driver = MagicMock()
    driver.capture.return_value = img
    artifacts = MagicMock()

    result = wait_for_in_dm(
        driver,
        coords,
        artifacts,
        timeout_sec=5.0,
        poll_sec=0.01,
    )

    assert result == InDmWaitResult(strict_ok=True, attempts=1)
    artifacts.log_step.assert_any_call("in_dm_detect_ok", attempt=1, strict=True)


def test_wait_for_in_dm_timeout_logs_probe_rgb() -> None:
    coords = load_nav_coords("360x270")
    img = Image.new("RGB", (360, 270), (100, 100, 100))
    driver = MagicMock()
    driver.capture.return_value = img
    artifacts = MagicMock()
    progress: list[str] = []

    with patch("modules.ui_nav.detectors.time.sleep"):
        with pytest.raises(UiNavTimeoutError, match="timeout waiting for in_dm"):
            wait_for_in_dm(
                driver,
                coords,
                artifacts,
                timeout_sec=0.05,
                poll_sec=0.01,
                on_progress=progress.append,
            )

    assert any(line.startswith("in_dm timeout:") for line in progress)
    assert any("p0=0" in line for line in progress)
    timeout_calls = [
        c
        for c in artifacts.log_step.call_args_list
        if c.args and c.args[0] == "in_dm_detect_timeout"
    ]
    assert len(timeout_calls) == 1
    assert timeout_calls[0].kwargs["timeout_sec"] == 0.05


def test_wait_for_in_dm_team_select_blocks_soft_peek() -> None:
    """Team-pick screen must not count toward in_dm soft_peek (false early join)."""
    coords = load_nav_coords("1280x720")
    team = Image.open(AI_PC_1280 / "team_select.png").convert("RGB")
    team720 = team.resize((1280, 720), Image.Resampling.LANCZOS)
    driver = MagicMock()
    driver.capture.return_value = team720
    artifacts = MagicMock()

    with patch("modules.ui_nav.detectors.time.sleep"):
        with pytest.raises(UiNavTimeoutError, match="timeout waiting for in_dm"):
            wait_for_in_dm(
                driver,
                coords,
                artifacts,
                timeout_sec=0.2,
                poll_sec=0.01,
                soft_min_match=1,
                soft_peek_polls=3,
            )

    soft_ok = [
        c
        for c in artifacts.log_step.call_args_list
        if c.args and c.args[0] == "in_dm_soft_peek_ok"
    ]
    assert soft_ok == []


def test_dm_retry_skips_map_wait_when_soft_in_dm_on_frame(data_dir, monkeypatch) -> None:
    monkeypatch.setenv("DM_NAV_SIM", "1")
    from modules.dm_runner.navigate import DmNavigator

    coords = load_nav_coords("360x270")
    soft_img = _soft_in_dm_image_one_probe(coords)
    emitted: list[tuple[EventType, str]] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        emitted.append((event, detail))

    nav = DmNavigator(
        config=AppConfig(
            map_load_delay_sec=10,
            game_search_timeout_sec=10,
            search_retries=2,
            in_dm_min_match=1,
        ),
        session_id="retry_soft",
        login="u1",
        emit=emit,
    )
    nav._menu_nav_done = True

    wait_calls = {"n": 0}

    def wait_side_effect(*args, **kwargs):
        wait_calls["n"] += 1
        raise UiNavTimeoutError("timeout waiting for in_dm")

    with patch.object(nav.driver, "capture", return_value=soft_img):
        with patch.object(nav, "_ensure_team_joined"):
            with patch.object(nav, "_run_simple_startup_autobuy"):
                with patch(
                    "modules.dm_runner.navigate.wait_for_in_dm",
                    side_effect=wait_side_effect,
                ):
                    with patch.object(nav, "_prepare_cs2_window"):
                        nav.navigate_to_dm_with_retries()

    assert wait_calls["n"] == 1
    in_dm_events = [(e, d) for e, d in emitted if e == EventType.IN_DM]
    assert len(in_dm_events) == 1
    assert in_dm_events[0][1] == "dm_runner: in_dm (soft_peek)"


def test_dm_retry_fast_path_blocks_while_team_select_visible(data_dir, monkeypatch) -> None:
    monkeypatch.setenv("DM_NAV_SIM", "0")
    monkeypatch.setattr("sys.platform", "win32")
    from modules.dm_runner.navigate import DmNavigator

    coords = load_nav_coords("1280x720")
    team = Image.open(AI_PC_1280 / "team_select.png").convert("RGB")
    team720 = team.resize((1280, 720), Image.Resampling.LANCZOS)

    with patch(
        "modules.dm_runner.navigate.load_nav_coords_for_hwnd",
        return_value=coords,
    ):
        nav = DmNavigator(
            config=AppConfig(
                map_load_delay_sec=10,
                game_search_timeout_sec=10,
                search_retries=2,
                in_dm_min_match=1,
                cs_resolution="1280x720",
            ),
            session_id="team_fast",
            login="u1",
            hwnd=12345,
        )
        with patch.object(nav.driver, "capture", return_value=team720):
            with patch.object(nav, "_ensure_team_joined"):
                assert nav._emit_in_dm_if_already_on_frame() is False


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DM_NAV_SIM", "1")
    return tmp_path
