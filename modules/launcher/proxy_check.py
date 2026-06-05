"""Проверка exit IP перед Steam (solo PC)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from modules.launcher.errors import LauncherError


def fetch_public_ip(timeout: float = 10.0) -> str:
    req = urllib.request.Request(
        "https://api.ipify.org?format=json",
        headers={"User-Agent": "farm-panel-prototype/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise LauncherError(f"proxy_check: cannot resolve public IP: {exc}") from exc
    ip = data.get("ip") if isinstance(data, dict) else None
    if not ip:
        raise LauncherError("proxy_check: empty IP response")
    return str(ip).strip()


def check_proxy(expected_ip: str) -> tuple[bool, str]:
    """
    Вернуть (ok, detail).
    Пустой expected_ip → пропуск проверки (ok).
    """
    expected = (expected_ip or "").strip()
    if not expected:
        return True, "proxy_check: skipped (no proxy_expected_ip)"
    current = fetch_public_ip()
    if current == expected:
        return True, f"proxy_check: ip_ok {current}"
    return False, f"proxy_check: expected {expected}, got {current}"
