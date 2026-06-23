"""DM panel startup autobuy — single console buy."""

from __future__ import annotations

from unittest.mock import patch

from modules.dm_runner.autobuy import run_console_autobuy


def test_console_autobuy_once() -> None:
    with patch("modules.dm_runner.autobuy.sys.platform", "win32"):
        with patch("modules.ui_nav.cs2_console.run_console_dm_rifle_buy") as buy:
            ok = run_console_autobuy(4242)

    assert ok is True
    buy.assert_called_once_with(4242)
