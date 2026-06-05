"""Telegram Bot API (stdlib urllib; токены только из config)."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config.paths import get_data_dir
from modules.telegram.errors import TelegramError


@dataclass(frozen=True)
class SendResult:
    ok: bool
    method: str
    detail: str
    simulated: bool = False


def _sim_enabled() -> bool:
    return os.environ.get("TELEGRAM_SIM", "").lower() in ("1", "true", "yes")


def _sim_record(method: str, payload: dict[str, Any]) -> SendResult:
    out_dir = get_data_dir() / "telegram_sim"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "outbox.jsonl"
    line = json.dumps({"method": method, **payload}, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return SendResult(ok=True, method=method, detail=f"sim → {path.name}", simulated=True)


def _api_json(token: str, method: str, body: dict[str, Any]) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(body).encode("utf-8")
    req = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise TelegramError(f"{method} HTTP {exc.code}: {err_body}") from exc
    except URLError as exc:
        raise TelegramError(f"{method} network: {exc}") from exc
    if not raw.get("ok"):
        raise TelegramError(f"{method} API: {raw.get('description', raw)}")
    return raw


def _multipart_photo(
    token: str,
    chat_id: str,
    photo_path: Path,
    caption: str,
) -> dict[str, Any]:
    boundary = f"FarmPanel{uuid.uuid4().hex}"
    photo_bytes = photo_path.read_bytes()
    filename = photo_path.name
    parts: list[bytes] = []

    def field(name: str, value: str) -> None:
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode()
        )

    field("chat_id", str(chat_id))
    field("caption", caption[:1024])
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="photo"; filename="{filename}"\r\n'
        f"Content-Type: image/png\r\n\r\n".encode()
    )
    parts.append(photo_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)

    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    req = Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=60) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise TelegramError(f"sendPhoto HTTP {exc.code}: {err_body}") from exc
    except URLError as exc:
        raise TelegramError(f"sendPhoto network: {exc}") from exc
    if not raw.get("ok"):
        raise TelegramError(f"sendPhoto API: {raw.get('description', raw)}")
    return raw


def send_message(token: str, chat_id: str, text: str) -> SendResult:
    if _sim_enabled():
        return _sim_record(
            "sendMessage",
            {"chat_id": chat_id, "text": text},
        )
    if not token or not chat_id:
        raise TelegramError("telegram_bot_token or telegram_chat_id empty")
    _api_json(
        token,
        "sendMessage",
        {"chat_id": chat_id, "text": text[:4096]},
    )
    return SendResult(ok=True, method="sendMessage", detail="sent")


def send_photo(
    token: str,
    chat_id: str,
    photo_path: Path,
    caption: str,
) -> SendResult:
    if _sim_enabled():
        return _sim_record(
            "sendPhoto",
            {
                "chat_id": chat_id,
                "caption": caption,
                "photo": str(photo_path),
            },
        )
    if not token or not chat_id:
        raise TelegramError("telegram_bot_token or telegram_chat_id empty")
    if not photo_path.is_file():
        raise TelegramError(f"photo not found: {photo_path}")
    _multipart_photo(token, chat_id, photo_path, caption)
    return SendResult(ok=True, method="sendPhoto", detail=str(photo_path.name))
