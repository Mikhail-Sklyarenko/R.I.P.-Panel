"""Persist and aggregate fleet nav metrics (JSONL)."""

from __future__ import annotations

import json
import socket
from datetime import datetime, timedelta, timezone
from typing import Any

from config.paths import get_nav_metrics_log_path


def append_nav_metric(
    metrics: dict[str, Any],
    *,
    login: str = "",
    session_id: str = "",
    host: str | None = None,
) -> None:
    path = get_nav_metrics_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "login": login,
        "session_id": session_id,
        "host": host or socket.gethostname(),
        "metrics": metrics,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    _maybe_push_fleet(record)


def _maybe_push_fleet(record: dict[str, Any]) -> None:
    try:
        from config.loader import load_config
        from modules.nav_metrics.push_client import push_metric_record_async

        cfg = load_config()
        url = (getattr(cfg, "nav_fleet_push_url", "") or "").strip()
        if not url:
            return
        token = getattr(cfg, "nav_fleet_collector_token", "") or ""
        push_metric_record_async(record, url=url, token=token)
    except Exception:
        return


def read_recent_metrics(
    *,
    hours: float = 24.0,
    limit: int = 500,
) -> list[dict[str, Any]]:
    path = get_nav_metrics_log_path()
    if not path.is_file():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in reversed(lines):
        if len(rows) >= limit:
            break
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        ts_raw = row.get("ts", "")
        try:
            ts = datetime.fromisoformat(str(ts_raw))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if ts < cutoff:
            break
        rows.append(row)
    rows.reverse()
    return rows


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def fleet_summary(
    *,
    hours: float = 24.0,
    rows: list[dict[str, Any]] | None = None,
    include_inbox: bool = True,
) -> dict[str, Any]:
    if rows is None:
        from modules.nav_metrics.aggregate import collect_fleet_rows

        rows = collect_fleet_rows(hours=hours, include_inbox=include_inbox)
    if not rows:
        return {
            "hours": hours,
            "samples": 0,
            "hosts": [],
            "logins": [],
            "avg_pose_valid_pct": 0.0,
            "avg_time_at_goal_pct": 0.0,
            "total_stuck_events": 0,
            "total_fallback_count": 0,
            "by_pack": {},
            "alerts": [],
            "latest": None,
        }

    pose_vals: list[float] = []
    goal_vals: list[float] = []
    stuck_total = 0
    fallback_total = 0
    hosts: set[str] = set()
    logins: set[str] = set()
    by_pack: dict[str, dict[str, Any]] = {}

    for row in rows:
        hosts.add(str(row.get("host") or ""))
        login = str(row.get("login") or "")
        if login:
            logins.add(login)
        m = row.get("metrics") or {}
        if not isinstance(m, dict):
            continue
        pose_vals.append(float(m.get("pose_valid_pct") or 0.0))
        goal_vals.append(float(m.get("time_at_goal_pct") or 0.0))
        stuck_total += int(m.get("stuck_events") or 0)
        fallback_total += int(m.get("fallback_count") or 0)
        pack = str(m.get("pack_id") or "unknown")
        bucket = by_pack.setdefault(
            pack,
            {"samples": 0, "pose_vals": [], "stuck": 0},
        )
        bucket["samples"] += 1
        bucket["pose_vals"].append(float(m.get("pose_valid_pct") or 0.0))
        bucket["stuck"] += int(m.get("stuck_events") or 0)

    by_pack_out: dict[str, Any] = {}
    for pack, bucket in sorted(by_pack.items()):
        by_pack_out[pack] = {
            "samples": bucket["samples"],
            "avg_pose_valid_pct": round(_avg(bucket["pose_vals"]), 1),
            "stuck_events": bucket["stuck"],
        }

    avg_pose = _avg(pose_vals)
    alerts: list[str] = []
    if avg_pose < 70.0 and pose_vals:
        alerts.append(f"low pose_valid_pct ({avg_pose:.0f}% avg)")
    if stuck_total > max(10, len(rows) // 2):
        alerts.append(f"high stuck_events ({stuck_total} in window)")

    latest = rows[-1]
    latest_m = latest.get("metrics") if isinstance(latest.get("metrics"), dict) else {}

    return {
        "hours": hours,
        "samples": len(rows),
        "hosts": sorted(h for h in hosts if h),
        "logins": sorted(logins),
        "avg_pose_valid_pct": round(avg_pose, 1),
        "avg_time_at_goal_pct": round(_avg(goal_vals), 1),
        "total_stuck_events": stuck_total,
        "total_fallback_count": fallback_total,
        "by_pack": by_pack_out,
        "alerts": alerts,
        "latest": {
            "ts": latest.get("ts"),
            "login": latest.get("login"),
            "host": latest.get("host"),
            "pack_id": latest_m.get("pack_id"),
            "goal_id": latest_m.get("goal_id"),
            "pose_valid_pct": latest_m.get("pose_valid_pct"),
            "time_at_goal_pct": latest_m.get("time_at_goal_pct"),
            "stuck_events": latest_m.get("stuck_events"),
        },
    }


def format_fleet_dashboard(*, hours: float = 24.0, include_inbox: bool = True) -> str:
    s = fleet_summary(hours=hours, include_inbox=include_inbox)
    lines = [
        f"Nav fleet ({s['hours']:.0f}h) — {s['samples']} samples",
        f"  hosts: {', '.join(s['hosts']) or '—'} ({len(s['hosts'])} PCs)",
        f"  logins: {len(s['logins'])}",
        f"  pose_valid: {s['avg_pose_valid_pct']}%  at_goal: {s['avg_time_at_goal_pct']}%",
        f"  stuck: {s['total_stuck_events']}  fallback: {s['total_fallback_count']}",
    ]
    if s["by_pack"]:
        lines.append("  by pack:")
        for pack, info in s["by_pack"].items():
            lines.append(
                f"    {pack}: n={info['samples']} pose={info['avg_pose_valid_pct']}% "
                f"stuck={info['stuck_events']}"
            )
    latest = s.get("latest")
    if latest:
        lines.append(
            f"  latest: {latest.get('login') or '?'} @ {latest.get('host') or '?'}"
            f" pack={latest.get('pack_id') or '?'}"
            f" pose={latest.get('pose_valid_pct')}%"
            f" goal={latest.get('goal_id') or '?'}"
        )
    if s["alerts"]:
        lines.append("  ALERT: " + "; ".join(s["alerts"]))
    return "\n".join(lines)
