"""HTTP fleet collector for nav metrics (PR-N9)."""

from __future__ import annotations

import json
import socket
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from modules.nav_metrics.store import append_nav_metric

_server: ThreadingHTTPServer | None = None
_thread: threading.Thread | None = None
_token: str = ""
_started_at: str | None = None
_ingest_count: int = 0


class NavFleetCollectorError(RuntimeError):
    pass


def _check_auth(headers: Any, token: str) -> bool:
    if not token:
        return True
    auth = headers.get("Authorization", "")
    if auth == f"Bearer {token}":
        return True
    return headers.get("X-Fleet-Token", "") == token


def ingest_remote_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept push body and persist as nav metric row."""
    global _ingest_count
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        metrics = payload
    login = str(payload.get("login") or "")
    session_id = str(payload.get("session_id") or "")
    host = str(payload.get("host") or "")
    append_nav_metric(
        metrics,
        login=login,
        session_id=session_id,
        host=host or None,
    )
    _ingest_count += 1
    return {"ok": True, "ingested": 1}


class _NavCollectorHandler(BaseHTTPRequestHandler):
    server_version = "NavFleetCollector/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, code: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/v1/health":
            self._send_json(
                200,
                {
                    "ok": True,
                    "service": "nav_fleet_collector",
                    "ingest_count": _ingest_count,
                    "started_at": _started_at,
                },
            )
            return
        if path == "/api/v1/fleet/summary":
            from modules.nav_metrics.store import fleet_summary

            self._send_json(200, fleet_summary(hours=24.0, include_inbox=True))
            return
        self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/v1/nav_metrics":
            self._send_json(404, {"ok": False, "error": "not found"})
            return
        if not _check_auth(self.headers, _token):
            self._send_json(401, {"ok": False, "error": "unauthorized"})
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        try:
            raw = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"ok": False, "error": "invalid json"})
            return
        if not isinstance(payload, dict):
            self._send_json(400, {"ok": False, "error": "object required"})
            return
        if "records" in payload and isinstance(payload["records"], list):
            count = 0
            for item in payload["records"]:
                if isinstance(item, dict):
                    ingest_remote_payload(item)
                    count += 1
            self._send_json(200, {"ok": True, "ingested": count})
            return
        result = ingest_remote_payload(payload)
        self._send_json(200, result)


def collector_status() -> dict[str, Any]:
    running = _server is not None
    port = _server.server_address[1] if _server else None
    return {
        "running": running,
        "port": port,
        "ingest_count": _ingest_count,
        "started_at": _started_at,
        "token_required": bool(_token),
    }


def start_collector(*, port: int = 8765, token: str = "") -> dict[str, Any]:
    global _server, _thread, _token, _started_at, _ingest_count
    if _server is not None:
        raise NavFleetCollectorError("collector already running")
    _token = token.strip()
    _ingest_count = 0
    _started_at = datetime.now(timezone.utc).isoformat()
    _server = ThreadingHTTPServer(("0.0.0.0", port), _NavCollectorHandler)
    _thread = threading.Thread(target=_server.serve_forever, daemon=True, name="nav-fleet-collector")
    _thread.start()
    host = _local_ip()
    return {
        "running": True,
        "port": port,
        "url": f"http://{host}:{port}/api/v1/nav_metrics",
        "health": f"http://{host}:{port}/api/v1/health",
    }


def stop_collector() -> None:
    global _server, _thread, _started_at
    if _server is None:
        return
    _server.shutdown()
    _server.server_close()
    _server = None
    if _thread is not None:
        _thread.join(timeout=3.0)
    _thread = None
    _started_at = None


def _local_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"
