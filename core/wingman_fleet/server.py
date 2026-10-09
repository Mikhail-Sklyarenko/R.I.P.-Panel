"""LAN HTTP endpoint of the coordinator plus the FSM tick loop.

POST /v1/heartbeat   agent observation + results -> commands, server_time, gameplay lease
GET  /v1/status      panel view (token header)
POST /v1/operator    {"pair_id", "action"} or {"agent_id", "command"} (token header)
"""
from __future__ import annotations

import hmac
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from core.wingman_fleet.coordinator import Coordinator
from core.wingman_fleet.models import CommandType

MAX_BODY = 512 * 1024
TICK_SEC = 0.25


def _header_token_ok(headers: Any, token: str) -> bool:
    supplied = headers.get("X-Fleet-Token", "")
    auth = headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        supplied = auth[7:]
    return bool(supplied) and hmac.compare_digest(supplied, token)


class _Handler(BaseHTTPRequestHandler):
    server_version = "WingmanFleet/1"
    coordinator: Coordinator

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send(self, code: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > MAX_BODY:
            self._send(413 if length > MAX_BODY else 400, {"ok": False, "error": "bad length"})
            return None
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send(400, {"ok": False, "error": "invalid json"})
            return None
        if not isinstance(payload, dict):
            self._send(400, {"ok": False, "error": "object required"})
            return None
        return payload

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/v1/health":
            self._send(200, {"ok": True, "server_time": time.time()})
            return
        if path == "/v1/status":
            if not _header_token_ok(self.headers, self.coordinator.token):
                self._send(403, {"ok": False, "error": "unauthorized"})
                return
            self._send(200, {"ok": True, **self.coordinator.status()})
            return
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/v1/heartbeat":
            payload = self._body()
            if payload is not None:
                code, body = self.coordinator.handle_heartbeat(payload)
                self._send(code, body)
            return
        if path == "/v1/operator":
            if not _header_token_ok(self.headers, self.coordinator.token):
                self._send(403, {"ok": False, "error": "unauthorized"})
                return
            payload = self._body()
            if payload is None:
                return
            try:
                if "pair_id" in payload:
                    self.coordinator.pair_action(str(payload["pair_id"]), str(payload["action"]))
                else:
                    self.coordinator.agent_command(str(payload["agent_id"]), CommandType(payload["command"]))
            except (KeyError, ValueError, RuntimeError) as exc:
                self._send(400, {"ok": False, "error": str(exc)})
                return
            self._send(200, {"ok": True})
            return
        self._send(404, {"ok": False, "error": "not found"})


class FleetServer:
    """Owns the HTTP thread and the tick thread; `stop()` is idempotent."""

    def __init__(self, coordinator: Coordinator, *, host: str = "0.0.0.0", port: int = 8790):
        handler = type("FleetHandler", (_Handler,), {"coordinator": coordinator})
        self.coordinator = coordinator
        self.httpd = ThreadingHTTPServer((host, port), handler)
        self.httpd.daemon_threads = True
        self._stop = threading.Event()
        self._threads = [threading.Thread(target=self.httpd.serve_forever, daemon=True, name="fleet-http"),
                         threading.Thread(target=self._tick_loop, daemon=True, name="fleet-tick")]

    @property
    def port(self) -> int:
        return int(self.httpd.server_address[1])

    def start(self) -> "FleetServer":
        for t in self._threads:
            t.start()
        return self

    def _tick_loop(self) -> None:
        while not self._stop.wait(TICK_SEC):
            try:
                self.coordinator.tick()
            except Exception as exc:  # keep coordinating; the failure is visible in the log
                self.coordinator.log(f"fleet: tick failed: {exc!r}")

    def stop(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        for t in self._threads:
            t.join(timeout=3.0)


def local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
