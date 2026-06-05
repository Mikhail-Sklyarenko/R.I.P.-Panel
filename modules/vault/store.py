"""Encrypted vault (data/vault.enc) + публичный index (accounts.index.json)."""

from __future__ import annotations

import json
from pathlib import Path

from config.paths import get_accounts_index_path, get_vault_enc_path
from modules.vault.crypto import decrypt, encrypt
from modules.vault.mafile import parse_mafile
from modules.vault.models import (
    AccountIndexEntry,
    AccountsIndex,
    VaultAccountSecret,
    VaultPayload,
)


class VaultError(Exception):
    pass


class AccountExistsError(VaultError):
    pass


class AccountNotFoundError(VaultError):
    pass


def _account_id(login: str) -> str:
    return login.strip()


def _load_payload() -> VaultPayload:
    path = get_vault_enc_path()
    if not path.exists():
        return VaultPayload()
    data = decrypt(path.read_bytes())
    return VaultPayload.model_validate_json(data.decode("utf-8"))


def _save_payload(payload: VaultPayload) -> None:
    path = get_vault_enc_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encrypt(payload.model_dump_json().encode("utf-8")))


def _load_index() -> AccountsIndex:
    path = get_accounts_index_path()
    if not path.exists():
        return AccountsIndex()
    return AccountsIndex.model_validate_json(path.read_text(encoding="utf-8"))


def _save_index(index: AccountsIndex) -> None:
    path = get_accounts_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    sorted_accounts = sorted(index.accounts, key=lambda e: e.login.lower())
    index = AccountsIndex(version=index.version, accounts=sorted_accounts)
    path.write_text(
        index.model_dump_json(indent=2),
        encoding="utf-8",
    )


def has_account(login: str) -> bool:
    login = login.strip()
    return _account_id(login) in _load_payload().accounts


def upsert_account(
    *,
    login: str,
    password: str,
    mafile_path: Path,
    update_existing: bool = True,
) -> AccountIndexEntry:
    """Добавить или обновить секреты; метаданные index сохраняются при update."""
    login = login.strip()
    if not login:
        raise VaultError("login is required")

    ma_name, shared_secret, identity_secret = parse_mafile(mafile_path)
    if ma_name.lower() != login.lower():
        raise VaultError(
            f"maFile account_name '{ma_name}' does not match login '{login}'"
        )

    aid = _account_id(login)
    payload = _load_payload()
    exists = aid in payload.accounts
    if exists and not update_existing:
        raise AccountExistsError(f"account already exists: {login}")

    payload.accounts[aid] = VaultAccountSecret(
        login=login,
        password=password,
        shared_secret=shared_secret,
        identity_secret=identity_secret,
    )
    _save_payload(payload)

    index = _load_index()
    entry = _find_index_entry(index, login)
    if entry is None:
        entry = AccountIndexEntry(login=login, level=0, farmed_this_week=False)
    index.accounts = [e for e in index.accounts if e.login.lower() != login.lower()]
    index.accounts.append(entry)
    _save_index(index)
    return entry


def add_account(
    *,
    login: str,
    password: str,
    mafile_path: Path,
) -> AccountIndexEntry:
    """Добавить аккаунт; секреты в vault.enc, метаданные в index."""
    return upsert_account(
        login=login,
        password=password,
        mafile_path=mafile_path,
        update_existing=False,
    )


def list_accounts() -> list[AccountIndexEntry]:
    return list(_load_index().accounts)


def list_unfarmed_logins() -> list[str]:
    """Очередь конвейера: аккаунты без farmed_this_week."""
    return [
        e.login
        for e in sorted(_load_index().accounts, key=lambda x: x.login.lower())
        if not e.farmed_this_week
    ]


def _find_index_entry(index: AccountsIndex, login: str) -> AccountIndexEntry | None:
    login = login.strip()
    for e in index.accounts:
        if e.login.lower() == login.lower():
            return e
    return None


def update_account_meta(
    login: str,
    *,
    level: int | None = None,
    xp: int | None = None,
    farmed_this_week: bool | None = None,
) -> AccountIndexEntry:
    login = login.strip()
    index = _load_index()
    entry = _find_index_entry(index, login)
    if entry is None:
        raise AccountNotFoundError(f"account not found: {login}")
    if level is not None:
        entry.level = level
    if xp is not None:
        entry.xp = xp
    if farmed_this_week is not None:
        entry.farmed_this_week = farmed_this_week
    index.accounts = [
        e if e.login.lower() != login.lower() else entry for e in index.accounts
    ]
    _save_index(index)
    return entry


def mark_farmed_this_week(login: str) -> AccountIndexEntry:
    return update_account_meta(login, farmed_this_week=True)


def load_account(login: str) -> dict:
    """Секреты + метаданные index для оркестратора."""
    login = login.strip()
    aid = _account_id(login)
    payload = _load_payload()
    secret = payload.accounts.get(aid)
    if secret is None:
        raise AccountNotFoundError(f"account not found: {login}")

    meta = next(
        (e for e in _load_index().accounts if e.login.lower() == login.lower()),
        AccountIndexEntry(login=login),
    )
    return {
        "login": secret.login,
        "password": secret.password,
        "shared_secret": secret.shared_secret,
        "identity_secret": secret.identity_secret,
        "level": meta.level,
        "xp": meta.xp,
        "farmed_this_week": meta.farmed_this_week,
    }
