"""Map name → patrol script id."""

from __future__ import annotations

import re
from typing import Literal, Optional

MapScriptId = Literal["dust2", "mirage", "inferno", "vertigo", "cache", "generic_dm"]

_KNOWN_SCRIPTS: tuple[MapScriptId, ...] = ("dust2", "mirage", "inferno", "vertigo", "cache", "generic_dm")

_DUST2_RE = re.compile(r"dust\s*(?:ii|2|_ii)\b", re.IGNORECASE)
_INFERNO_RE = re.compile(r"\binferno\b", re.IGNORECASE)
_MIRAGE_RE = re.compile(r"\bmirage\b", re.IGNORECASE)


def normalize_map_text(text: str) -> str:
    return " ".join(text.replace("|", " ").replace("•", " ").split()).strip()


def parse_map_script(text: str) -> Optional[MapScriptId]:
    """
    Parse OCR / HUD text into a patrol script id.

    Returns dust2, mirage, inferno, or None when unknown (caller keeps generic_dm).
    """
    norm = normalize_map_text(text).lower()
    if not norm:
        return None
    if _DUST2_RE.search(norm):
        return "dust2"
    if re.search(r"\bvertigo\b", norm.replace("de_", ""), re.IGNORECASE):
        return "vertigo"
    if re.search(r"\bcache\b", norm.replace("de_", ""), re.IGNORECASE):
        return "cache"
    if _INFERNO_RE.search(norm.replace("de_", "")):
        return "inferno"
    if _MIRAGE_RE.search(norm):
        return "mirage"
    return None


def is_map_script_id(value: str) -> bool:
    return value in _KNOWN_SCRIPTS
