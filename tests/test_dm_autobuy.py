"""DM panel startup autobuy timing and keys."""

from __future__ import annotations

from unittest.mock import patch

from modules.dm_runner.autobuy import run_startup_autobuy


def test_startup_autobuy_waits_then_presses_keys() -> None:
    pressed: list[str] = []
    progress: list[str] = []

    with patch("modules.dm_runner.autobuy.sys.platform", "win32"):
        with patch("modules.dm_runner.autobuy.time.sleep") as sleep:
            with patch(
                "modules.dm_runner.autobuy.press_game_bind",
                side_effect=lambda _hwnd, key: pressed.append(key),
            ):
                ok = run_startup_autobuy(
                    4242,
                    spawn_wait_sec=10.0,
                    buy_delays_sec=(0.0, 1.0),
                    buy_keys=("f5", "o"),
                    on_progress=progress.append,
                )

    assert ok is True
    assert pressed == ["f5", "o", "f5", "o"]
    assert sleep.call_args_list[0].args == (10.0,)
    assert any("autobuy wait 10" in line for line in progress)
