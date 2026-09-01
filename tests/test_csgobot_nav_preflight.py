"""Tests for minimap nav preflight (PR-N5)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_CSGOBOT = Path(__file__).resolve().parents[1] / "vendor" / "csgobot"


def test_nav_preflight_ok_for_bundled_pack(csgobot_path) -> None:
    from nav.preflight import run_nav_preflight

    result = run_nav_preflight(pack_id="dust2_dm")
    assert result["ok"] is True
    assert result["pack_id"] == "dust2_dm"
    assert result["pack_version"]
    assert "mid" in result["goals"]
    assert not result["errors"]


def test_nav_preflight_fails_missing_pack(csgobot_path) -> None:
    from nav.preflight import run_nav_preflight

    result = run_nav_preflight(pack_id="no_such_pack_xyz")
    assert result["ok"] is False
    assert result["errors"]


def test_nav_preflight_cli_json() -> None:
    script = _CSGOBOT / "tools" / "nav_preflight.py"
    import subprocess

    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(_CSGOBOT),
        capture_output=True,
        text=True,
        check=False,
    )
    data = json.loads(proc.stdout)
    assert data["ok"] is True
    assert data["pack_id"] == "auto"
    assert "dust2_dm" in data.get("packs_ok", [])
    assert "mirage_dm" in data.get("packs_ok", [])
    assert "generic_dm" in data.get("packs_ok", [])
