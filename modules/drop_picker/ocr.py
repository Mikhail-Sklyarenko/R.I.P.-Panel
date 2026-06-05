"""OCR имён предметов по слотам (Tesseract optional / fixture / sim)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from PIL import Image, ImageDraw

from modules.drop_picker.slots import SlotLayout, crop_slot_name


def _normalize_name(text: str) -> str:
    line = " ".join(text.split()).strip()
    return line


def _ocr_tesseract(image: Image.Image) -> str:
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError("pytesseract not installed") from exc
    raw = pytesseract.image_to_string(image, config="--psm 7")
    return _normalize_name(raw)


def _ocr_fixture(slot_id: int, fixture_dir: Path | None) -> str | None:
    if fixture_dir is None:
        return None
    names_path = fixture_dir / "slot_names.json"
    if names_path.is_file():
        data = json.loads(names_path.read_text(encoding="utf-8"))
        names = data.get("slots", [])
        if 1 <= slot_id <= len(names):
            return str(names[slot_id - 1])
    return None


def _ocr_sim(slot_id: int) -> str:
    defaults = [
        "AK-47 | Redline (Field-Tested)",
        "Glock-18 | Water Elemental (Minimal Wear)",
        "MP9 | Storm (Factory New)",
        "P250 | Sand Dune (Battle-Scarred)",
    ]
    return defaults[slot_id - 1]


def read_slot_name(
    image: Image.Image,
    slot: SlotLayout,
    *,
    fixture_dir: Path | None = None,
) -> str:
    crop = crop_slot_name(image, slot)
    if os.environ.get("DROP_PICKER_SIM", "").lower() in ("1", "true", "yes"):
        return _ocr_sim(slot.slot_id)

    fix = _ocr_fixture(slot.slot_id, fixture_dir)
    if fix:
        return fix

    if os.environ.get("DROP_OCR_FIXTURE_ONLY", "").lower() in ("1", "true"):
        return _ocr_sim(slot.slot_id)

    try:
        name = _ocr_tesseract(crop)
        if name:
            return name
    except Exception:
        pass

    return _ocr_sim(slot.slot_id)


def read_all_slots(
    image: Image.Image,
    slots: list[SlotLayout],
    *,
    fixture_dir: Path | None = None,
) -> list[tuple[int, str]]:
    return [
        (s.slot_id, read_slot_name(image, s, fixture_dir=fixture_dir)) for s in slots
    ]


def render_fixture_slot_image(
    layout_slots: list[SlotLayout],
    names: list[str],
    size: tuple[int, int] = (360, 270),
) -> Image.Image:
    """Синтетический care package для тестов OCR/детектора."""
    from modules.drop_picker.slots import load_drop_layout

    layout = load_drop_layout(f"{size[0]}x{size[1]}")
    img = Image.new("RGB", size, (35, 40, 48))
    draw = ImageDraw.Draw(img)
    for x, y, rgb, _ in layout.care_package_probes:
        draw.rectangle((x - 2, y - 2, x + 2, y + 2), fill=rgb)
    for slot, name in zip(layout_slots, names, strict=True):
        r = slot.name_rect
        draw.rectangle((r.x, r.y, r.x + r.w, r.y + r.h), fill=(20, 22, 28))
        short = name[:18] + ("…" if len(name) > 18 else "")
        draw.text((r.x + 2, r.y + 4), short, fill=(220, 220, 220))
    return img
