#!/usr/bin/env python3
"""Download radar PNG + meta.json for a CS2 map from cs2-map-icons."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/MurkyYT/cs2-map-icons/main"
MAP_DEFAULTS = {
    "de_dust2": {
        "display_name": "Dust II",
        "pos_x": -2476,
        "pos_y": 3239,
        "scale": 4.4,
        "rotate": 1,
        "zoom": 1.1,
        "landmarks": {
            "t_spawn": {"x": 0.39, "y": 0.91},
            "ct_spawn": {"x": 0.62, "y": 0.21},
            "bombsite_a": {"x": 0.80, "y": 0.16},
            "bombsite_b": {"x": 0.21, "y": 0.12},
            "mid": {"x": 0.52, "y": 0.48},
        },
    },
    "de_mirage": {
        "display_name": "Mirage",
        "pos_x": -3230,
        "pos_y": 1713,
        "scale": 5.0,
        "rotate": 0,
        "zoom": 0.0,
        "landmarks": {
            "t_spawn": {"x": 0.87, "y": 0.36},
            "ct_spawn": {"x": 0.28, "y": 0.70},
            "bombsite_a": {"x": 0.54, "y": 0.76},
            "bombsite_b": {"x": 0.23, "y": 0.28},
            "mid": {"x": 0.49, "y": 0.52},
            "connector": {"x": 0.49, "y": 0.40},
            "palace": {"x": 0.62, "y": 0.62},
        },
    },
}


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"fetch {url}")
    with urllib.request.urlopen(url, timeout=60) as resp:
        dest.write_bytes(resp.read())
    print(f"wrote {dest}")


def _parse_radar_txt(text: str) -> dict[str, float | int]:
    out: dict[str, float | int] = {}
    for key in ("pos_x", "pos_y", "scale", "rotate", "zoom"):
        m = re.search(rf'"{key}"\s+"([^"]+)"', text)
        if m:
            val: float | int = float(m.group(1))
            if key in ("pos_x", "pos_y", "rotate"):
                val = int(float(m.group(1)))
            out[key] = val
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--map-id",
        default="de_dust2",
        help="Map id folder name (default: de_dust2)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "resources" / "nav" / "maps",
    )
    args = parser.parse_args()
    map_id = args.map_id
    out_dir = args.out / map_id
    radar_url = f"{BASE}/images/radars/{map_id}_radar_psd.png"
    info_url = f"{BASE}/data/radar_info/{map_id}.txt"

    try:
        _download(radar_url, out_dir / "radar.png")
    except Exception as exc:
        print(f"radar download failed: {exc}", file=sys.stderr)
        return 1

    defaults = MAP_DEFAULTS.get(map_id, {})
    meta: dict = {
        "map_id": map_id,
        "script_id": map_id.replace("de_", ""),
        "display_name": defaults.get("display_name", map_id),
        "radar_size_px": 1024,
        "source": "cs2-map-icons",
        "source_url": "https://github.com/MurkyYT/cs2-map-icons",
        "radar_info_url": info_url,
    }
    try:
        with urllib.request.urlopen(info_url, timeout=30) as resp:
            parsed = _parse_radar_txt(resp.read().decode("utf-8", errors="replace"))
        meta.update(parsed)
    except Exception as exc:
        print(f"radar_info fetch failed ({exc}); using defaults", file=sys.stderr)
        meta.update({k: defaults[k] for k in ("pos_x", "pos_y", "scale", "rotate", "zoom") if k in defaults})

    if "landmarks" in defaults:
        meta["landmarks"] = defaults["landmarks"]

    meta_path = out_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
