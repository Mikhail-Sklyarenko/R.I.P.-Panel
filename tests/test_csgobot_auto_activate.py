"""Phase 3: panel subprocess auto-activates csgobot without Caps Lock."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"
if str(_CSGOBOT) not in sys.path:
    sys.path.insert(0, str(_CSGOBOT))

from config import HotkeyConfig  # noqa: E402


def test_hotkey_config_auto_activate_default() -> None:
    cfg = HotkeyConfig()
    assert cfg.auto_activate is False


def test_create_config_reads_auto_activate_env(monkeypatch) -> None:
    monkeypatch.setenv("CSGOBOT_AUTO_ACTIVATE", "1")
    from run import create_config  # noqa: E402

    cfg = create_config()
    assert cfg.hotkeys.auto_activate is True


def test_create_config_manual_run_no_env(monkeypatch) -> None:
    monkeypatch.delenv("CSGOBOT_AUTO_ACTIVATE", raising=False)
    from run import AUTO_ACTIVATE, create_config  # noqa: E402

    if AUTO_ACTIVATE:
        pytest.skip("AUTO_ACTIVATE True in run.py")
    cfg = create_config()
    assert cfg.hotkeys.auto_activate is False


@pytest.mark.skipif(sys.platform != "win32", reason="csgobot panel launch is Windows-only")
def test_start_ai_passes_auto_activate_env(monkeypatch) -> None:
    from modules.combat import csgobot_ai

    monkeypatch.setattr(csgobot_ai, "is_installed", lambda: True)
    monkeypatch.setattr(
        csgobot_ai,
        "python_executable",
        lambda: Path("C:/fake/venv/Scripts/python.exe"),
    )

    proc = MagicMock()
    proc.poll.return_value = 0
    proc.returncode = 0

    with patch("modules.combat.csgobot_ai.subprocess.Popen", return_value=proc) as popen:
        ok = csgobot_ai.start_ai({})

    assert ok is True
    _, kwargs = popen.call_args
    assert kwargs["env"]["CSGOBOT_AUTO_ACTIVATE"] == "1"
