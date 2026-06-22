"""Invuln-gated console autobuy."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from modules.dm_runner.autobuy import wait_spawn_console_autobuy
from modules.ui_nav.coords import load_nav_coords


def test_wait_spawn_console_autobuy_on_invuln() -> None:
    coords = load_nav_coords("1280x720")
    driver = MagicMock()
    driver.capture.return_value = object()
    progress: list[str] = []

    with patch("modules.dm_runner.autobuy.sys.platform", "win32"):
        with patch(
            "modules.dm_runner.autobuy.detect_probe_key",
            side_effect=[False, True, True, True, False],
        ):
            with patch("modules.dm_runner.autobuy.time.sleep"):
                with patch(
                    "modules.dm_runner.autobuy.run_console_autobuy",
                    return_value=True,
                ) as buy:
                    ok = wait_spawn_console_autobuy(
                        99,
                        driver,
                        coords,
                        timeout_sec=5.0,
                        presses=2,
                        interval_sec=0.0,
                        on_progress=progress.append,
                    )

    assert ok is True
    assert buy.call_count == 2
    assert any("invuln panel" in line for line in progress)
