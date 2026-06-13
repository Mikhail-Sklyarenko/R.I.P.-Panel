"""Load HUD team color probes from YAML."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class TeamProbeLoadError(ValueError):
    pass


@dataclass(frozen=True)
class ColorProbe:
    x: int
    y: int
    rgb: tuple[int, int, int]
    tolerance: int = 50


@dataclass(frozen=True)
class TeamProbeSet:
    ct: tuple[ColorProbe, ...]
    t: tuple[ColorProbe, ...]
    base_width: int = 1280
    base_height: int = 720


def _parse_probe(raw: Any, team: str, index: int) -> ColorProbe:
    if not isinstance(raw, dict):
        raise TeamProbeLoadError(f"{team}[{index}] must be a mapping")
    try:
        x = int(raw["x"])
        y = int(raw["y"])
        rgb_raw = raw["rgb"]
        rgb = (int(rgb_raw[0]), int(rgb_raw[1]), int(rgb_raw[2]))
        tolerance = int(raw.get("tolerance", 50))
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise TeamProbeLoadError(f"{team}[{index}] invalid probe fields") from exc
    if tolerance < 0 or tolerance > 120:
        raise TeamProbeLoadError(f"{team}[{index}].tolerance out of range")
    return ColorProbe(x=x, y=y, rgb=rgb, tolerance=tolerance)


def parse_team_probe_data(data: dict[str, Any]) -> TeamProbeSet:
    meta = data.get("meta") or {}
    base_width = int(meta.get("base_width", 1280))
    base_height = int(meta.get("base_height", 720))

    ct_raw = data.get("ct")
    t_raw = data.get("t")
    if not isinstance(ct_raw, list) or not ct_raw:
        raise TeamProbeLoadError("ct must be a non-empty list")
    if not isinstance(t_raw, list) or not t_raw:
        raise TeamProbeLoadError("t must be a non-empty list")

    ct = tuple(_parse_probe(item, "ct", i) for i, item in enumerate(ct_raw))
    t = tuple(_parse_probe(item, "t", i) for i, item in enumerate(t_raw))
    return TeamProbeSet(ct=ct, t=t, base_width=base_width, base_height=base_height)


def load_team_probes(path: Path | str) -> TeamProbeSet:
    path = Path(path)
    if not path.is_file():
        raise TeamProbeLoadError(f"team probes file not found: {path}")

    try:
        import yaml
    except ImportError as exc:
        raise TeamProbeLoadError(
            "PyYAML required for team probes (pip install pyyaml)"
        ) from exc

    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise TeamProbeLoadError("team probes YAML root must be a mapping")

    return parse_team_probe_data(data)
