"""Phase 3: panel subprocess auto-activates csgobot without Caps Lock."""

from __future__ import annotations

import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"


@contextmanager
def _csgobot_run_module():
    """Load vendor run.py with isolated config; restore panel imports after."""
    import importlib

    inserted = str(_CSGOBOT)
    saved_config = sys.modules.get("config")
    saved_run = sys.modules.pop("run", None)
    sys.path.insert(0, inserted)
    try:
        sys.modules.pop("config", None)
        yield importlib.import_module("run")
    finally:
        sys.path.remove(inserted)
        sys.modules.pop("config", None)
        if saved_config is not None:
            sys.modules["config"] = saved_config
        if saved_run is not None:
            sys.modules["run"] = saved_run


def test_hotkey_config_auto_activate_default() -> None:
    with _csgobot_run_module() as csgobot_run:
        cfg = csgobot_run.HotkeyConfig()
    assert cfg.auto_activate is False


def test_create_config_reads_auto_activate_env(monkeypatch) -> None:
    monkeypatch.setenv("CSGOBOT_AUTO_ACTIVATE", "1")
    with _csgobot_run_module() as csgobot_run:
        cfg = csgobot_run.create_config()
    assert cfg.hotkeys.auto_activate is True


def test_create_config_manual_run_no_env(monkeypatch) -> None:
    monkeypatch.delenv("CSGOBOT_AUTO_ACTIVATE", raising=False)
    with _csgobot_run_module() as csgobot_run:
        if csgobot_run.AUTO_ACTIVATE:
            pytest.skip("AUTO_ACTIVATE True in run.py")
        cfg = csgobot_run.create_config()
    assert cfg.hotkeys.auto_activate is False


def _patch_start_ai_deps(monkeypatch, csgobot_ai) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(csgobot_ai, "is_installed", lambda: True)
    monkeypatch.setattr(
        csgobot_ai,
        "python_executable",
        lambda: Path("C:/fake/venv/Scripts/python.exe"),
    )
    monkeypatch.setattr(
        csgobot_ai,
        "check_obs_virtual_camera",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        csgobot_ai,
        "check_csgobot_preflight",
        lambda: (True, []),
    )
    monkeypatch.setattr(
        csgobot_ai,
        "check_cuda_torch",
        lambda: (True, {"cuda": True, "device": "GPU"}),
    )


def _fake_clock(monkeypatch, csgobot_ai, start: float = 1000.0) -> list[float]:
    clock = [start]

    def monotonic() -> float:
        return clock[0]

    def sleep(dt: float) -> None:
        clock[0] += dt

    monkeypatch.setattr(csgobot_ai.time, "monotonic", monotonic)
    monkeypatch.setattr(csgobot_ai.time, "sleep", sleep)
    return clock


def test_start_ai_passes_auto_activate_env(monkeypatch) -> None:
    from modules.combat import csgobot_ai

    _patch_start_ai_deps(monkeypatch, csgobot_ai)
    monkeypatch.setenv("CSGOBOT_MIN_RUNTIME_SEC", "0")
    _fake_clock(monkeypatch, csgobot_ai)

    proc = MagicMock()
    proc.poll.return_value = 0
    proc.returncode = 0
    proc.stderr = MagicMock()
    proc.stderr.read.return_value = b""

    with patch("modules.combat.csgobot_ai.subprocess.Popen", return_value=proc) as popen:
        ok = csgobot_ai.start_ai({})

    assert ok is True
    _, kwargs = popen.call_args
    assert kwargs["env"]["CSGOBOT_AUTO_ACTIVATE"] == "1"
    assert kwargs["stderr"] is not None
    assert kwargs["stderr"] is not subprocess.PIPE


