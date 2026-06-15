"""Build map template PNGs from operator calibration screenshots."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

SB_MAP = (450, 50, 220, 36)
READY = (360, 302, 520, 32)

SOURCES = {
    "sb_mirage.png": ("mirage_tab.png", SB_MAP),
    "sb_dust2.png": ("dust2_tab.png", SB_MAP),
    "ready_mirage.png": ("mirage_ready.png", READY),
    "ready_dust2.png": ("dust2_ready.png", READY),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "tests"
        / "fixtures"
        / "csgobot_map",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "resources"
        / "csgobot"
        / "map_templates",
    )
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    for out_name, (src_name, rect) in SOURCES.items():
        src = args.fixtures / src_name
        if not src.is_file():
            raise SystemExit(f"missing fixture: {src}")
        img = Image.open(src).convert("RGB").resize(
            (1280, 720),
            Image.Resampling.LANCZOS,
        )
        x, y, w, h = rect
        crop = img.crop((x, y, x + w, y + h))
        crop.save(args.out / out_name)
        print(f"wrote {args.out / out_name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
