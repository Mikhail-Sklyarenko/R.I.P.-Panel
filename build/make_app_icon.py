#!/usr/bin/env python3
"""Regenerate farm_panel.ico from resources/app/farm_panel.png."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "resources" / "app" / "farm_panel.png"
DST = ROOT / "resources" / "app" / "farm_panel.ico"
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def _flatten_on_black(img: Image.Image) -> Image.Image:
    """Windows shell icons are more reliable with opaque RGB frames."""
    rgba = img.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    return Image.alpha_composite(background, rgba).convert("RGB")


def save_windows_ico(img: Image.Image, path: Path, sizes: list[tuple[int, int]]) -> None:
    base = _flatten_on_black(img)
    frames = [base.resize(size, Image.Resampling.LANCZOS) for size in sizes]
    frames[0].save(
        path,
        format="ICO",
        sizes=[frame.size for frame in frames],
        append_images=frames[1:],
    )


def main() -> None:
    if not SRC.is_file():
        raise SystemExit(f"Missing source icon: {SRC}")
    save_windows_ico(Image.open(SRC), DST, SIZES)
    print(f"Wrote {DST}")


if __name__ == "__main__":
    main()
