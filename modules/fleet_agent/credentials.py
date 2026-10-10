"""Local fleet-agent token. Windows DPAPI. The Steam vault is not used."""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

from modules.fleet_agent.transport import https_context


class CredentialError(RuntimeError):
    pass


def store_agent_token(path: Path, token: str) -> None:
    if not token or any(ch.isspace() for ch in token):
        raise CredentialError("agent token is empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_protect(token.encode("utf-8")))


def load_agent_token(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        token = _unprotect(path.read_bytes()).decode("utf-8")
    except Exception as exc:
        raise CredentialError("agent token could not be read") from exc
    if not token:
        raise CredentialError("agent token could not be read")
    return token


def claim_enrollment(base_url: str, agent_id: str, code: str, *, ca_file: str = "") -> tuple[str, int]:
    """Exchange a one-time code for an agent token and its registration generation."""
    url = base_url.rstrip("/") + "/v1/enroll"
    if url.startswith("https://"):
        context = https_context(ca_file)
    elif url.startswith("http://127.0.0.1") or url.startswith("http://localhost"):
        context = None
    else:
        raise CredentialError("enrollment over cleartext is only allowed on localhost")
    raw = json.dumps({"agent_id": agent_id, "code": code}).encode("utf-8")
    req = urllib.request.Request(url, data=raw, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=2.0, context=context) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise CredentialError("enrollment was rejected") from exc
    token = str(body.get("agent_token") or "")
    try:
        generation = int(body.get("registration_generation") or 0)
    except (TypeError, ValueError):
        generation = 0
    if not body.get("ok") or not token or generation < 1:
        raise CredentialError("enrollment was rejected")
    return token, generation


def claim_enrollment_token(base_url: str, agent_id: str, code: str, *, ca_file: str = "") -> str:
    """Exchange a one-time code. The returned token is for the caller to store."""
    token, _generation = claim_enrollment(base_url, agent_id, code, ca_file=ca_file)
    return token


def _protect(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise CredentialError("local agent credentials require Windows DPAPI")
    import ctypes
    from ctypes import wintypes

    crypt32, kernel32 = _crypt32()
    in_blob, holder = _blob(data)
    out_blob = _DATA_BLOB()
    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 0x1, ctypes.byref(out_blob),
    ):
        raise CredentialError("DPAPI could not protect the agent token")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)
        del holder


def _unprotect(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise CredentialError("local agent credentials require Windows DPAPI")
    import ctypes

    crypt32, kernel32 = _crypt32()
    in_blob, holder = _blob(data)
    out_blob = _DATA_BLOB()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0x1, ctypes.byref(out_blob),
    ):
        raise CredentialError("agent token could not be read")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)
        del holder


class _DATA_BLOB:
    pass


def _crypt32():
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    global _DATA_BLOB
    _DATA_BLOB = DATA_BLOB
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = crypt32.CryptProtectData.argtypes
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def _blob(data: bytes):
    import ctypes

    buffer = ctypes.create_string_buffer(data)
    blob = _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, buffer
