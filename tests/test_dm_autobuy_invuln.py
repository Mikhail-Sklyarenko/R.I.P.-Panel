"""Invuln-gated autobuy burst."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from modules.dm_runner.autobuy import wait_invuln_and_autobuy
from modules.ui_nav.coords import load_nav_coords


def test_wait_invuln_fires_buy_on_first_panel() -> None:
    coords = load_nav_coords("1280x720")
    driver = MagicMock()
    driver.capture.return_value = object()
    progress: list[str] = []
    presses: list[int] = []

    with patch("modules.dm_runner.autobuy.sys.platform", "win32"):
        with patch(
            "modules.dm_runner.autobuy.detect_probe_key",
            side_effect=[False, True, True, False],
        ):
            with patch("modules.dm_runner.autobuy.time.sleep"):
                with patch(
                    "modules.dm_runner.autobuy.press_spawn_buy",
                    side_effect=lambda *_a, **_k: presses.append(1),
                ):
                    ok = wait_invuln_and_autobuy(
                        99,
                        driver,
                        coords,
                        timeout_sec=5.0,
                        presses=2,
                        interval_sec=0.0,
                        on_progress=progress.append,
                    )

    assert ok is True
    assert len(presses) == 2
    assert any("invuln buy panel visible" in line for line in progress)
    assert any("autobuy o (1/2)" in line for line in progress)
