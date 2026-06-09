"""Парсинг resources/launch_options.txt (defaults из FSM settings.json)."""

from __future__ import annotations

import shlex
from pathlib import Path

from config.paths import get_resources_dir


def _options_file() -> Path:
    return get_resources_dir() / "launch_options.txt"


def _parse_launch_options_file() -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in _options_file().read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip().lower()
            sections[current] = []
            continue
        if current:
            sections[current].append(line)
    return {key: " ".join(lines) for key, lines in sections.items()}


def get_steam_launch_argv(*, classic_ui: bool = False) -> list[str]:
    raw = _parse_launch_options_file().get("steam", "")
    argv = shlex.split(raw, posix=False) if raw else []
    if classic_ui:
        argv = [a for a in argv if a.lower() != "-noreactlogin"]
    return argv


def get_cs2_launch_argv(*, vac_safe: bool = False) -> list[str]:
    if vac_safe:
        return []
    raw = _parse_launch_options_file().get("cs2", "")
    return shlex.split(raw, posix=False) if raw else []
