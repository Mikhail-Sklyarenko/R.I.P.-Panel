"""DM team-pick loop."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from modules.dm_runner.team_join import wait_team_select_done
from modules.ui_nav.coords import load_nav_coords
from modules.ui_nav.errors import UiNavTimeoutError


def test_wait_team_select_clicks_then_clears() -> None:
    coords = load_nav_coords("1280x720")
    driver = MagicMock()
    frames = [True, True, False]
    driver.capture.return_value = object()

    with patch(
        "modules.dm_runner.team_join.detect_probe_key",
        side_effect=frames,
    ):
        with patch("modules.dm_runner.team_join.time.sleep"):
            clicks = wait_team_select_done(
                driver,
                coords,
                timeout_sec=10.0,
                click_retry_sec=0.0,
                on_progress=None,
            )

    assert clicks == 2
    assert driver.click.call_count == 2


def test_wait_team_select_timeout() -> None:
    coords = load_nav_coords("1280x720")
    driver = MagicMock()

    with patch(
        "modules.dm_runner.team_join.detect_probe_key",
        return_value=True,
    ):
        with patch("modules.dm_runner.team_join.time.monotonic", side_effect=[0.0, 100.0]):
            with pytest.raises(UiNavTimeoutError):
                wait_team_select_done(driver, coords, timeout_sec=5.0, click_retry_sec=0.0)
