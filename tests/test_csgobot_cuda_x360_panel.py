"""Panel integration: CUDA check and CS2_SENSITIVITY env for csgobot."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.events import EventType


def test_start_ai_passes_cs2_sensitivity_env(monkeypatch) -> None:
    from config.schema import AppConfig, BotMode
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
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        csgobot_ai,
        "check_csgobot_preflight",
        lambda: (True, []),
    )
    monkeypatch.setattr(
        csgobot_ai,
        "check_nav_preflight",
        lambda pack_id="dust2_dm": (True, {"pack_version": "1.2.0", "goals": ["mid"]}),
    )
    monkeypatch.setattr(
        csgobot_ai,
        "check_cuda_torch",
        lambda: (True, {"cuda": True, "device": "NVIDIA Test"}),
    )
    monkeypatch.setenv("CSGOBOT_MIN_RUNTIME_SEC", "0")

    clock = [1000.0]

    def monotonic() -> float:
        return clock[0]

    def sleep(dt: float) -> None:
        clock[0] += dt

    monkeypatch.setattr(csgobot_ai.time, "monotonic", monotonic)
    monkeypatch.setattr(csgobot_ai.time, "sleep", sleep)

    proc = MagicMock()
    proc.poll.return_value = 0
    proc.returncode = 0
    proc.stderr = MagicMock()
    proc.stderr.read.return_value = b""

    cfg = AppConfig(cs2_sensitivity=3.0, bot_mode=BotMode.AI)
    emitted: list[tuple[EventType, str]] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        emitted.append((event, detail))

    with patch("modules.combat.csgobot_ai.subprocess.Popen", return_value=proc) as popen:
        ok = csgobot_ai.start_ai({"emit": emit, "config": cfg, "hwnd": 424242})

    assert ok is True
    _, kwargs = popen.call_args
    assert kwargs["env"]["CS2_SENSITIVITY"] == "3.0"
    assert kwargs["env"]["CSGOBOT_CS2_HWND"] == "424242"
    assert any("CS2_SENSITIVITY=3.0" in d for _, d in emitted)


@patch("shutil.which", return_value="/usr/bin/node")
@patch("modules.combat.csgobot_ai.check_cuda_torch", return_value=(False, {"install_hint": "pip cuda"}))
@patch(
    "modules.combat.csgobot_ai.check_nav_preflight",
    return_value=(True, {"pack_version": "1.2.0", "goals": ["mid"]}),
)
@patch("modules.combat.csgobot_ai.check_csgobot_preflight", return_value=(True, []))
@patch("modules.combat.csgobot_ai.check_obs_virtual_camera", return_value=(True, ""))
@patch("modules.combat.csgobot_ai.is_installed", return_value=True)
@patch("modules.combat.csgobot_ai.python_executable", return_value=Path("python.exe"))
def test_startup_warns_cpu_torch(
    _py: object,
    _installed: object,
    _obs: object,
    _preflight: object,
    _nav: object,
    _cuda: object,
    _which: object,
    tmp_path,
    monkeypatch,
) -> None:
    from config.schema import AppConfig
    from core.startup_checks import collect_startup_warnings

    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("sys.platform", "win32")
    cfg = AppConfig(
        steam_path=r"C:\Steam\steam.exe",
        cs2_path=r"C:\CS2\cs2.exe",
        bot_mode="ai",
    )
    warnings = collect_startup_warnings(cfg)
    assert any("PyTorch CPU" in w for w in warnings)


def test_start_ai_require_cuda_blocks(monkeypatch) -> None:
    from config.schema import AppConfig, BotMode
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
        lambda: (False, {"install_hint": "pip cuda"}),
    )

    emitted: list[tuple[EventType, str]] = []

    def emit(event: EventType, detail: str = "", **kwargs) -> None:
        emitted.append((event, detail))

    with patch("modules.combat.csgobot_ai.subprocess.Popen") as popen:
        ok = csgobot_ai.start_ai(
            {
                "emit": emit,
                "config": AppConfig(csgobot_require_cuda=True, bot_mode=BotMode.AI),
            }
        )

    assert ok is False
    popen.assert_not_called()
    assert any(e == EventType.COMBAT_FALLBACK for e, _ in emitted)


def test_x360_from_panel_sensitivity_3() -> None:
    assert round(360.0 / (0.022 * 3.0)) == 5455
