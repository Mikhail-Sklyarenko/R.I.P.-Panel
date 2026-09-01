#!/usr/bin/env python3
"""Fleet nav metrics report from data/logs/nav_metrics.jsonl (PR-N7)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.nav_metrics.aggregate import collect_fleet_rows, import_fleet_inbox, list_inbox_files  # noqa: E402
from modules.nav_metrics.store import fleet_summary, format_fleet_dashboard  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=24.0, help="Lookback window")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument(
        "--no-inbox",
        action="store_true",
        help="Only local nav_metrics.jsonl (skip fleet_inbox/)",
    )
    parser.add_argument(
        "--import-inbox",
        action="store_true",
        help="Merge inbox files into local log before report",
    )
    args = parser.parse_args()

    if args.import_inbox:
        result = import_fleet_inbox(archive=True)
        print(
            f"imported {result['imported_rows']} rows "
            f"from {result['imported_files']} file(s)\n"
        )

    include_inbox = not args.no_inbox
    if args.json:
        rows = collect_fleet_rows(hours=args.hours, include_inbox=include_inbox)
        print(json.dumps(fleet_summary(hours=args.hours, rows=rows), indent=2))
    else:
        print(format_fleet_dashboard(hours=args.hours, include_inbox=include_inbox))
        pending = list_inbox_files()
        if pending:
            print(f"\n  inbox pending: {len(pending)} file(s) — run scripts/nav_fleet_import.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
