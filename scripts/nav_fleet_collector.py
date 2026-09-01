#!/usr/bin/env python3
"""Run central nav fleet HTTP collector (PR-N9)."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config.loader import load_config  # noqa: E402
from modules.nav_metrics.collector import (  # noqa: E402
    collector_status,
    start_collector,
    stop_collector,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0, help="Override config port")
    parser.add_argument("--token", default="", help="Override config token")
    parser.add_argument("--json", action="store_true", help="Print startup info as JSON")
    args = parser.parse_args()

    cfg = load_config()
    port = args.port or cfg.nav_fleet_collector_port
    token = args.token if args.token else cfg.nav_fleet_collector_token

    info = start_collector(port=port, token=token)
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        print(f"nav fleet collector listening on {info.get('url')}")
        print(f"health: {info.get('health')}")
        print("Ctrl+C to stop")

    def _shutdown(_signum: int, _frame: object) -> None:
        stop_collector()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        while True:
            time.sleep(5.0)
            status = collector_status()
            if not status.get("running"):
                break
    except KeyboardInterrupt:
        pass
    finally:
        stop_collector()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
