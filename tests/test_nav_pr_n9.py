"""Tests for PR-N9 radar overlay editor and HTTP fleet collector."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from modules.nav_metrics.collector import (
    collector_status,
    ingest_remote_payload,
    start_collector,
    stop_collector,
)
from modules.nav_metrics.push_client import push_metric_record
from modules.nav_metrics.store import append_nav_metric, read_recent_metrics
from modules.nav_pack.radar_overlay import (
    build_overlay_state,
    norm_to_pixel,
    pixel_to_norm,
    render_overlay_png_bytes,
)


def test_pixel_norm_roundtrip() -> None:
    x, y = pixel_to_norm(160, 80, 320, 320)
    px, py = norm_to_pixel(x, y, 320, 320)
    assert px == 160
    assert py == 80


def test_build_overlay_state_dust2() -> None:
    state = build_overlay_state("dust2_dm", goal_x=0.55, goal_y=0.45)
    assert state.pack_id == "dust2_dm"
    assert state.map_id == "de_dust2"
    assert state.image_size[0] > 0
    assert any(m.marker_id and m.x == 0.55 for m in state.markers)


def test_render_overlay_png() -> None:
    state = build_overlay_state("dust2_dm")
    png = render_overlay_png_bytes(state, display_size=128)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_ingest_remote_payload(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    result = ingest_remote_payload(
        {
            "host": "pc-remote",
            "login": "acc1",
            "session_id": "s9",
            "metrics": {"pose_valid_pct": 88.0, "pack_id": "mirage_dm"},
        }
    )
    assert result["ok"] is True
    rows = read_recent_metrics(hours=48.0)
    assert len(rows) == 1
    assert rows[0]["host"] == "pc-remote"
    assert rows[0]["metrics"]["pack_id"] == "mirage_dm"


def test_collector_start_stop(monkeypatch) -> None:
    stop_collector()
    info = start_collector(port=18765, token="secret")
    assert info["running"] is True
    status = collector_status()
    assert status["running"] is True
    assert status["port"] == 18765
    stop_collector()
    assert collector_status()["running"] is False


def test_collector_http_ingest(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    stop_collector()
    start_collector(port=18766, token="tok")
    try:
        body = json.dumps(
            {
                "host": "http-pc",
                "login": "u1",
                "metrics": {"pose_valid_pct": 91.0, "pack_id": "generic_dm"},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:18766/api/v1/nav_metrics",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer tok",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload.get("ok") is True
        rows = read_recent_metrics(hours=48.0)
        assert rows[-1]["host"] == "http-pc"
    finally:
        stop_collector()


def test_push_metric_record(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            received.append(json.loads(raw.decode("utf-8")))
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        record = {
            "ts": "2026-09-01T12:00:00+00:00",
            "host": "pc1",
            "metrics": {"pose_valid_pct": 85.0},
        }
        ok, _detail = push_metric_record(
            record,
            url=f"http://127.0.0.1:{port}/api/v1/nav_metrics",
            token="",
        )
        assert ok is True
        assert received[0]["host"] == "pc1"
    finally:
        server.shutdown()
        server.server_close()


def test_append_nav_metric_pushes_when_configured(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    pushed: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            pushed.append(json.loads(raw.decode("utf-8")))
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    from config.loader import load_config, save_config

    cfg = load_config()
    cfg = cfg.model_copy(
        update={
            "nav_fleet_push_url": f"http://127.0.0.1:{port}/api/v1/nav_metrics",
            "nav_fleet_collector_token": "",
        }
    )
    save_config(cfg)
    try:
        append_nav_metric({"pose_valid_pct": 77.0, "pack_id": "dust2_dm"}, login="a")
        for _ in range(20):
            if pushed:
                break
            threading.Event().wait(0.05)
        assert pushed
        assert pushed[0]["metrics"]["pose_valid_pct"] == 77.0
    finally:
        server.shutdown()
        server.server_close()
