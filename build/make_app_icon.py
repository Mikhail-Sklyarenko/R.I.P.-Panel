#!/usr/bin/env python3
"""Regenerate farm_panel.ico from resources/app/farm_panel.png."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "resources" / "app" / "farm_panel.png"
DST = ROOT / "resources" / "app" / "farm_panel.ico"
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> None:
    if not SRC.is_file():
        raise SystemExit(f"Missing source icon: {SRC}")
    img = Image.open(SRC).convert("RGBA")
    img.save(DST, format="ICO", sizes=SIZES)
    print(f"Wrote {DST}")


if __name__ == "__main__":
    main()
