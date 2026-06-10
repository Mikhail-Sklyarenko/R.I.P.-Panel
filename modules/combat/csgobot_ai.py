"""csgobot через subprocess (GPL изолирован в vendor/csgobot)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Protocol

from config.paths import get_app_root
from core.events import EventType
from modules.combat.errors import CombatError


def _csgobot_dir() -> Path:
    return get_app_root() / "vendor" / "csgobot"


def _run_py() -> Path:
    return _csgobot_dir() / "run.py"
_PROCESS: subprocess.Popen[Any] | None = None


class _Emit(Protocol):
    def __call__(
        self,
        event: EventType,
        detail: str = "",
        *,
        drop_log: bool = False,
    ) -> None: ...


def csgobot_dir() -> Path:
    return _csgobot_dir()


def is_installed() -> bool:
    return _run_py().is_file()


def python_executable() -> Path | None:
    base = _csgobot_dir()
    if sys.platform == "win32":
        candidate = base / "venv" / "Scripts" / "python.exe"
    else:
        candidate = base / "venv" / "bin" / "python"
    return candidate if candidate.is_file() else None


def _max_runtime_sec(ctx: dict[str, Any]) -> int:
    config = ctx.get("config")
    if config is not None:
        return int(getattr(config, "max_dm_minutes", 90)) * 60
    return 90 * 60


def start_ai(ctx: dict[str, Any]) -> bool:
    """
    Запуск subprocess; блок до завершения/таймаута.
    True = AI отработал; False = нужен fallback (simple).
    """
    global _PROCESS
    emit: _Emit | None = ctx.get("emit")

    if sys.platform != "win32":
        return False
    if not is_installed():
        return False
    py = python_executable()
    if py is None:
        return False

    if _PROCESS is not None and _PROCESS.poll() is None:
        stop_ai()

    run_py = _run_py()
    cmd = [str(py), str(run_py.name)]
    creationflags = (
        subprocess.CREATE_NO_WINDOW
        if hasattr(subprocess, "CREATE_NO_WINDOW")
        else 0
    )
    child_env = os.environ.copy()
    child_env["CSGOBOT_AUTO_ACTIVATE"] = "1"
    try:
        _PROCESS = subprocess.Popen(
            cmd,
            cwd=str(_csgobot_dir()),
            env=child_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
    except OSError:
        _PROCESS = None
        return False

    if emit:
        emit(
            EventType.COMBAT_AI_STARTED,
            "csgobot: subprocess started (auto_activate)",
        )

    timeout = _max_runtime_sec(ctx)
    if os.environ.get("COMBAT_AI_SECONDS"):
        timeout = max(1, int(os.environ["COMBAT_AI_SECONDS"]))

    deadline = time.monotonic() + timeout
    farming_interval = 120.0
    next_farm = time.monotonic() + farming_interval

    while _PROCESS.poll() is None and time.monotonic() < deadline:
        if ctx.get("stop_requested"):
            stop_ai()
            return True
        if emit and time.monotonic() >= next_farm:
            emit(EventType.FARMING, "csgobot: farming")
            next_farm = time.monotonic() + farming_interval
        time.sleep(0.5)

    if _PROCESS.poll() is None:
        stop_ai()
        if emit:
            emit(EventType.COMBAT_FALLBACK, "csgobot: timeout → simple")
        return False

    code = _PROCESS.returncode
    _PROCESS = None
    if code != 0:
        if emit:
            emit(EventType.COMBAT_FALLBACK, f"csgobot: exit {code} → simple")
        return False
    if emit:
        emit(EventType.FARMING, "csgobot: finished ok")
    return True


def stop_ai() -> None:
    global _PROCESS
    if _PROCESS is None:
        return
    if _PROCESS.poll() is None:
        _PROCESS.terminate()
        try:
            _PROCESS.wait(timeout=8.0)
        except subprocess.TimeoutExpired:
            _PROCESS.kill()
            _PROCESS.wait(timeout=3.0)
    _PROCESS = None
