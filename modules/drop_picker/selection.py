"""Выбор top-N слотов по цене (FSM: 4 → 2)."""

from __future__ import annotations

from modules.drop_picker.pricing import PricedItem


def select_top_slots(items: list[PricedItem], count: int = 2) -> list[PricedItem]:
    if count < 1:
        raise ValueError("count must be >= 1")
    ordered = sorted(
        items,
        key=lambda it: (it.price_usd, -it.slot_id),
        reverse=True,
    )
    return ordered[: min(count, len(ordered))]
