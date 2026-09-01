"""Parse nav_metrics lines from csgobot stderr."""

from __future__ import annotations

import json
from pathlib import Path

NAV_METRICS_PREFIX = "nav_metrics: "


def parse_nav_metrics_lines(text: str) -> list[dict]:
    """Extract JSON payloads from log lines containing ``nav_metrics:``."""
    out: list[dict] = []
    for line in text.splitlines():
        if NAV_METRICS_PREFIX not in line:
            continue
        payload = line.split(NAV_METRICS_PREFIX, 1)[1].strip()
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def tail_nav_metrics(path: Path, offset: int) -> tuple[list[dict], int]:
    """Read new stderr bytes from *offset*; return metrics + new offset."""
    if not path.is_file():
        return [], offset
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            fh.seek(offset)
            chunk = fh.read()
            new_offset = fh.tell()
    except OSError:
        return [], offset
    return parse_nav_metrics_lines(chunk), new_offset
