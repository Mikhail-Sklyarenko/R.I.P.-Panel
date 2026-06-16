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
    assert parse_buy_offsets("") == (3.0, 5.0, 7.0, 9.0, 11.0)


def test_scheduler_fires_when_elapsed() -> None:
    pressed: list[str] = []
    t0 = time.monotonic()
    sched = SpawnAutobuyScheduler(spawn_mono=t0, offsets_sec=(0.0, 1.0))

    with patch("modules.dm_runner.autobuy.sys.platform", "win32"):
        with patch(
            "modules.dm_runner.autobuy.press_game_bind",
            side_effect=lambda _hwnd, key: pressed.append(key),
        ):
            sched.tick(1, on_progress=None)
            assert pressed == ["f5", "o"]

            with patch("modules.dm_runner.autobuy.time.monotonic", return_value=t0 + 1.1):
                sched.tick(1, on_progress=None)
            assert pressed == ["f5", "o", "f5", "o"]


def test_startup_autobuy_legacy_helper() -> None:
    pressed: list[str] = []
    progress: list[str] = []

    with patch("modules.dm_runner.autobuy.sys.platform", "win32"):
        with patch("modules.dm_runner.autobuy.time.sleep"):
            with patch(
                "modules.dm_runner.autobuy.press_game_bind",
                side_effect=lambda _hwnd, key: pressed.append(key),
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
