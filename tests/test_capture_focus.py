"""Capture focus and black-frame retry."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from PIL import Image

from modules.ui_nav.capture import (
    capture_client,
    capture_client_with_black_retry,
    is_suspect_black_capture,
)


def test_is_suspect_black_capture() -> None:
    black = Image.new("RGB", (360, 270), (0, 0, 0))
    assert is_suspect_black_capture(black) is True
    img = Image.new("RGB", (360, 270), (0, 0, 0))
    img.putpixel((180, 135), (100, 100, 100))
    assert is_suspect_black_capture(img) is False


def test_capture_uses_focus_window_not_raw_setforeground(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    img = Image.new("RGB", (360, 270), (50, 50, 50))
    mock_win32 = MagicMock()
    mock_win32.GetClientRect.return_value = (0, 0, 360, 270)
    mock_win32.ClientToScreen.return_value = (0, 0)
    mock_win32.GetForegroundWindow.return_value = 123

    with patch("modules.ui_nav.window.is_valid_hwnd", return_value=True):
        with patch("modules.ui_nav.actions.focus_window") as mock_focus:
            with patch.dict("sys.modules", {"win32gui": mock_win32}):
                with patch("PIL.ImageGrab.grab", return_value=img):
                    result = capture_client(123)
    mock_focus.assert_called_once_with(123)
    assert result.size == (360, 270)


def test_black_capture_retries_focus_once(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    black = Image.new("RGB", (360, 270), (0, 0, 0))
    ok = Image.new("RGB", (360, 270), (0, 0, 0))
    ok.putpixel((180, 135), (120, 120, 120))
    artifacts = MagicMock()
    calls = {"n": 0}

    def fake_capture(hwnd, **kwargs):
        calls["n"] += 1
        return black if calls["n"] == 1 else ok

    with patch("modules.ui_nav.capture.capture_client", side_effect=fake_capture):
        result = capture_client_with_black_retry(
            999,
            artifacts=artifacts,
            attempt=3,
        )
    assert calls["n"] == 2
    artifacts.log_step.assert_called_once_with(
        "capture_suspect_black",
        attempt=3,
        detail="retry focus",
    )
    assert result.getpixel((180, 135))[:3] == (120, 120, 120)
