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
    driver.capture.return_value = object()
    clock = iter([0.0, 0.0, 0.5, 1.0, 1.5, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 100.0])

    with patch(
        "modules.dm_runner.team_join.detect_probe_key",
        side_effect=[True, True, False],
    ):
        with patch(
            "modules.dm_runner.team_join.past_team_select_screen",
            side_effect=[False, False, True],
        ):
            with patch("modules.dm_runner.team_join.time.sleep"):
                with patch(
                    "modules.dm_runner.team_join.time.monotonic",
                    side_effect=lambda: next(clock, 100.0),
                ):
                    clicks = wait_team_select_done(
                        driver,
                        coords,
                        timeout_sec=10.0,
                        click_retry_sec=0.0,
                        on_progress=None,
                    )

    assert clicks >= 2
    assert driver.click.call_count >= 2


def test_no_blind_click_after_team_overlay_seen() -> None:
    """After overlay was visible, no LMB when probes miss (in-game)."""
    coords = load_nav_coords("1280x720")
    driver = MagicMock()
    driver.capture.return_value = object()
    clock = iter([0.0, 0.0, 0.5, 1.0, 1.5, 2.5, 3.0, 3.5, 4.0, 100.0])

    with patch(
        "modules.dm_runner.team_join.detect_probe_key",
        side_effect=[True, False, False, False],
    ):
        with patch(
            "modules.dm_runner.team_join.past_team_select_screen",
            side_effect=[False, False, False, True],
        ):
            with patch("modules.dm_runner.team_join.time.sleep"):
                with patch(
                    "modules.dm_runner.team_join.time.monotonic",
                    side_effect=lambda: next(clock, 100.0),
                ):
                    clicks = wait_team_select_done(
                        driver,
                        coords,
                        timeout_sec=10.0,
                        click_retry_sec=0.0,
                    )

    assert clicks == 1
    assert driver.click.call_count == 1


def test_wait_team_select_timeout() -> None:
    coords = load_nav_coords("1280x720")
    driver = MagicMock()

    with patch(
        "modules.dm_runner.team_join.detect_probe_key",
        return_value=True,
    ):
        with patch("modules.dm_runner.team_join.past_team_select_screen", return_value=False):
            with patch("modules.dm_runner.team_join.time.monotonic", side_effect=[0.0, 0.1, 100.0]):
                with patch("modules.dm_runner.team_join.time.sleep"):
                    with pytest.raises(UiNavTimeoutError):
                        wait_team_select_done(driver, coords, timeout_sec=5.0, click_retry_sec=0.0)


def test_wait_team_select_blind_clicks_until_timeout_not_early_exit() -> None:
    coords = load_nav_coords("1280x720")
    driver = MagicMock()
    driver.capture.return_value = object()
    clock = iter([0.0, 0.0, 0.5, 1.0, 1.5, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 100.0])

    with patch(
        "modules.dm_runner.team_join.detect_probe_key",
        return_value=False,
    ):
        with patch("modules.dm_runner.team_join.past_team_select_screen", return_value=False):
            with patch("modules.dm_runner.team_join.time.sleep"):
                with patch(
                    "modules.dm_runner.team_join.time.monotonic",
                    side_effect=lambda: next(clock, 100.0),
                ):
                    with pytest.raises(UiNavTimeoutError):
                        wait_team_select_done(
                            driver,
                            coords,
                            timeout_sec=5.0,
                            click_retry_sec=0.0,
                        )

    assert 1 <= driver.click.call_count <= 3


def test_wait_team_select_exits_on_spawn_hud() -> None:
    coords = load_nav_coords("1280x720")
    driver = MagicMock()
    driver.capture.return_value = object()
    clock = iter([0.0, 0.0, 3.0, 3.5, 4.0, 100.0])

    with patch(
        "modules.dm_runner.team_join.past_team_select_screen",
        side_effect=[False, True],
    ):
        with patch("modules.dm_runner.team_join.detect_probe_key", return_value=False):
            with patch("modules.dm_runner.team_join.time.sleep"):
                with patch(
                    "modules.dm_runner.team_join.time.monotonic",
                    side_effect=lambda: next(clock, 100.0),
                ):
                    clicks = wait_team_select_done(
                        driver,
                        coords,
                        timeout_sec=10.0,
                        click_retry_sec=0.0,
                    )

    assert clicks <= 3
