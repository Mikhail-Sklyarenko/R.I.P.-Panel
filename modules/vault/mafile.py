"""Разбор .maFile (Steam Guard); файл не копируется в data/."""

from __future__ import annotations

import json
from pathlib import Path


def parse_mafile(path: Path) -> tuple[str, str, str]:
    """
    Вернуть (account_name, shared_secret, identity_secret).
    account_name из JSON, иначе stem файла.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"invalid maFile JSON: {path}")

    shared = raw.get("shared_secret")
    identity = raw.get("identity_secret")
    if not shared or not identity:
        raise ValueError(f"maFile missing shared_secret/identity_secret: {path}")

    name = raw.get("account_name") or path.stem
    if name.endswith(".maFile"):
        name = name[: -len(".maFile")]
    return str(name), str(shared), str(identity)
