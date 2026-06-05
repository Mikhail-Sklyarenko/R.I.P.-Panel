"""Steam auto-login via Node steam-user (vendor/looter/steam_login.js)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from config.schema import AppConfig
from modules.looter.runner import (
    looter_dir,
    node_executable,
    node_modules_ready,
)
from modules.launcher.errors import LauncherError, LauncherPlatformError
from modules.vault.store import AccountNotFoundError, load_account

_READY_MARKER = "STEAM_AUTH_READY"
_AUTH_PROCESS: subprocess.Popen[str] | None = None
_AUTH_LOCK = threading.Lock()


@dataclass(frozen=True)
class SteamAuthResult:
    ok: bool
    login: str
    detail: str
    simulated: bool = False


def steam_login_script_path() -> Path:
    return looter_dir() / "steam_login.js"


def is_ready() -> bool:
    return (
        steam_login_script_path().is_file()
        and node_modules_ready()
        and node_executable() is not None
    )


def _require_windows() -> None:
    if sys.platform != "win32":
        raise LauncherPlatformError("steam auto-login is Windows-only")


def _validate_secrets(secrets: dict) -> None:
    if not (secrets.get("password") or "").strip():
        raise LauncherError("steam login: empty password in vault")
    if not (secrets.get("shared_secret") or "").strip():
        raise LauncherError(
            "maFile secrets required for steam login (shared_secret missing)"
        )


def stop_steam_auth() -> None:
    """Terminate background steam_login.js (session end / next account)."""
    global _AUTH_PROCESS
    with _AUTH_LOCK:
        proc = _AUTH_PROCESS
        _AUTH_PROCESS = None
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5.0)


def _sim_result(login: str) -> SteamAuthResult:
    return SteamAuthResult(
        ok=True,
        login=login,
        detail="STEAM_AUTH_READY (sim)",
        simulated=True,
    )


def _wait_for_ready(
    proc: subprocess.Popen[str],
    *,
    timeout_sec: int,
    login: str,
) -> SteamAuthResult:
    deadline = time.monotonic() + timeout_sec
    assert proc.stdout is not None
    last_error = ""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            err_tail = ""
            if proc.stderr:
                try:
                    err_tail = (proc.stderr.read() or "")[-400:]
                except Exception:
                    pass
            return SteamAuthResult(
                ok=False,
                login=login,
                detail=f"steam login process exited ({proc.returncode}) {err_tail}".strip(),
            )
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.05)
            continue
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        event = payload.get("event")
        if event == "error":
            msg = str(payload.get("message", "steam login error"))
            stop_steam_auth()
            return SteamAuthResult(ok=False, login=login, detail=f"steam login: {msg}")
        status = payload.get("status") or ""
        if event == "ready" and status == _READY_MARKER:
            return SteamAuthResult(
                ok=True,
                login=login,
                detail="steam login ok",
            )
        if event == "loggedOn":
            continue
        if event == "webSession":
            continue
    return SteamAuthResult(
        ok=False,
        login=login,
        detail=last_error or f"steam login timeout ({timeout_sec}s)",
    )


def login_steam_account(login: str, config: AppConfig) -> SteamAuthResult:
    """
    Log on via steam-user; keeps subprocess alive until stop_steam_auth().
    Secrets from vault only — never log password/TOTP.
    """
    login = login.strip()
    if not login:
        raise LauncherError("steam login: login required")

    if os.environ.get("STEAM_LOGIN_SIM") == "1":
        return _sim_result(login)

    if not config.steam_auto_login:
        return SteamAuthResult(
            ok=True,
            login=login,
            detail="steam_auto_login disabled — manual Steam login expected",
        )

    _require_windows()

    if not is_ready():
        raise LauncherError(
            "steam auto-login: node or vendor/looter/node_modules missing "
            "(run npm install in vendor/looter)"
        )

    try:
        secrets = load_account(login)
    except AccountNotFoundError as exc:
        raise LauncherError(f"account not in vault: {login}") from exc

    _validate_secrets(secrets)

    stop_steam_auth()

    node = node_executable()
    script = steam_login_script_path()
    cmd = [
        node,
        script.name,
        login,
        secrets["password"],
        secrets["shared_secret"],
    ]
    creationflags = (
        subprocess.CREATE_NO_WINDOW
        if hasattr(subprocess, "CREATE_NO_WINDOW")
        else 0
    )
    global _AUTH_PROCESS
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(looter_dir()),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
        )
    except OSError as exc:
        raise LauncherError(f"steam login: failed to start node: {exc}") from exc

    with _AUTH_LOCK:
        _AUTH_PROCESS = proc

    timeout = max(30, int(config.steam_login_timeout_sec))
    result = _wait_for_ready(proc, timeout_sec=timeout, login=login)
    if not result.ok:
        stop_steam_auth()
    return result
