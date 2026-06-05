"""Оркестрация: CARE_PACKAGE → OCR → price → top 2 → click."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from config.schema import AppConfig
from core.events import EventType
from modules.drop_picker.actions import click_slots
from modules.drop_picker.detector import wait_for_care_package
from modules.drop_picker.errors import DropPickerError
from modules.drop_picker.ocr import read_all_slots
from modules.drop_picker.pricing import price_slots
from modules.drop_picker.selection import select_top_slots
from modules.drop_picker.slots import crop_slot_name, load_drop_layout
from modules.ui_nav.artifacts import ArtifactStore


class _Emit(Protocol):
    def __call__(
        self,
        event: EventType,
        detail: str = "",
        *,
        drop_log: bool = False,
    ) -> None: ...


def pick_care_package(ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    if ctx is None:
        ctx = {}
    config: AppConfig | None = ctx.get("config")
    if config is None:
        from config.loader import load_config

        config = load_config()
        ctx["config"] = config

    emit: _Emit | None = ctx.get("emit")
    session_id = str(ctx.get("session_id", "drop"))
    artifacts = ArtifactStore(session_id)
    layout = load_drop_layout(config.cs_resolution)
    fixture_dir = Path(ctx["fixture_dir"]) if ctx.get("fixture_dir") else None

    try:
        if ctx.get("screenshot_path"):
            from PIL import Image

            frame = Image.open(ctx["screenshot_path"]).convert("RGB")
            artifacts.save_image("drop_input", frame)
        else:
            frame = wait_for_care_package(ctx, layout=layout, artifacts=artifacts)

        for slot in layout.slots:
            crop = crop_slot_name(frame, slot)
            artifacts.save_image(f"drop_slot_{slot.slot_id}_crop", crop)

        slot_names = read_all_slots(frame, layout.slots, fixture_dir=fixture_dir)
        priced = price_slots(slot_names)
        picks = select_top_slots(priced, count=2)
        artifacts.save_json(
            "drop_selection",
            {
                "slots": [
                    {
                        "slot_id": p.slot_id,
                        "name": p.market_hash_name,
                        "price_usd": p.price_usd,
                        "source": p.source,
                    }
                    for p in priced
                ],
                "picked": [p.slot_id for p in picks],
            },
        )

        if emit:
            summary = ", ".join(
                f"#{p.slot_id} ${p.price_usd:.2f}" for p in picks
            )
            emit(
                EventType.DROP_PICKED,
                f"top2: {summary}",
                drop_log=True,
            )

        if config.auto_collect_drop:
            click_slots(ctx, layout, picks, artifacts)
        else:
            artifacts.log_step("drop_clicks_skipped", reason="auto_collect_drop=false")

        _maybe_notify_telegram(ctx, picks=picks, artifacts=artifacts)

        return {
            "ok": True,
            "picked": [p.market_hash_name for p in picks],
            "priced": priced,
        }
    except DropPickerError as exc:
        if emit:
            emit(EventType.SESSION_FAILED, f"drop_picker: {exc}")
        return {"ok": False, "error": str(exc)}


def _maybe_notify_telegram(
    ctx: dict[str, Any],
    *,
    picks: list[Any],
    artifacts: ArtifactStore,
) -> None:
    try:
        from modules.telegram.notify import notify_drop

        result = notify_drop(ctx, picks=picks, artifacts=artifacts)
        if result:
            artifacts.log_step("telegram_sent", method=result.method, detail=result.detail)
            emit = ctx.get("emit")
            if emit:
                emit(
                    EventType.TELEGRAM_SENT,
                    f"{result.method} ({result.detail})",
                    drop_log=True,
                )
    except Exception:
        pass
