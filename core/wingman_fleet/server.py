"""LAN HTTP endpoint of the coordinator plus the FSM tick loop.

POST /v1/heartbeat   agent observation + results -> commands, server_time, gameplay lease
GET  /v1/status      panel view (operator token)
POST /v1/operator    {"pair_id", "action"} or {"agent_id", "command"} (operator token)
"""
from __future__ import annotations

import hmac
import json
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from core.wingman_fleet.coordinator import Coordinator
from core.wingman_fleet.models import CommandType

MAX_BODY = 512 * 1024
TICK_SEC = 0.25


def _operator_token_ok(headers: Any, token: str) -> bool:
    """Operator routes accept only the operator secret, never the fleet or agent token."""
    supplied = headers.get("X-Operator-Token", "")
    if not supplied:
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
            if not _operator_token_ok(self.headers, self.coordinator.operator_token):
                self._send(403, {"ok": False, "error": "unauthorized"})
                return
            self._send(200, {"ok": True, **self.coordinator.status()})
            return
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/v1/enroll":
            payload = self._body()
            book = getattr(self.coordinator, "assignments", None)
            if payload is None:
                return
            if book is None:
                self._send(403, {"ok": False, "error": "enrollment unavailable"})
                return
            try:
                agent_id = str(payload["agent_id"])
                token = book.claim_enrollment(agent_id, str(payload["code"]))
            except (KeyError, TypeError, RuntimeError):
                self._send(403, {"ok": False, "error": "enrollment rejected"})
                return
            self._send(200, {
                "ok": True, "agent_token": token,
                "registration_generation": book.registration_generation(agent_id),
            })
            return
        if path == "/v1/heartbeat":
            payload = self._body()
            if payload is not None:
                code, body = self.coordinator.handle_heartbeat(payload)
                self._send(code, body)
            return
        if path == "/v1/operator":
            if not _operator_token_ok(self.headers, self.coordinator.operator_token):
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
        self.tls = False
        self.httpd = ThreadingHTTPServer((host, port), handler)
        self.httpd.daemon_threads = True
        self._stop = threading.Event()
        self._threads = [threading.Thread(target=self.httpd.serve_forever, daemon=True, name="fleet-http"),
                         threading.Thread(target=self._tick_loop, daemon=True, name="fleet-tick")]

    @property
    def port(self) -> int:
        return int(self.httpd.server_address[1])

    def enable_tls(self, certfile: str, keyfile: str) -> None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile, keyfile)
        self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)
        self.tls = True

    def start(self, *, certfile: str = "", keyfile: str = "") -> "FleetServer":
        bound = str(self.httpd.server_address[0])
        if bound not in {"127.0.0.1", "localhost", "::1"} and not (certfile and keyfile):
            self.httpd.server_close()
            raise RuntimeError("cleartext HTTP is refused outside localhost; SECURE_LAN requires TLS")
        if certfile or keyfile:
            if not certfile or not keyfile:
                raise RuntimeError("tls needs both a certificate and a key")
            self.enable_tls(certfile, keyfile)
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
