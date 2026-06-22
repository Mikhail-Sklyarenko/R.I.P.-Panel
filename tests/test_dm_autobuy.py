"""DM panel startup autobuy — simple o burst after in_dm spawn HUD."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from modules.dm_runner.autobuy import run_simple_startup_autobuy


def test_simple_autobuy_waits_then_presses_o() -> None:
    pressed: list[int] = []
    progress: list[str] = []

    with patch("modules.dm_runner.autobuy.sys.platform", "win32"):
        with patch("modules.dm_runner.autobuy.time.sleep"):
            with patch(
                "modules.dm_runner.autobuy.press_spawn_buy",
                side_effect=lambda _hwnd, **kw: pressed.append(1),
            ):
                with patch("modules.dm_runner.autobuy._console_buy_fallback", return_value=True):
                    ok = run_simple_startup_autobuy(
                        4242,
                        delay_sec=5.0,
                        presses=3,
                        interval_sec=0.2,
                        on_progress=progress.append,
                    )

    assert ok is True
    assert len(pressed) == 3
    assert any("autobuy wait" in line and "spawn HUD" in line for line in progress)
    assert any("autobuy o (1/3)" in line for line in progress)


def test_simple_autobuy_console_fallback() -> None:
    fallback = MagicMock(return_value=True)

    with patch("modules.dm_runner.autobuy.sys.platform", "win32"):
        with patch("modules.dm_runner.autobuy.time.sleep"):
            with patch("modules.dm_runner.autobuy.press_spawn_buy"):
                with patch("modules.dm_runner.autobuy._console_buy_fallback", fallback):
                    run_simple_startup_autobuy(1, delay_sec=0.0, presses=1)

    fallback.assert_called_once()
