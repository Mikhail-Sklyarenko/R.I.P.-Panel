"""Decide whether all four agents are connected to one and the same match.

Equal map, load time or score are deliberately ignored: only the server identity
and the connected player list reported by each client count as evidence.
"""
from __future__ import annotations

from enum import Enum

from core.wingman_fleet.models import MatchFingerprint


class Verdict(str, Enum):
    SAME = "same_match_confirmed"
    DIFFERENT = "different_match_confirmed"
    INSUFFICIENT = "insufficient_evidence"


WINGMAN_PLAYERS = 4
MAX_FINGERPRINT_AGE_SEC = 30.0


def _norm(name: str) -> str:
    return " ".join(name.casefold().split())


def judge(fingerprints: dict[str, MatchFingerprint | None], expected_names: dict[str, str]) -> tuple[Verdict, str]:
    """`expected_names` maps agent_id -> display name of its account."""
    expected = {_norm(n) for n in expected_names.values()}
    if len(expected) != len(expected_names):
        return Verdict.INSUFFICIENT, "duplicate display names make roster proof ambiguous"
    tokens: set[str] = set()
    complete = 0
    for agent_id in expected_names:
        fp = fingerprints.get(agent_id)
        if fp is None or fp.observed_age_sec > MAX_FINGERPRINT_AGE_SEC:
            continue
        seen = {_norm(p) for p in fp.players}
        if fp.server_token:
            tokens.add(fp.server_token)
        if len(seen) >= WINGMAN_PLAYERS and not expected <= seen:
            # A full server without our other pair is positive proof of a different match.
            missing = sorted(expected - seen)
            return Verdict.DIFFERENT, f"{agent_id}: full roster without {missing}"
        if expected <= seen:
            complete += 1
    if len(tokens) > 1:
        return Verdict.DIFFERENT, f"different server tokens: {sorted(tokens)}"
    if complete == len(expected_names):
        return Verdict.SAME, "all clients list all four expected players" + (
            f" on {next(iter(tokens))}" if tokens else "")
    return Verdict.INSUFFICIENT, f"{complete}/{len(expected_names)} complete rosters"
