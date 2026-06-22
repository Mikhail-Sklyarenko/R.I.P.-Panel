"""DM team-pick loop."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from modules.dm_runner.team_join import wait_team_select_done
from modules.ui_nav.coords import load_nav_coords
from modules.ui_nav.errors import UiNavTimeoutError


def _mock_clock(start: float = 0.0, step: float = 0.4, limit: float = 9.0):
    t = start

    def tick() -> float:
        nonlocal t
        current = t
        t = min(t + step, limit)
        return current

    return tick


def test_wait_team_select_clicks_then_clears() -> None:
    coords = load_nav_coords("1280x720")
    driver = MagicMock()
    driver.capture.return_value = object()
    clock = _mock_clock()
    team_flags = iter([True, True, False, False, False, False, False, False, False, False])

    with patch(
        "modules.dm_runner.team_join.detect_probe_key",
        side_effect=lambda *_a, **_k: next(team_flags, False),
    ):
        with patch(
            "modules.dm_runner.team_join.past_team_select_screen",
            side_effect=[False, False, False, True, True],
        ):
            with patch("modules.dm_runner.team_join.time.sleep"):
                with patch(
                    "modules.dm_runner.team_join.time.monotonic",
                    side_effect=clock,
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


def test_console_buy_fires_once_after_team_visible_click() -> None:
    coords = load_nav_coords("1280x720")
    driver = MagicMock()
    driver.capture.return_value = object()
    clock = _mock_clock()
    buy = MagicMock()
    team_flags = iter([True, True, False, False, False, False, False, False, False, False])
    past_flags = iter([False] * 8 + [True] * 10)

    with patch(
        "modules.dm_runner.team_join.detect_probe_key",
        side_effect=lambda *_a, **_k: next(team_flags, False),
    ):
        with patch(
            "modules.dm_runner.team_join.past_team_select_screen",
            side_effect=lambda *_a, **_k: next(past_flags, True),
        ):
            with patch("modules.dm_runner.team_join.time.sleep"):
                with patch(
                    "modules.dm_runner.team_join.time.monotonic",
                    side_effect=clock,
                ):
                    wait_team_select_done(
                        driver,
                        coords,
                        timeout_sec=10.0,
                        click_retry_sec=0.0,
                        on_team_random_clicked=buy,
                    )

    buy.assert_called_once()


def test_no_blind_click_after_team_overlay_seen() -> None:
    coords = load_nav_coords("1280x720")
    driver = MagicMock()
    driver.capture.return_value = object()
    clock = _mock_clock()
    team_flags = iter([True, False, False, False, False, False, False, False, False, False])
    past_flags = iter([False] * 8 + [True] * 10)

    with patch(
        "modules.dm_runner.team_join.detect_probe_key",
        side_effect=lambda *_a, **_k: next(team_flags, False),
    ):
        with patch(
            "modules.dm_runner.team_join.past_team_select_screen",
            side_effect=lambda *_a, **_k: next(past_flags, True),
        ):
            with patch("modules.dm_runner.team_join.time.sleep"):
                with patch(
                    "modules.dm_runner.team_join.time.monotonic",
                    side_effect=clock,
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
