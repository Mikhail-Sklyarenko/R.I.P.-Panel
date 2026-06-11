"""in_dm soft_peek: 1/2 probes × 3 polls, timeout logging, retry fast-path."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from config.schema import AppConfig
from core.events import EventType
from modules.ui_nav.coords import load_nav_coords
from modules.ui_nav.detectors import InDmWaitResult, ScreenState, wait_for_in_dm
from modules.ui_nav.errors import UiNavTimeoutError


def _soft_in_dm_image_one_probe(coords) -> Image.Image:
    """Only first in_dm probe matches (soft 1/2, not strict)."""
    img = Image.new("RGB", (360, 270), (0, 0, 0))
    probes = coords.probes("in_dm")
    if probes:
        p = probes[0]
        img.putpixel((p.x, p.y), p.rgb)
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
    img = Image.new("RGB", (360, 270), (5, 5, 5))
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


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DM_NAV_SIM", "1")
    return tmp_path
