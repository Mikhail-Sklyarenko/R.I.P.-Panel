"""DM panel startup autobuy — console buy commands."""

from __future__ import annotations

from unittest.mock import patch

from modules.dm_runner.autobuy import run_console_autobuy_burst


def test_console_autobuy_burst() -> None:
    calls: list[int] = []
    progress: list[str] = []

    with patch("modules.dm_runner.autobuy.sys.platform", "win32"):
        with patch("modules.dm_runner.autobuy.time.sleep"):
            with patch(
                "modules.dm_runner.autobuy.run_console_autobuy",
                side_effect=lambda *_a, **_k: calls.append(1) or True,
            ):
                ok = run_console_autobuy_burst(
                    4242,
                    presses=3,
                    interval_sec=0.2,
                    on_progress=progress.append,
                )

    assert ok is True
    assert len(calls) == 3
    assert any("autobuy startup done" in line for line in progress)
