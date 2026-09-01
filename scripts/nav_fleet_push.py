#!/usr/bin/env python3
"""Push nav metrics to central fleet collector (PR-N9 test CLI)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config.loader import load_config  # noqa: E402
from modules.nav_metrics.push_client import push_metric_record  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="", help="Collector POST URL")
    parser.add_argument("--token", default="", help="Bearer token")
    parser.add_argument(
        "--file",
        type=Path,
        help="Push last line from JSONL file (default: data/logs/nav_metrics.jsonl)",
    )
    args = parser.parse_args()

    cfg = load_config()
    url = (args.url or cfg.nav_fleet_push_url).strip()
    token = args.token or cfg.nav_fleet_collector_token
    if not url:
        print("set nav_fleet_push_url in config or pass --url", file=sys.stderr)
        return 1

    if args.file:
        path = args.file
    else:
        from config.paths import get_nav_metrics_log_path

        path = get_nav_metrics_log_path()

    if not path.is_file():
        print(f"no metrics file: {path}", file=sys.stderr)
        return 1

    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        print("metrics file empty", file=sys.stderr)
        return 1
    record = json.loads(lines[-1])
    ok, detail = push_metric_record(record, url=url, token=token)
    print(detail)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
