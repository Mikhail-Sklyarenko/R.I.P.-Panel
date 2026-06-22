"""CS2 main-menu overlay dismiss (Escape)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from modules.ui_nav.cs2_modal_dismiss import dismiss_cs2_modals


@pytest.fixture(autouse=True)
def _win32(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")


def test_dismiss_cs2_modals_sends_escape_burst() -> None:
    hwnd = 4242
    with patch("modules.ui_nav.cs2_modal_dismiss.is_valid_hwnd", return_value=True):
        with patch("modules.ui_nav.actions.press_escape") as esc:
            sent = dismiss_cs2_modals(hwnd, bursts=3, interval_sec=0.0)
    assert sent == 3
    assert esc.call_count == 3


def test_dismiss_cs2_modals_invalid_hwnd() -> None:
    with patch("modules.ui_nav.cs2_modal_dismiss.is_valid_hwnd", return_value=False):
        assert dismiss_cs2_modals(0) == 0


def test_dismiss_cs2_modals_reports_progress() -> None:
    progress: list[str] = []
    with patch("modules.ui_nav.cs2_modal_dismiss.is_valid_hwnd", return_value=True):
        with patch("modules.ui_nav.actions.press_escape"):
            dismiss_cs2_modals(1, bursts=2, interval_sec=0.0, on_progress=progress.append)
    assert any("Esc x2" in line for line in progress)
