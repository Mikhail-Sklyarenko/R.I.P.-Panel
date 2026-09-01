#!/usr/bin/env python3
"""Import fleet nav_metrics JSONL drops from data/fleet_inbox/ (PR-N8)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.nav_metrics.aggregate import import_fleet_inbox, list_inbox_files  # noqa: E402
from modules.nav_metrics.store import format_fleet_dashboard  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-archive",
        action="store_true",
        help="Keep inbox files after import",
    )
    parser.add_argument("--json", action="store_true", help="JSON result")
    args = parser.parse_args()

    pending = list_inbox_files()
    if not pending:
        print("fleet inbox empty — drop *.jsonl from farm PCs into data/fleet_inbox/")
        return 0

    result = import_fleet_inbox(archive=not args.no_archive)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(
            f"imported {result['imported_rows']} rows "
            f"from {result['imported_files']} file(s)"
        )
        print()
        print(format_fleet_dashboard(hours=24.0, include_inbox=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
