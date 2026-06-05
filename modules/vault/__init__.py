"""Vault: data/vault.enc + data/accounts.index.json (без logpass.txt)."""

from __future__ import annotations

from typing import Any

from modules.vault.store import (
    AccountExistsError,
    AccountNotFoundError,
    VaultError,
    add_account,
    has_account,
    upsert_account,
    list_accounts,
    list_unfarmed_logins,
    load_account,
    mark_farmed_this_week,
    update_account_meta,
)

__all__ = [
    "AccountExistsError",
    "AccountNotFoundError",
    "VaultError",
    "add_account",
    "has_account",
    "upsert_account",
    "list_accounts",
    "list_unfarmed_logins",
    "load_account",
    "mark_farmed_this_week",
    "update_account_meta",
]
