"""Tests for PR-N8 fleet aggregator and nav pack editor."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from modules.nav_metrics.aggregate import collect_fleet_rows, import_fleet_inbox
from modules.nav_metrics.store import fleet_summary
from modules.nav_pack.editor import (
    has_override,
    list_pack_ids,
    load_pack_view,
    reset_pack_override,
    save_pack_override,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def test_collect_fleet_rows_merges_inbox(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    local = tmp_path / "logs" / "nav_metrics.jsonl"
    inbox = tmp_path / "fleet_inbox" / "pc2.jsonl"
    _write_jsonl(
        local,
        [
            {
                "ts": "2026-09-01T12:00:00+00:00",
                "host": "pc1",
                "login": "a1",
                "session_id": "s1",
                "metrics": {"pose_valid_pct": 90.0, "pack_id": "dust2_dm"},
            }
        ],
    )
    _write_jsonl(
        inbox,
        [
            {
                "ts": "2026-09-01T12:01:00+00:00",
                "host": "pc2",
                "login": "a2",
                "session_id": "s2",
                "metrics": {"pose_valid_pct": 80.0, "pack_id": "mirage_dm"},
            }
        ],
    )
    rows = collect_fleet_rows(hours=48.0)
    assert len(rows) == 2
    summary = fleet_summary(hours=48.0, rows=rows)
    assert summary["samples"] == 2
    assert "pc1" in summary["hosts"]
    assert "pc2" in summary["hosts"]


def test_import_fleet_inbox_archives(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    inbox = tmp_path / "fleet_inbox" / "pc3.jsonl"
    _write_jsonl(
        inbox,
        [
            {
                "ts": "2026-09-01T12:02:00+00:00",
                "host": "pc3",
                "metrics": {"pose_valid_pct": 75.0},
            }
        ],
    )
    result = import_fleet_inbox(archive=True)
    assert result["imported_rows"] == 1
    assert not inbox.exists()
    assert (tmp_path / "fleet_inbox" / "processed" / "pc3.jsonl").is_file()
    local = (tmp_path / "logs" / "nav_metrics.jsonl").read_text(encoding="utf-8")
    assert "pc3" in local


def test_nav_pack_override_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FARM_PANEL_APP_ROOT", str(tmp_path))
    bundled = tmp_path / "resources" / "nav" / "packs"
    bundled.mkdir(parents=True)
    pack = {
        "meta": {"pack_id": "dust2_dm", "map_id": "de_dust2", "version": "1.2.0"},
        "strategy": "route_cycle",
        "goal": {"id": "mid", "x": 0.52, "y": 0.48, "arrive_radius": 0.06},
        "goals": [
            {"id": "mid", "x": 0.52, "y": 0.48, "arrive_radius": 0.06},
            {"id": "bombsite_a", "x": 0.80, "y": 0.16, "arrive_radius": 0.06},
        ],
        "routing": {"dwell_at_goal_sec": 35.0, "direct_goal_dist": 0.12},
    }
    (bundled / "dust2_dm.yaml").write_text(yaml.safe_dump(pack), encoding="utf-8")
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path / "data"))

    assert "dust2_dm" in list_pack_ids()
    view = load_pack_view("dust2_dm")
    assert view.source == "bundled"

    out = save_pack_override(
        "dust2_dm",
        goal_x=0.51,
        goal_y=0.47,
        goal_arrive_radius=0.07,
        goal2_x=0.79,
        goal2_y=0.15,
        goal2_arrive_radius=0.06,
        dwell_at_goal_sec=40.0,
        direct_goal_dist=0.11,
    )
    assert out.is_file()
    assert has_override("dust2_dm")
    view2 = load_pack_view("dust2_dm")
    assert view2.source == "override"
    assert view2.goal_x == 0.51
    assert view2.version == "1.2.1"

    assert reset_pack_override("dust2_dm")
    view3 = load_pack_view("dust2_dm")
    assert view3.source == "bundled"


def test_csgobot_resolve_pack_override(tmp_path, monkeypatch, csgobot_path) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(data_dir))
    override_dir = data_dir / "nav_packs"
    override_dir.mkdir(parents=True)
    (override_dir / "dust2_dm.yaml").write_text(
        "meta:\n  pack_id: dust2_dm\n  map_id: de_dust2\n  version: 9.9.9\n"
        "goal:\n  id: mid\n  x: 0.1\n  y: 0.2\n  arrive_radius: 0.06\n",
        encoding="utf-8",
    )
    from nav.paths import resolve_nav_pack_path

    path = resolve_nav_pack_path("dust2_dm")
    assert path == override_dir / "dust2_dm.yaml"
