"""csgobot через subprocess (GPL изолирован в vendor/csgobot)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, IO, Protocol

from config.paths import get_app_root, get_logs_dir
from core.events import EventType

_STDERR_READ_LIMIT = 8192
_STDERR_TAIL_EMIT = 200
_PROCESS: subprocess.Popen[Any] | None = None
_PROCESS_STDERR_FILE: IO[str] | None = None


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


def _open_stderr_log(session_id: str) -> IO[str]:
    path = _stderr_log_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    return open(path, "w", encoding="utf-8", buffering=1)


def _close_stderr_log_file() -> None:
    global _PROCESS_STDERR_FILE
    if _PROCESS_STDERR_FILE is None:
        return
    try:
        _PROCESS_STDERR_FILE.flush()
        _PROCESS_STDERR_FILE.close()
    except OSError:
        pass
    _PROCESS_STDERR_FILE = None


def _read_stderr_log(session_id: str) -> str:
    _close_stderr_log_file()
    path = _stderr_log_path(session_id)
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) > _STDERR_READ_LIMIT:
        return text[-_STDERR_READ_LIMIT:]
    return text


def _stderr_log_path_if_nonempty(session_id: str) -> Path | None:
    path = _stderr_log_path(session_id)
    if not path.is_file():
        return None
    try:
        if path.stat().st_size <= 0:
            return None
    except OSError:
        return None
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


def check_cuda_torch() -> tuple[bool, dict[str, object]]:
    """
    True if PyTorch CUDA is available in csgobot venv.
    Returns (ok, info dict from check_cuda_torch.py JSON).
    """
    if sys.platform != "win32":
        return True, {"cuda": True}
    py = python_executable()
    script = _csgobot_dir() / "tools" / "check_cuda_torch.py"
    if py is None or not script.is_file():
        return True, {}
    try:
        result = subprocess.run(
            [str(py), str(script)],
            cwd=str(_csgobot_dir()),
            capture_output=True,
            text=True,
            timeout=30.0,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            ),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, {"error": str(exc), "cuda": False}
    payload = (result.stdout or "").strip()
    if not payload:
        detail = (result.stderr or "").strip() or f"check_cuda_torch exit {result.returncode}"
        return False, {"error": detail, "cuda": False}
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return False, {"error": payload[:200], "cuda": False}
    return bool(data.get("cuda")), data


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


def _panel_config(ctx: dict[str, Any]) -> Any | None:
    return ctx.get("config")


def _apply_child_env_from_ctx(ctx: dict[str, Any], child_env: dict[str, str]) -> None:
    """Map panel session context into csgobot subprocess environment."""
    # Deathmatch product default: engage all player classes (c/ch/t/th).
    # Panel can still override via parent env; unset → csgobot run.py default ffa.
    if not child_env.get("CSGOBOT_TARGET_MODE", "").strip():
        child_env["CSGOBOT_TARGET_MODE"] = "ffa"
    config = _panel_config(ctx)
    if config is not None:
        sens = getattr(config, "cs2_sensitivity", None)
        if sens is not None:
            try:
                sens_f = float(sens)
            except (TypeError, ValueError):
                sens_f = 0.0
            if sens_f > 0:
                child_env["CS2_SENSITIVITY"] = str(sens_f)
    x360_override = os.environ.get("CSGOBOT_X360", "").strip()
    if x360_override:
        child_env["CSGOBOT_X360"] = x360_override
    hwnd = ctx.get("hwnd") or ctx.get("cs2_hwnd")
    if hwnd is not None:
        try:
            child_env["CSGOBOT_CS2_HWND"] = str(int(hwnd))
        except (TypeError, ValueError):
            pass


def _aim_env_summary(ctx: dict[str, Any]) -> str:
    config = _panel_config(ctx)
    if config is not None:
        sens = getattr(config, "cs2_sensitivity", None)
        if sens is not None:
            return f"csgobot: x360 from CS2_SENSITIVITY={sens}"
    if os.environ.get("CS2_SENSITIVITY", "").strip():
        return f"csgobot: x360 from CS2_SENSITIVITY={os.environ['CS2_SENSITIVITY']}"
    if os.environ.get("CSGOBOT_X360", "").strip():
        return f"csgobot: x360 from CSGOBOT_X360={os.environ['CSGOBOT_X360']}"
    return "csgobot: x360 from run.py default"


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
    sid = _session_id(ctx)
    stderr_text = _read_stderr_log(sid)
    log_path = _stderr_log_path_if_nonempty(sid)
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


_PROCESS_PRELOADED = False


def _spawn_subprocess(ctx: dict[str, Any]) -> bool:
    """Start csgobot child process if not already running."""
    global _PROCESS, _PROCESS_STDERR_FILE, _PROCESS_PRELOADED

    if _PROCESS is not None and _PROCESS.poll() is None:
        return True

    if _PROCESS is not None:
        stop_ai()

    run_py = _run_py()
    py = python_executable()
    if py is None:
        return False

    cmd = [str(py), str(run_py.name)]
    creationflags = (
        subprocess.CREATE_NO_WINDOW
        if hasattr(subprocess, "CREATE_NO_WINDOW")
        else 0
    )
    child_env = os.environ.copy()
    child_env["CSGOBOT_AUTO_ACTIVATE"] = "1"
    _apply_child_env_from_ctx(ctx, child_env)
    sid = _session_id(ctx)
    try:
        _close_stderr_log_file()
        _PROCESS_STDERR_FILE = _open_stderr_log(sid)
        _PROCESS = subprocess.Popen(
            cmd,
            cwd=str(_csgobot_dir()),
            env=child_env,
            stdout=subprocess.DEVNULL,
            stderr=_PROCESS_STDERR_FILE,
            creationflags=creationflags,
        )
    except OSError:
        _close_stderr_log_file()
        _PROCESS = None
        return False

    _PROCESS_PRELOADED = True
    return True


def preload_ai(ctx: dict[str, Any]) -> bool:
    """Start csgobot during DM map load so YOLO warms up before spawn buy ends."""
    emit: _Emit | None = ctx.get("emit")

    if sys.platform != "win32" or not is_installed():
        return False
    if python_executable() is None:
        return False

    obs_ok, obs_detail = check_obs_virtual_camera()
    if not obs_ok:
        return False

    preflight_ok, _ = check_csgobot_preflight()
    if not preflight_ok:
        return False

    if not _spawn_subprocess(ctx):
        return False

    if emit:
        sid = _session_id(ctx)
        emit(
            EventType.FARMING,
            f"csgobot: preloading during map load (log: {_stderr_log_path(sid)})",
        )
    return True


def start_ai(ctx: dict[str, Any]) -> bool:
    """
    Запуск subprocess; блок до завершения/таймаута.
    True = AI отработал; False = нужен fallback (simple).
    """
    global _PROCESS, _PROCESS_STDERR_FILE, _PROCESS_PRELOADED
    emit: _Emit | None = ctx.get("emit")
    preloaded = _PROCESS is not None and _PROCESS.poll() is None and _PROCESS_PRELOADED

    if sys.platform != "win32":
        return False
    if not is_installed():
        return False
    py = python_executable()
    if py is None:
        return False

    if not preloaded:
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

        config = _panel_config(ctx)
        require_cuda = bool(getattr(config, "csgobot_require_cuda", False)) if config else False
        test_mode = bool(getattr(config, "test_mode", False)) if config else False
        cuda_ok, cuda_info = check_cuda_torch()
        if not cuda_ok and not test_mode:
            hint = str(cuda_info.get("install_hint") or cuda_info.get("error") or "install CUDA torch")
            detail = f"csgobot: PyTorch CPU — expect low FPS; {hint}"
            if require_cuda:
                if emit:
                    emit(EventType.COMBAT_FALLBACK, detail)
                return False
            if emit:
                emit(EventType.FARMING, detail + " (see FARM_PC_CHECKLIST.md)")
        elif cuda_ok and cuda_info.get("device") and emit:
            emit(
                EventType.FARMING,
                f"csgobot: CUDA ok — {cuda_info.get('device')}",
            )

        if not _spawn_subprocess(ctx):
            return False
    else:
        _PROCESS_PRELOADED = False

    sid = _session_id(ctx)
    stderr_path = _stderr_log_path(sid)
    if emit:
        detail = (
            "csgobot: joined preloaded subprocess"
            if preloaded
            else f"csgobot: subprocess started (auto_activate); log: {stderr_path}"
        )
        emit(EventType.COMBAT_AI_STARTED, detail)
        emit(EventType.FARMING, _aim_env_summary(ctx))

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
    global _PROCESS, _PROCESS_PRELOADED
    if _PROCESS is None:
        _close_stderr_log_file()
        return
    if _PROCESS.poll() is None:
        _PROCESS.terminate()
        try:
            _PROCESS.wait(timeout=8.0)
        except subprocess.TimeoutExpired:
            _PROCESS.kill()
            _PROCESS.wait(timeout=3.0)
    _PROCESS = None
    _PROCESS_PRELOADED = False
    _close_stderr_log_file()
