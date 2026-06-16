"""DM panel startup autobuy timing and keys."""

from __future__ import annotations

import time
from unittest.mock import patch

from modules.dm_runner.autobuy import (
    SpawnAutobuyScheduler,
    parse_buy_offsets,
    run_startup_autobuy,
)


def test_parse_buy_offsets() -> None:
    assert parse_buy_offsets("3,5,7") == (3.0, 5.0, 7.0)
    assert parse_buy_offsets("") == (0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0)


def test_hold_buy_window_delegates_to_scheduler() -> None:
    sched = SpawnAutobuyScheduler(spawn_mono=100.0, offsets_sec=(0.0,))
    clock = iter([100.0, 100.0, 100.6])

    with patch("modules.dm_runner.autobuy.sys.platform", "win32"):
        with patch.object(sched, "tick") as tick:
            with patch.object(sched, "finish", return_value=True) as finish:
                with patch(
                    "modules.dm_runner.autobuy.time.monotonic",
                    side_effect=lambda: next(clock, 100.6),
                ):
                    with patch("modules.dm_runner.autobuy.time.sleep"):
                        from modules.dm_runner.autobuy import hold_buy_window

                        out, sent = hold_buy_window(1, sched, window_sec=0.5)

    assert sent is True
    assert out is sched
    assert tick.called
    finish.assert_called_once()


def test_scheduler_fires_when_elapsed() -> None:
    pressed: list[str] = []
    t0 = time.monotonic()
    sched = SpawnAutobuyScheduler(spawn_mono=t0, offsets_sec=(0.0, 1.0))

    with patch("modules.dm_runner.autobuy.sys.platform", "win32"):
        with patch("modules.ui_nav.actions.focus_window"):
            with patch("modules.ui_nav.cs2_console.run_cs2_console_commands") as console:
                console.side_effect = Exception("skip console")
                with patch(
                    "modules.dm_runner.autobuy.press_game_bind",
                    side_effect=lambda _hwnd, key, **kw: pressed.append(key),
                ):
                    sched.tick(1, on_progress=None)
                    assert pressed == ["f5", "o", "p"]

                    with patch("modules.dm_runner.autobuy.time.monotonic", return_value=t0 + 1.1):
                        sched.tick(1, on_progress=None)
                    assert pressed == ["f5", "o", "p", "f5", "o", "p"]


def test_startup_autobuy_legacy_helper() -> None:
    pressed: list[str] = []
    progress: list[str] = []

    with patch("modules.dm_runner.autobuy.sys.platform", "win32"):
        with patch("modules.dm_runner.autobuy.time.sleep"):
            with patch("modules.ui_nav.actions.focus_window"):
                with patch("modules.ui_nav.cs2_console.run_cs2_console_commands") as console:
                    console.side_effect = Exception("skip console")
                    with patch(
                        "modules.dm_runner.autobuy.press_game_bind",
                        side_effect=lambda _hwnd, key, **kw: pressed.append(key),
                    ):
                        ok = run_startup_autobuy(
                            4242,
                            spawn_wait_sec=0.0,
                            buy_delays_sec=(0.0,),
                            buy_keys=("f5",),
                            on_progress=progress.append,
                        )

    assert ok is True
    assert pressed == ["f5"]
