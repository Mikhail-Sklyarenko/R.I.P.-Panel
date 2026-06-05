#!/usr/bin/env python3
"""Точка входа: UI панели, headless conveyor, vault CLI (frozen exe)."""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="FarmPanel",
        description="Farm Panel Prototype — solo DM, 1 acc = 1 CS2",
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Включить fake modules (без Steam / реального фарма)",
    )
    parser.add_argument(
        "--conveyor",
        action="store_true",
        help="Headless конвейер (unfarmed acc), без UI",
    )
    parser.add_argument(
        "--conveyor-max",
        type=int,
        default=0,
        help="Лимит acc для --conveyor (0 = все unfarmed)",
    )
    parser.add_argument(
        "--vault-cli",
        nargs=argparse.REMAINDER,
        help="Vault CLI: add|list|import-fsm (после --vault-cli)",
    )
    return parser


def _run_vault_cli(argv: list[str]) -> int:
    from modules.vault.cli import main as vault_main

    return int(vault_main(argv))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.vault_cli is not None:
        cli_args = list(args.vault_cli)
        if cli_args and cli_args[0] == "--":
            cli_args = cli_args[1:]
        return _run_vault_cli(cli_args)

    from config.loader import ensure_config, load_config, save_config

    ensure_config()
    cfg = load_config()
    if args.test_mode and not cfg.test_mode:
        cfg = cfg.model_copy(update={"test_mode": True})
        save_config(cfg)
    elif not args.test_mode:
        cfg = load_config()

    if args.conveyor:
        from core.conveyor import run_conveyor, run_night_conveyor

        max_acc = args.conveyor_max if args.conveyor_max > 0 else 9999
        if max_acc >= 9999:
            ok = run_conveyor(test_mode=cfg.test_mode)
        else:
            ok = run_night_conveyor(
                max_accounts=max_acc,
                test_mode=cfg.test_mode,
            )
        return 0 if ok else 1

    from panel.app import run_panel

    run_panel(test_mode=cfg.test_mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
