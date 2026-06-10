"""Load patrol YAML scripts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

from .schema import VALID_KEYS, PatrolScript, PatrolStep


class PatrolLoadError(ValueError):
    pass


def _parse_steps(raw_steps: Any) -> List[PatrolStep]:
    if not isinstance(raw_steps, list) or not raw_steps:
        raise PatrolLoadError("steps must be a non-empty list")

    steps: List[PatrolStep] = []
    for i, item in enumerate(raw_steps):
        if not isinstance(item, dict):
            raise PatrolLoadError(f"steps[{i}] must be a mapping")
        key = str(item.get("key", "")).lower()
        if key not in VALID_KEYS:
            raise PatrolLoadError(f"steps[{i}].key must be one of {sorted(VALID_KEYS)}")
        try:
            sec = float(item["sec"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PatrolLoadError(f"steps[{i}].sec must be a number") from exc
        if sec <= 0 or sec > 30:
            raise PatrolLoadError(f"steps[{i}].sec must be between 0 and 30")
        steps.append(PatrolStep(key=key, sec=sec))
    return steps


def parse_patrol_data(data: dict[str, Any]) -> PatrolScript:
    name = str(data.get("name", "patrol"))
    loop = bool(data.get("loop", True))
    steps = _parse_steps(data.get("steps"))
    return PatrolScript(name=name, loop=loop, steps=steps)


def load_patrol(path: Path | str) -> PatrolScript:
    path = Path(path)
    if not path.is_file():
        raise PatrolLoadError(f"patrol file not found: {path}")

    try:
        import yaml
    except ImportError as exc:
        raise PatrolLoadError(
            "PyYAML required for patrol scripts (pip install pyyaml)"
        ) from exc

    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise PatrolLoadError("patrol YAML root must be a mapping")

    return parse_patrol_data(data)
