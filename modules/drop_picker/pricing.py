"""Steam Market price + SQLite cache (data/price_cache.db)."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

from config.paths import get_price_cache_path

_CACHE_TTL_SEC = 24 * 3600
_STEAM_URL = (
    "https://steamcommunity.com/market/priceoverview/"
    "?appid=730&currency=1&market_hash_name={name}"
)


@dataclass
class PricedItem:
    slot_id: int
    market_hash_name: str
    price_usd: float
    source: str


def _ensure_db(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prices (
                market_hash_name TEXT PRIMARY KEY,
                price_usd REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )


def _read_cache(name: str) -> float | None:
    path = get_price_cache_path()
    if not path.is_file():
        return None
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT price_usd, updated_at FROM prices WHERE market_hash_name = ?",
            (name,),
        ).fetchone()
    if not row:
        return None
    price, updated = float(row[0]), float(row[1])
    if time.time() - updated > _CACHE_TTL_SEC:
        return None
    return price


def _write_cache(name: str, price: float) -> None:
    path = get_price_cache_path()
    _ensure_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO prices (market_hash_name, price_usd, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(market_hash_name) DO UPDATE SET
                price_usd = excluded.price_usd,
                updated_at = excluded.updated_at
            """,
            (name, price, time.time()),
        )


def _parse_steam_price(payload: dict) -> float | None:
    if not payload.get("success"):
        return None
    for key in ("lowest_price", "median_price"):
        raw = payload.get(key)
        if not raw:
            continue
        m = re.search(r"[\d.]+", str(raw).replace(",", ""))
        if m:
            return float(m.group())
    return None


def fetch_steam_price_usd(market_hash_name: str, *, timeout: float = 12.0) -> float | None:
    if os.environ.get("DROP_PRICING_OFFLINE", "").lower() in ("1", "true"):
        return None

    url = _STEAM_URL.format(name=urllib.parse.quote(market_hash_name))
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "farm-panel-prototype/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    return _parse_steam_price(data)


def _heuristic_price(name: str) -> float:
    """Fallback когда Steam недоступен (тесты / offline)."""
    base = 0.05
    if "Factory New" in name:
        base += 0.40
    if "Minimal Wear" in name:
        base += 0.25
    if "Field-Tested" in name:
        base += 0.15
    if "AK-47" in name or "AWP" in name:
        base += 0.50
    if "Glock" in name:
        base += 0.08
    if "MP9" in name:
        base += 0.03
    if "P250" in name:
        base += 0.02
    return round(base, 2)


def get_price_usd(market_hash_name: str) -> tuple[float, str]:
    cached = _read_cache(market_hash_name)
    if cached is not None:
        return cached, "cache"
    steam = fetch_steam_price_usd(market_hash_name)
    if steam is not None:
        _write_cache(market_hash_name, steam)
        return steam, "steam"
    est = _heuristic_price(market_hash_name)
    _write_cache(market_hash_name, est)
    return est, "heuristic"


def price_slots(
    slot_names: list[tuple[int, str]],
) -> list[PricedItem]:
    out: list[PricedItem] = []
    for slot_id, name in slot_names:
        usd, source = get_price_usd(name)
        out.append(
            PricedItem(
                slot_id=slot_id,
                market_hash_name=name,
                price_usd=usd,
                source=source,
            )
        )
    return out
