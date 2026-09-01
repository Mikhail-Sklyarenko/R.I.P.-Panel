"""Tests for fleet nav metrics ingest/store (PR-N7)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from modules.nav_metrics.ingest import NAV_METRICS_PREFIX, parse_nav_metrics_lines
from modules.nav_metrics.store import (
    append_nav_metric,
    fleet_summary,
    format_fleet_dashboard,
    read_recent_metrics,
)


def test_parse_nav_metrics_lines() -> None:
    payload = {"pose_valid_pct": 88.5, "pack_id": "dust2_dm"}
    line = f"2026-01-01 12:00:00 INFO CS2Bot nav_metrics: {json.dumps(payload)}"
    out = parse_nav_metrics_lines(line)
    assert len(out) == 1
    assert out[0]["pose_valid_pct"] == 88.5
    assert NAV_METRICS_PREFIX in line


def test_append_and_fleet_summary(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    append_nav_metric(
        {
            "pack_id": "mirage_dm",
            "pose_valid_pct": 85.0,
            "time_at_goal_pct": 20.0,
            "stuck_events": 1,
            "fallback_count": 0,
            "goal_id": "mid",
        },
        login="acc1",
        session_id="sess1",
        host="pc-a",
    )
    append_nav_metric(
        {
            "pack_id": "dust2_dm",
            "pose_valid_pct": 90.0,
            "time_at_goal_pct": 25.0,
            "stuck_events": 0,
            "fallback_count": 0,
            "goal_id": "mid",
        },
        login="acc2",
        session_id="sess2",
        host="pc-b",
    )
    rows = read_recent_metrics(hours=24.0)
    assert len(rows) == 2
    summary = fleet_summary(hours=24.0)
    assert summary["samples"] == 2
    assert summary["avg_pose_valid_pct"] == 87.5
    assert "mirage_dm" in summary["by_pack"]
    assert "dust2_dm" in summary["by_pack"]
    dash = format_fleet_dashboard(hours=24.0)
    assert "Nav fleet" in dash
    assert "pc-a" in dash or "pc-b" in dash


def test_fleet_summary_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    summary = fleet_summary()
    assert summary["samples"] == 0
    assert summary["alerts"] == []
