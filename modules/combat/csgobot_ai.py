"""csgobot через subprocess (GPL изолирован в vendor/csgobot)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Protocol

from config.paths import get_app_root, get_logs_dir
from core.events import EventType

_STDERR_READ_LIMIT = 8192
_STDERR_TAIL_EMIT = 200
_PROCESS: subprocess.Popen[Any] | None = None


class _Emit(Protocol):
    def __call__(
        self,
        event: EventType,
        detail: str = "",
        *,
        drop_log: bool = False,
    ) -> None: ...


def _csgobot_dir() -> Path:
    return get_app_root() / "vendor" / "csgobot"


def _run_py() -> Path:
    return _csgobot_dir() / "run.py"


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


def _min_runtime_sec() -> int:
    raw = os.environ.get("CSGOBOT_MIN_RUNTIME_SEC", "30")
    try:
        return max(0, int(raw))
    except ValueError:
        return 30


def _session_id(ctx: dict[str, Any]) -> str:
    return str(ctx.get("session_id") or "csgobot")


def _stderr_log_path(session_id: str) -> Path:
    return get_logs_dir() / f"csgobot_{session_id}.stderr.txt"


def _read_process_stderr(proc: subprocess.Popen[Any]) -> str:
    if proc.stderr is None:
        return ""
    try:
        raw = proc.stderr.read(_STDERR_READ_LIMIT)
    except Exception:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw or ""


def _save_stderr(stderr: str, session_id: str) -> Path | None:
    if not stderr.strip():
        return None
    path = _stderr_log_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stderr, encoding="utf-8")
    return path


def _stderr_tail(stderr: str, limit: int = _STDERR_TAIL_EMIT) -> str:
    text = stderr.strip()
    if not text:
        return ""
    if len(text) > limit:
        return "..." + text[-limit:]
    return text


def _format_stderr_hint(stderr: str, log_path: Path | None) -> str:
    parts: list[str] = []
    tail = _stderr_tail(stderr)
    if tail:
        parts.append(tail)
    if log_path is not None:
        parts.append(f"log: {log_path}")
    return " — ".join(parts)


def check_obs_virtual_camera() -> tuple[bool, str]:
    """True if OBS Virtual Camera is available to csgobot grabber."""
    if sys.platform != "win32":
        return True, ""
    py = python_executable()
    script = _csgobot_dir() / "tools" / "check_obs_vc.py"
    if py is None or not script.is_file():
        return True, ""
    try:
        result = subprocess.run(
            [str(py), str(script)],
            cwd=str(_csgobot_dir()),
            capture_output=True,
            text=True,
            timeout=15.0,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            ),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if result.returncode == 0:
        return True, ""
    detail = (result.stderr or result.stdout or "").strip()
    return False, detail or "OBS Virtual Camera not found"


def check_csgobot_preflight() -> tuple[bool, list[str]]:
    """
    Quick subprocess check: weights, pygrabber, torch/YOLO imports.
    Returns (critical_ok, warnings). Non-fatal issues (e.g. CPU-only) are warnings.
    """
    if sys.platform != "win32":
        return True, []
    py = python_executable()
    script = _csgobot_dir() / "tools" / "preflight.py"
    if py is None or not script.is_file():
        return True, []

    try:
        result = subprocess.run(
            [str(py), str(script)],
            cwd=str(_csgobot_dir()),
            capture_output=True,
            text=True,
            timeout=45.0,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            ),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, [str(exc)]

    payload = (result.stdout or "").strip()
    if not payload:
        detail = (result.stderr or "").strip() or f"preflight exit {result.returncode}"
        return False, [detail]

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return False, [payload[:200]]

    warnings = [str(w) for w in data.get("warnings", [])]
    errors = [str(e) for e in data.get("errors", [])]
    if errors or not data.get("ok", False):
        return False, errors + warnings
    return True, warnings


def _max_runtime_sec(ctx: dict[str, Any]) -> int:
    config = ctx.get("config")
    if config is not None:
        return int(getattr(config, "max_dm_minutes", 90)) * 60
    return 90 * 60


def _finalize_process(
    proc: subprocess.Popen[Any],
    *,
    started_at: float,
    ctx: dict[str, Any],
    emit: _Emit | None,
) -> bool:
    """
    Read stderr, persist log, classify exit.
    True = normal completion; False = fallback.
    """
    code = proc.returncode
    stderr_text = _read_process_stderr(proc)
    log_path = _save_stderr(stderr_text, _session_id(ctx))
    elapsed = time.monotonic() - started_at
    stderr_hint = _format_stderr_hint(stderr_text, log_path)

    if code != 0:
        detail = f"csgobot: exit {code} → simple"
        if stderr_hint:
            detail = f"{detail} — {stderr_hint}"
        if emit:
            emit(EventType.COMBAT_FALLBACK, detail)
        return False

    min_runtime = _min_runtime_sec()
    if elapsed < min_runtime:
        detail = f"csgobot: early exit ({elapsed:.1f}s) — see csgobot log"
        if stderr_hint:
            detail = f"{detail} — {stderr_hint}"
        if emit:
            emit(EventType.COMBAT_FALLBACK, detail)
        return False

    if emit:
        emit(EventType.FARMING, "csgobot: finished ok")
    return True


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

    obs_ok, obs_detail = check_obs_virtual_camera()
    if not obs_ok:
        if emit:
            emit(
                EventType.COMBAT_FALLBACK,
                f"csgobot: OBS Virtual Camera not found — {obs_detail}",
            )
        return False

    preflight_ok, preflight_msgs = check_csgobot_preflight()
    if not preflight_ok:
        detail = "csgobot: preflight failed — " + "; ".join(preflight_msgs[:3])
        if emit:
            emit(EventType.COMBAT_FALLBACK, detail)
        return False
    for warn in preflight_msgs:
        if emit:
            emit(EventType.FARMING, f"csgobot: preflight warn — {warn}")

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

    started_at = time.monotonic()
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

    proc = _PROCESS
    _PROCESS = None
    return _finalize_process(proc, started_at=started_at, ctx=ctx, emit=emit)


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
