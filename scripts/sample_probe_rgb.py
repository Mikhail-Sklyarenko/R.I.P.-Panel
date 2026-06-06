#!/usr/bin/env python3
"""Sample RGB at (x, y) from a CS2 client-area screenshot for probe calibration."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print RGB at pixel (x, y) in a PNG (client-area capture)."
    )
    parser.add_argument("image", type=Path, help="Screenshot path, e.g. wait_main_menu_84.png")
    parser.add_argument("x", type=int, help="X coordinate")
    parser.add_argument("y", type=int, help="Y coordinate")
    args = parser.parse_args(argv)

    if not args.image.is_file():
        print(f"error: file not found: {args.image}", file=sys.stderr)
        return 1

    img = Image.open(args.image).convert("RGB")
    if args.x < 0 or args.y < 0 or args.x >= img.width or args.y >= img.height:
        print(
            f"error: ({args.x}, {args.y}) out of bounds for {img.width}x{img.height}",
            file=sys.stderr,
        )
        return 1

    r, g, b = img.getpixel((args.x, args.y))
    print(f"image: {args.image} ({img.width}x{img.height})")
    print(f"pixel @ ({args.x}, {args.y}): rgb [{r}, {g}, {b}]")
    print(f"yaml: {{x: {args.x}, y: {args.y}, rgb: [{r}, {g}, {b}], tolerance: 70}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
