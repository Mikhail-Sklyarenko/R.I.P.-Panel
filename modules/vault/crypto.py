"""Fernet-шифрование vault.enc; ключ в data/.vault_key (gitignored)."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from config.paths import get_vault_key_path


def ensure_key() -> bytes:
    path = get_vault_key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path.read_bytes().strip()
    key = Fernet.generate_key()
    path.write_bytes(key)
    return key


def encrypt(plaintext: bytes) -> bytes:
    return Fernet(ensure_key()).encrypt(plaintext)


def decrypt(ciphertext: bytes) -> bytes:
    try:
        return Fernet(ensure_key()).decrypt(ciphertext)
    except InvalidToken as exc:
        raise ValueError("vault decrypt failed (wrong key or corrupt file)") from exc
