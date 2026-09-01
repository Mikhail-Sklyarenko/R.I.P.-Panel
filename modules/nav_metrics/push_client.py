"""Push nav metrics to central fleet collector (PR-N9)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any


def push_metric_record(
    record: dict[str, Any],
    *,
    url: str,
    token: str = "",
    timeout_sec: float = 3.0,
) -> tuple[bool, str]:
    """POST one metric record to collector. Returns (ok, detail)."""
    target = url.strip()
    if not target:
        return False, "empty url"
    body = json.dumps(record).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    req = urllib.request.Request(target, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            payload = resp.read().decode("utf-8", errors="replace")
            return True, payload[:200]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        return False, f"HTTP {exc.code}: {detail}"
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return False, str(exc)


def push_metric_record_async(
    record: dict[str, Any],
    *,
    url: str,
    token: str = "",
) -> None:
    """Fire-and-forget push (farm PC must not block on collector)."""

    def _run() -> None:
        push_metric_record(record, url=url, token=token)

    threading.Thread(target=_run, daemon=True, name="nav-metrics-push").start()
