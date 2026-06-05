"""CLI: python -m core.conveyor_cli [--max N]"""

from __future__ import annotations

import argparse
import sys

from core.conveyor import run_night_conveyor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Headless farm conveyor (B10)")
    parser.add_argument(
        "--max",
        type=int,
        default=0,
        help="Max accounts (0 = all unfarmed)",
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Force fake modules",
    )
    args = parser.parse_args(argv)
    max_acc = args.max if args.max > 0 else 9999

    lines: list[str] = []

    def log(msg: str) -> None:
        print(msg, flush=True)
        lines.append(msg)

    ok = run_night_conveyor(
        max_accounts=max_acc,
        test_mode=True if args.test_mode else None,
        on_log=log,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
