"""DM panel startup autobuy — simple p burst after team select."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from modules.dm_runner.autobuy import run_simple_startup_autobuy


def test_simple_autobuy_waits_then_presses_p() -> None:
    pressed: list[int] = []
    t0 = time.monotonic()
    progress: list[str] = []

    with patch("modules.dm_runner.autobuy.sys.platform", "win32"):
        with patch("modules.dm_runner.autobuy.time.sleep"):
            with patch(
                "modules.dm_runner.autobuy.press_spawn_buy",
                side_effect=lambda _hwnd, **kw: pressed.append(1),
            ):
                ok = run_simple_startup_autobuy(
                    4242,
                    t0,
                    delay_sec=5.0,
                    presses=3,
                    interval_sec=0.2,
                    on_progress=progress.append,
                )

    assert ok is True
    assert len(pressed) == 3
    assert any("autobuy wait" in line for line in progress)
    assert any("autobuy p (1/3)" in line for line in progress)


def test_simple_autobuy_calls_before_press() -> None:
    before = MagicMock()

    with patch("modules.dm_runner.autobuy.sys.platform", "win32"):
        with patch("modules.dm_runner.autobuy.time.sleep"):
            with patch("modules.dm_runner.autobuy.press_spawn_buy"):
                run_simple_startup_autobuy(
                    1,
                    time.monotonic(),
                    delay_sec=0.0,
                    presses=1,
                    before_press=before,
                )

    before.assert_called_once()
