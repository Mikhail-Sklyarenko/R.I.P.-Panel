"""Subprocess wrapper: node looter_core.js (cwd vendor/looter)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from config.paths import get_app_root


def looter_dir() -> Path:
    return get_app_root() / "vendor" / "looter"


def looter_script_path() -> Path:
    return looter_dir() / "looter_core.js"


DEFAULT_INVENTORY = "730/2"
DEFAULT_TIMEOUT_SEC = 300


@dataclass(frozen=True)
class LooterRunResult:
    exit_code: int
    stdout: str
    stderr: str
    simulated: bool = False


def node_executable() -> str | None:
    return shutil.which("node")


def node_modules_ready() -> bool:
    return (looter_dir() / "node_modules").is_dir()


def is_ready() -> bool:
    return (
        looter_script_path().is_file()
        and node_modules_ready()
        and node_executable() is not None
    )


def _tail(text: str, max_chars: int = 400) -> str:
    text = (text or "").strip().replace("\r\n", "\n")
    if len(text) <= max_chars:
        return text
    return "…" + text[-max_chars:]


def run_looter_core(
    *,
    login: str,
    password: str,
    shared_secret: str,
    identity_secret: str,
    trade_offer_link: str,
    inventory: str = DEFAULT_INVENTORY,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> LooterRunResult:
    """
    Запуск node looter_core.js с cwd=vendor/looter.
    Exit 1 = trade confirmed (FSM contract).
    """
    if os.environ.get("LOOTER_SIM") == "1":
        code = int(os.environ.get("LOOTER_SIM_EXIT", "1"))
        return LooterRunResult(
            exit_code=code,
            stdout="LOOTER_SIM=1",
            stderr="",
            simulated=True,
        )

    script = looter_script_path()
    cwd = looter_dir()
    node = node_executable()
    if node is None:
        raise RuntimeError("node not found on PATH")
    if not script.is_file():
        raise RuntimeError(f"missing script: {script}")
    if not node_modules_ready():
        raise RuntimeError(
            "vendor/looter/node_modules missing — run npm install in vendor/looter"
        )

    cmd = [
        node,
        script.name,
        login,
        password,
        shared_secret,
        identity_secret,
        trade_offer_link,
        inventory,
    ]
    creationflags = (
        subprocess.CREATE_NO_WINDOW
        if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW")
        else 0
    )
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        creationflags=creationflags,
    )
    return LooterRunResult(
        exit_code=int(proc.returncode),
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )


def detail_from_result(result: LooterRunResult) -> str:
    """Краткий лог для UI/events без секретов."""
    parts = [f"exit={result.exit_code}"]
    if result.simulated:
        parts.append("sim")
    out = _tail(result.stdout)
    err = _tail(result.stderr)
    if out:
        parts.append(out)
    if err:
        parts.append(f"stderr:{err}")
    return " | ".join(parts)
