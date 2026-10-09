"""Parse CS2 `status` / scoreboard text into a MatchFingerprint.

Equal map or load time is ignored. Only a server identity plus connected names
count as evidence of a shared match.
"""
from __future__ import annotations

import re

from core.wingman_fleet.models import MatchFingerprint

_IP = re.compile(r"(?:udp/ip|ip)\s*[:=]\s*(\S+)", re.I)
_HOST = re.compile(r"hostname\s*[:=]\s*(.+)", re.I)
_STEAM = re.compile(r"\[U:1:(\d+)\]")
_QUOTED = re.compile(r'"([^"]{2,32})"')
_HASH = re.compile(r"steam_id_64['\"\s:=]+(7656119\d{10})", re.I)


def parse_status(text: str, *, observed_age_sec: float = 0.0) -> MatchFingerprint | None:
    if not (text or "").strip():
        return None
    token = ""
    ip = _IP.search(text)
    host = _HOST.search(text)
    if ip:
        token = ip.group(1).strip().rstrip(",")
    elif host:
        token = host.group(1).strip()
    names = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.lower().startswith(("udp", "hostname", "version", "os", "players", "# userid")):
            continue
        quoted = _QUOTED.findall(line)
        if quoted:
            names.append(quoted[0])
    if not names:
        names = [m.group(1) for m in _QUOTED.finditer(text)]
    if not token and not names:
        return None
    return MatchFingerprint(token, tuple(dict.fromkeys(names)), observed_age_sec)


def fingerprint_from_names(server_token: str, names: tuple[str, ...], *,
                           observed_age_sec: float = 0.0) -> MatchFingerprint | None:
    names = tuple(n for n in names if n)
    if not server_token and len(names) < 2:
        return None
    return MatchFingerprint(server_token, names, observed_age_sec)
