"""Scancode key press for CS2 binds."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from modules.ui_nav.game_keys import press_game_bind_no_focus


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows only")
def test_press_o_uses_scancode_not_pydirectinput() -> None:
    calls: list[tuple[int, bool, bool]] = []

    def fake_send(scan: int, *, key_up: bool, extended: bool = False) -> None:
        calls.append((scan, key_up, extended))

    with patch("modules.ui_nav.game_keys._send_scancode", side_effect=fake_send):
        press_game_bind_no_focus("o")

    assert calls == [(0x18, False, False), (0x18, True, False)]
