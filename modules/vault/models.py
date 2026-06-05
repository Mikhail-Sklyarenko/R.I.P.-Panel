"""Модели vault и публичного index (без паролей)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class VaultAccountSecret(BaseModel):
    login: str
    password: str
    shared_secret: str
    identity_secret: str


class VaultPayload(BaseModel):
    version: int = 1
    accounts: dict[str, VaultAccountSecret] = Field(default_factory=dict)


class AccountIndexEntry(BaseModel):
    login: str
    level: int = 0
    xp: int = 0
    farmed_this_week: bool = False


class AccountsIndex(BaseModel):
    version: int = 1
    accounts: list[AccountIndexEntry] = Field(default_factory=list)
