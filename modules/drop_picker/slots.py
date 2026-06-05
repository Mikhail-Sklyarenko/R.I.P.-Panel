"""4 слота Care Package: регионы OCR и точки клика."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from PIL import Image

from config.paths import get_app_root
from modules.drop_picker.errors import DropPickerError


def _slots_file() -> Path:
    return get_app_root() / "resources" / "ui_nav" / "drop_slots_360x270.yaml"


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class SlotLayout:
    slot_id: int
    name_rect: Rect
    click_x: int
    click_y: int


@dataclass
class DropLayout:
    base_width: int
    base_height: int
    slots: list[SlotLayout]
    confirm_click: tuple[int, int]
    care_package_probes: list[tuple[int, int, tuple[int, int, int], int]]
    scale_x: float = 1.0
    scale_y: float = 1.0


def _parse_resolution(resolution: str) -> tuple[int, int]:
    w, h = resolution.lower().split("x", 1)
    return int(w), int(h)


def load_drop_layout(resolution: str = "360x270") -> DropLayout:
    data = yaml.safe_load(_slots_file().read_text(encoding="utf-8"))
    meta = data.get("meta", {})
    base_w = int(meta.get("base_width", 360))
    base_h = int(meta.get("base_height", 270))
    tw, th = _parse_resolution(resolution)
    sx, sy = tw / base_w, th / base_h

    slots: list[SlotLayout] = []
    for raw in data.get("slots", []):
        nr = raw["name_rect"]
        ck = raw["click"]
        slots.append(
            SlotLayout(
                slot_id=int(raw["id"]),
                name_rect=Rect(
                    int(nr["x"] * sx),
                    int(nr["y"] * sy),
                    int(nr["w"] * sx),
                    int(nr["h"] * sy),
                ),
                click_x=int(ck["x"] * sx),
                click_y=int(ck["y"] * sy),
            )
        )
    if len(slots) != 4:
        raise DropPickerError(f"expected 4 slots, got {len(slots)}")

    probes = []
    for p in data.get("detectors", {}).get("care_package", []):
        probes.append(
            (
                int(p["x"] * sx),
                int(p["y"] * sy),
                tuple(int(c) for c in p["rgb"]),
                int(p.get("tolerance", 50)),
            )
        )
    conf = data["confirm_click"]
    return DropLayout(
        base_width=base_w,
        base_height=base_h,
        slots=slots,
        confirm_click=(int(conf["x"] * sx), int(conf["y"] * sy)),
        care_package_probes=probes,
        scale_x=sx,
        scale_y=sy,
    )


def crop_slot_name(image: Image.Image, slot: SlotLayout) -> Image.Image:
    r = slot.name_rect
    return image.crop((r.x, r.y, r.x + r.w, r.y + r.h))