def test_start_ai_obs_missing_returns_fallback(monkeypatch) -> None:
    from core.events import EventType
    from modules.combat import csgobot_ai

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(csgobot_ai, "is_installed", lambda: True)
    monkeypatch.setattr(
        csgobot_ai,
        "python_executable",
        lambda: Path("C:/fake/venv/Scripts/python.exe"),
    )
    monkeypatch.setattr(
        csgobot_ai,
        "check_obs_virtual_camera",
        lambda: (False, "OBS Virtual Camera not found"),
    )

    emitted: list[tuple[EventType, str]] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        emitted.append((event, detail))

    with patch("modules.combat.csgobot_ai.subprocess.Popen") as popen:
        ok = csgobot_ai.start_ai({"emit": emit})

    assert ok is False
    popen.assert_not_called()
    assert any(e == EventType.COMBAT_FALLBACK for e, _ in emitted)
    assert any("OBS Virtual Camera" in d for _, d in emitted)


def test_start_ai_early_exit_emits_fallback_not_finished_ok(monkeypatch, tmp_path) -> None:
    from core.events import EventType
    from modules.combat import csgobot_ai

    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    _patch_start_ai_deps(monkeypatch, csgobot_ai)
    _fake_clock(monkeypatch, csgobot_ai)

    proc = MagicMock()
    proc.poll.return_value = 0
    proc.returncode = 0
    proc.stderr = MagicMock()
    proc.stderr.read.return_value = b""

    emitted: list[tuple[EventType, str]] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        emitted.append((event, detail))

    with patch("modules.combat.csgobot_ai.subprocess.Popen", return_value=proc):
        ok = csgobot_ai.start_ai({"emit": emit, "session_id": "early1"})

    assert ok is False
    assert not any(d == "csgobot: finished ok" for _, d in emitted)
    assert any(e == EventType.COMBAT_FALLBACK for e, _ in emitted)
    assert any("early exit" in d for _, d in emitted)


def test_start_ai_stderr_saved_and_in_fallback(monkeypatch, tmp_path) -> None:
    from core.events import EventType
    from modules.combat import csgobot_ai

    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    _patch_start_ai_deps(monkeypatch, csgobot_ai)
    _fake_clock(monkeypatch, csgobot_ai)

    stderr_body = "GrabProcess died unexpectedly\nFailed to initialize grabber: device missing\n"
    proc = MagicMock()
    proc.poll.return_value = 0
    proc.returncode = 0

    emitted: list[tuple[EventType, str]] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        emitted.append((event, detail))

    def popen_side_effect(*args, **kwargs):
        stderr_f = kwargs.get("stderr")
        if stderr_f is not None:
            stderr_f.write(stderr_body)
            stderr_f.flush()
        return proc

    with patch(
        "modules.combat.csgobot_ai.subprocess.Popen",
        side_effect=popen_side_effect,
    ):
        ok = csgobot_ai.start_ai({"emit": emit, "session_id": "stderr1"})

    assert ok is False
    log_path = tmp_path / "logs" / "csgobot_stderr1.stderr.txt"
    assert log_path.is_file()
    assert "GrabProcess died" in log_path.read_text(encoding="utf-8")
    fallback = next(d for e, d in emitted if e == EventType.COMBAT_FALLBACK)
    assert "GrabProcess died" in fallback or "device missing" in fallback
    assert "csgobot_stderr1.stderr.txt" in fallback


def test_start_ai_exit_nonzero_fallback(monkeypatch, tmp_path) -> None:
    from core.events import EventType
    from modules.combat import csgobot_ai

    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CSGOBOT_MIN_RUNTIME_SEC", "0")
    _patch_start_ai_deps(monkeypatch, csgobot_ai)
    _fake_clock(monkeypatch, csgobot_ai)

    proc = MagicMock()
    proc.poll.return_value = 1
    proc.returncode = 1
    proc.stderr = MagicMock()
    proc.stderr.read.return_value = b"fatal error\n"

    emitted: list[tuple[EventType, str]] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        emitted.append((event, detail))

    with patch("modules.combat.csgobot_ai.subprocess.Popen", return_value=proc):
        ok = csgobot_ai.start_ai({"emit": emit, "session_id": "exit1"})

    assert ok is False
    assert not any(d == "csgobot: finished ok" for _, d in emitted)
    fallback = next(d for e, d in emitted if e == EventType.COMBAT_FALLBACK)
    assert "exit 1" in fallback
