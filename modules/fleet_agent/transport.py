"""Agent → coordinator transports (HTTP on the LAN, in-process for tests)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Protocol


class TransportError(RuntimeError):
    pass


class Transport(Protocol):
    def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class HttpTransport:
    def __init__(self, base_url: str, *, timeout: float = 1.0):
        self.url = base_url.rstrip("/") + "/v1/heartbeat"
        self.timeout = timeout

    def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.url, data=raw, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except (ValueError, OSError):
                body = {}
            raise TransportError(f"HTTP {exc.code}: {body.get('error', exc.reason)}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise TransportError(str(exc)) from exc


class InProcessTransport:
    """Calls a Coordinator directly; `down=True` simulates a network partition."""

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.down = False

    def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.down:
            raise TransportError("partitioned")
        code, body = self.coordinator.handle_heartbeat(json.loads(json.dumps(payload)))
        if code != 200:
            raise TransportError(f"HTTP {code}: {body.get('error')}")
        return body
