"""CLI импорта аккаунтов: python -m modules.vault.cli add|list|import-fsm."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from config.loader import ensure_config
from modules.vault.fsm_import import format_import_summary, import_from_fsm_files
from modules.vault.store import (
    AccountExistsError,
    VaultError,
    add_account,
    list_accounts,
)


def _cmd_add(args: argparse.Namespace) -> int:
    mafile = Path(args.mafile).expanduser().resolve()
    if not mafile.is_file():
        print(f"maFile not found: {mafile}", file=sys.stderr)
        return 1
    try:
        entry = add_account(
            login=args.login,
            password=args.password,
            mafile_path=mafile,
        )
    except AccountExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except VaultError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"added: {entry.login}")
    return 0


def _cmd_list(_args: argparse.Namespace) -> int:
    rows = list_accounts()
    if not rows:
        print("no accounts")
        return 0
    print(f"{'login':<24} {'level':>5}  farmed_this_week")
    for row in rows:
        print(f"{row.login:<24} {row.level:>5}  {str(row.farmed_this_week).lower()}")
    return 0


def _cmd_import_fsm(args: argparse.Namespace) -> int:
    logpass = Path(args.logpass).expanduser() if args.logpass else None
    mafiles = Path(args.mafiles_dir).expanduser() if args.mafiles_dir else None
    results = import_from_fsm_files(
        logpass_path=logpass,
        mafiles_dir=mafiles,
        update_existing=not args.no_update,
        dry_run=args.dry_run,
    )
    for line in format_import_summary(results):
        print(line)
    for row in results:
        if row.status in ("added", "updated", "skipped") and row.login:
            print(f"  {row.login}: {row.status} — {row.detail}")
    if any(r.status == "error" for r in results):
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m modules.vault.cli",
        description="Vault: encrypted accounts (FSM import → vault.enc)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add_p = sub.add_parser("add", help="Add account from login/password/maFile")
    add_p.add_argument("--login", required=True)
    add_p.add_argument("--password", required=True)
    add_p.add_argument("--mafile", required=True, help="Path to .maFile (not copied)")
    add_p.set_defaults(func=_cmd_add)

    list_p = sub.add_parser("list", help="List accounts (metadata only)")
    list_p.set_defaults(func=_cmd_list)

    imp_p = sub.add_parser(
        "import-fsm",
        help="Import from logpass.txt + maFiles/ (see data/import/)",
    )
    imp_p.add_argument(
        "--logpass",
        default="",
        help="Path to logpass.txt (default: data/import/logpass.txt)",
    )
    imp_p.add_argument(
        "--mafiles-dir",
        default="",
        help="Path to maFiles directory (default: data/import/maFiles/)",
    )
    imp_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Report only, do not write vault",
    )
    imp_p.add_argument(
        "--no-update",
        action="store_true",
        help="Do not update existing logins in vault",
    )
    imp_p.set_defaults(func=_cmd_import_fsm)

    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_config()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
