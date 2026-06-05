#!/usr/bin/env python3
"""B5 smoke: 5× in_dm. Windows + CS2, или DM_NAV_SIM=1 без игры."""

from __future__ import annotations

import argparse
import sys

from config.loader import ensure_config
from modules.dm_runner import run_in_dm_cycles


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DM nav smoke (5× in_dm)")
    parser.add_argument("--cycles", type=int, default=5)
    args = parser.parse_args(argv)
    ensure_config()
    ok = run_in_dm_cycles(args.cycles, ctx={"login": "smoke"})
    print(f"in_dm cycles ok: {ok}/{args.cycles}")
    return 0 if ok >= args.cycles else 1


if __name__ == "__main__":
    sys.exit(main())
