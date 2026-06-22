"""DM panel startup autobuy timing and keys."""

from __future__ import annotations

import time
from unittest.mock import patch

from modules.dm_runner.autobuy import (
    SpawnAutobuyScheduler,
    make_fresh_spawn_autobuy,
    parse_buy_offsets,
    run_startup_autobuy,
)


def test_parse_buy_offsets() -> None:
    assert parse_buy_offsets("3,5,7") == (3.0, 5.0, 7.0)
    assert parse_buy_offsets("") == (0.0, 0.15, 0.35, 0.6, 1.0, 1.5, 2.5, 4.0, 6.0)


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
        with patch(
            "modules.dm_runner.autobuy.press_game_bind",
            side_effect=lambda _hwnd, key, **kw: pressed.append(key),
        ):
            sched.tick(1, on_progress=None)
            assert pressed == ["p", "f5", "o"]

            with patch("modules.dm_runner.autobuy.time.monotonic", return_value=t0 + 1.1):
                sched.tick(1, on_progress=None)
            assert pressed == ["p", "f5", "o", "p", "f5", "o"]


def test_stale_scheduler_not_reused_after_load() -> None:
    """Buy window must re-anchor at in_dm — not reuse load-time exhausted scheduler."""
    pressed: list[str] = []
    stale = SpawnAutobuyScheduler(
        spawn_mono=time.monotonic() - 60.0,
        offsets_sec=(0.0,),
    )
    stale._next_index = 1
    stale.sent = True

    with patch("modules.dm_runner.autobuy.sys.platform", "win32"):
        with patch(
            "modules.dm_runner.autobuy.press_game_bind",
            side_effect=lambda _hwnd, key, **kw: pressed.append(key),
        ):
            fresh = make_fresh_spawn_autobuy((0.0,))
            fresh.finish(1)

    assert pressed == ["p", "f5", "o"]


def test_startup_autobuy_legacy_helper() -> None:
    pressed: list[str] = []
    progress: list[str] = []

    with patch("modules.dm_runner.autobuy.sys.platform", "win32"):
        with patch("modules.dm_runner.autobuy.time.sleep"):
            with patch("modules.ui_nav.actions.focus_window"):
                with patch(
                    "modules.dm_runner.autobuy.press_game_bind",
                    side_effect=lambda _hwnd, key, **kw: pressed.append(key),
                ):
                    ok = run_startup_autobuy(
                        4242,
                        spawn_wait_sec=0.0,
                        buy_delays_sec=(0.0,),
                        buy_keys=("p",),
                        on_progress=progress.append,
                    )

    assert ok is True
    assert pressed == ["p"]
