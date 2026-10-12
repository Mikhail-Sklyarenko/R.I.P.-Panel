"""HTTPS loopback for SECURE_LAN. This is not a four-PC trial."""
from __future__ import annotations

import json
import ssl
import subprocess
import urllib.error
import urllib.request

from core.wingman_fleet.coordinator import Coordinator
from core.wingman_fleet.server import FleetServer
from core.wingman_fleet.store import FleetStore
from tests.test_fleet_acceptance import _cert
from tests.test_wingman_fleet_fsm import TOKEN


def test_https_health_and_operator_authorization(tmp_path):
    cert, key = _cert(tmp_path)
    store = FleetStore(tmp_path / "c.db")
    coord = Coordinator(store, token=TOKEN, operator_token="o" * 32, clock=lambda: 1.0)
    server = FleetServer(coord, host="127.0.0.1", port=0)
    server.enable_tls(str(cert), str(key))
    server.start()
    url = f"https://127.0.0.1:{server.port}"
    try:
        raw = subprocess.check_output(
            ["curl.exe", "--cacert", str(cert), f"{url}/v1/health"],
            text=True, stderr=subprocess.STDOUT,
        )
        assert '"ok": true' in raw.replace(" ", "") or '"ok":true' in raw.replace(" ", "")
        context = ssl.create_default_context(cafile=str(cert))
        with urllib.request.urlopen(f"{url}/v1/health", context=context, timeout=3) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        assert body["ok"] is True
        for headers in (
            {},
            {"X-Fleet-Token": TOKEN},
            {"X-Operator-Token": TOKEN},
            {"Authorization": f"Bearer {TOKEN}"},
        ):
            req = urllib.request.Request(f"{url}/v1/status", headers=headers)
            try:
                urllib.request.urlopen(req, context=context, timeout=3)
                raised = False
            except urllib.error.HTTPError as exc:
                raised = True
                assert exc.code == 403
            assert raised
        req = urllib.request.Request(f"{url}/v1/status", headers={"X-Operator-Token": "o" * 32})
        with urllib.request.urlopen(req, context=context, timeout=3) as resp:
            status = json.loads(resp.read().decode("utf-8"))
        assert status["ok"] is True
    finally:
        server.stop()
        store.close()


def test_https_rejects_http_and_a_foreign_ca(tmp_path):
    cert, key = _cert(tmp_path)
    store = FleetStore(tmp_path / "c.db")
    coord = Coordinator(store, token=TOKEN, operator_token="o" * 32, clock=lambda: 1.0)
    server = FleetServer(coord, host="127.0.0.1", port=0)
    server.enable_tls(str(cert), str(key))
    server.start()
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other, _other_key = _cert(other_dir)
    try:
        failed = subprocess.run(
            ["curl.exe", "--cacert", str(other), f"https://127.0.0.1:{server.port}/v1/health"],
            capture_output=True, text=True,
        )
        assert failed.returncode != 0
        insecure = subprocess.run(
            ["curl.exe", f"http://127.0.0.1:{server.port}/v1/health"],
            capture_output=True, text=True,
        )
        assert insecure.returncode != 0 or "ok" not in (insecure.stdout + insecure.stderr)
    finally:
        server.stop()
        store.close()
