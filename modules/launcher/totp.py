"""Steam Guard TOTP via vendor/looter steam-totp (secret file, not argv)."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from config.paths import get_data_dir
from modules.launcher.errors import LauncherError
from modules.looter.runner import looter_dir, node_executable, node_modules_ready

_STEAM_GUARD_CODE_RE = re.compile(r"^[23456789BCDFGHJKMNPQRTVWXY]{5}$")


def _totp_script_path() -> Path:
    return looter_dir() / "totp_once.js"


def _parse_totp_stdout(raw: str) -> str:
    code = (raw or "").strip()
    if _STEAM_GUARD_CODE_RE.match(code):
        return code
    return code


def _valid_steam_guard_code(code: str) -> bool:
    return bool(_STEAM_GUARD_CODE_RE.match(code))


def _run_node_totp(node: str, secret: str) -> tuple[int, str, str]:
    """Run totp_once.js with secret in temp file; delete file after node exits."""
    script = _totp_script_path()
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    fd, secret_path = tempfile.mkstemp(
        prefix=".totp_",
        suffix=".secret",
        dir=str(data_dir),
    )
    os.close(fd)
    path = Path(secret_path)
    try:
        path.write_text(secret, encoding="utf-8", newline="\n")
        proc = subprocess.run(
            [node, str(script.resolve()), str(path.resolve())],
            cwd=str(looter_dir()),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _run_node_totp_inline(node: str, secret: str) -> tuple[int, str, str]:
    """Fallback: inline -e (short secrets only; file path preferred on Windows)."""
    script = (
        "const SteamTotp=require('steam-totp');"
        "const fs=require('fs');"
        "const p=process.argv[1];"
        "const s=fs.readFileSync(p,'utf8').replace(/^\\uFEFF/,'').trim();"
        "process.stdout.write(SteamTotp.getAuthCode(s));"
    )
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    fd, secret_path = tempfile.mkstemp(
        prefix=".totp_",
        suffix=".secret",
        dir=str(data_dir),
    )
    os.close(fd)
    path = Path(secret_path)
    try:
        path.write_text(secret, encoding="utf-8", newline="\n")
        proc = subprocess.run(
            [node, "-e", script, str(path.resolve())],
            cwd=str(looter_dir()),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def generate_steam_guard_code(shared_secret: str) -> str:
    """
    6-digit TOTP from maFile shared_secret.
    Never log the code or secret.
    """
    secret = (shared_secret or "").strip()
    if not secret:
        raise LauncherError("steam guard: empty shared_secret")

    if os.environ.get("STEAM_GUI_LOGIN_SIM") == "1":
        return "23456"

    node = node_executable()
    if node is None:
        raise LauncherError("steam guard TOTP: node not on PATH")
    if not node_modules_ready():
        raise LauncherError(
            "steam guard TOTP: vendor/looter/node_modules missing (npm install)"
        )
    if not _totp_script_path().is_file():
        raise LauncherError("steam guard TOTP: vendor/looter/totp_once.js missing")

    rc, stdout, stderr = _run_node_totp(node, secret)
    if rc != 0:
        rc2, stdout2, stderr2 = _run_node_totp_inline(node, secret)
        if rc2 == 0:
            rc, stdout, stderr = rc2, stdout2, stderr2
        else:
            err = (stderr or stdout or stderr2 or stdout2 or "").strip()[-200:]
            raise LauncherError(
                f"steam guard TOTP failed (exit {rc}) {err}".strip()
            )

    code = _parse_totp_stdout(stdout)
    if not _valid_steam_guard_code(code):
        tail = (stderr or "").strip()[-120:]
        msg = "steam guard TOTP: invalid code from steam-totp"
        if tail:
            msg = f"{msg} ({tail})"
        raise LauncherError(msg)
    return code
