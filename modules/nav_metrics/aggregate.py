"""Merge nav metrics from multiple farm PCs (PR-N8)."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config.paths import get_fleet_inbox_dir, get_nav_metrics_log_path


def _parse_ts(ts_raw: object) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(ts_raw))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except (TypeError, ValueError):
        return None


def read_jsonl_metrics(
    path: Path,
    *,
    hours: float = 24.0,
    limit: int = 5000,
) -> list[dict[str, Any]]:
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
        ts = _parse_ts(row.get("ts"))
        if ts is None or ts < cutoff:
            if ts is not None:
                break
            continue
        rows.append(row)
    rows.reverse()
    return rows


def _row_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    m = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    return (
        str(row.get("ts") or ""),
        str(row.get("host") or ""),
        str(row.get("session_id") or ""),
        str(m.get("uptime_sec") or ""),
    )


def merge_metric_rows(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for group in groups:
        for row in group:
            merged[_row_key(row)] = row
    out = list(merged.values())
    out.sort(key=lambda r: str(r.get("ts") or ""))
    return out


def collect_fleet_rows(
    *,
    hours: float = 24.0,
    include_local: bool = True,
    include_inbox: bool = True,
    extra_paths: list[Path] | None = None,
) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    if include_local:
        groups.append(read_jsonl_metrics(get_nav_metrics_log_path(), hours=hours))
    if include_inbox:
        inbox = get_fleet_inbox_dir()
        if inbox.is_dir():
            for path in sorted(inbox.glob("*.jsonl")):
                groups.append(read_jsonl_metrics(path, hours=hours))
    for path in extra_paths or []:
        groups.append(read_jsonl_metrics(path, hours=hours))
    return merge_metric_rows(*groups)


def list_inbox_files() -> list[Path]:
    inbox = get_fleet_inbox_dir()
    if not inbox.is_dir():
        return []
    return sorted(inbox.glob("*.jsonl"))


def import_fleet_inbox(*, archive: bool = True) -> dict[str, Any]:
    """
    Merge inbox JSONL files into local nav_metrics log.

    Processed files move to fleet_inbox/processed/ when archive=True.
    """
    inbox = get_fleet_inbox_dir()
    inbox.mkdir(parents=True, exist_ok=True)
    processed_dir = inbox / "processed"
    files = list_inbox_files()
    if not files:
        return {"imported_files": 0, "imported_rows": 0, "files": []}

    dest = get_nav_metrics_log_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    imported_rows = 0
    imported_files: list[str] = []

    with dest.open("a", encoding="utf-8") as out:
        for path in files:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            count = 0
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                row.setdefault("imported_from", path.name)
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                count += 1
            imported_rows += count
            imported_files.append(path.name)
            if archive:
                processed_dir.mkdir(parents=True, exist_ok=True)
                target = processed_dir / path.name
                if target.exists():
                    target.unlink()
                shutil.move(str(path), str(target))

    return {
        "imported_files": len(imported_files),
        "imported_rows": imported_rows,
        "files": imported_files,
    }
