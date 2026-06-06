"""Tests for focus_window AttachThreadInput fallback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_focus_window_fallback_without_attach_thread_input(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    mock_win32api = MagicMock()
    del mock_win32api.AttachThreadInput
    mock_win32gui = MagicMock()
    mock_win32gui.GetForegroundWindow.return_value = 1
    mock_win32process = MagicMock()
    mock_win32process.GetWindowThreadProcessId.side_effect = [(10, 0), (20, 0)]

    with patch("modules.ui_nav.window.is_valid_hwnd", return_value=True):
        with patch.dict(
            "sys.modules",
            {
                "win32api": mock_win32api,
                "win32gui": mock_win32gui,
                "win32process": mock_win32process,
                "win32con": MagicMock(),
            },
        ):
            from modules.ui_nav.actions import focus_window

            focus_window(4242)

    mock_win32gui.SetForegroundWindow.assert_called_once_with(4242)
