"""Persistent fleet roster (data/wingman_fleet.json): four slots, two fixed pairs.

Slot order is permanent: 1 leader P1, 2 follower P1, 3 leader P2, 4 follower P2.
A missing account never shifts the others and a follower is never promoted.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.wingman_fleet.models import AccountProfile, PairProfile, RetryPolicy, Role, RunPlan, new_id

SLOT_LAYOUT = ((1, "pair-1", Role.LEADER), (2, "pair-1", Role.FOLLOWER),
               (3, "pair-2", Role.LEADER), (4, "pair-2", Role.FOLLOWER))


class RosterError(ValueError):
    pass


@dataclass
class FleetRoster:
    token: str = ""
    port: int = 8790
    slots: dict[int, dict[str, Any]] = field(default_factory=dict)
    retry: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "FleetRoster":
        if not path.is_file():
            return cls(token=secrets.token_hex(24))
        d = json.loads(path.read_text(encoding="utf-8"))
        slots = {int(k): v for k, v in (d.get("slots") or {}).items()}
        return cls(str(d.get("token") or secrets.token_hex(24)), int(d.get("port", 8790)), slots,
                   dict(d.get("retry") or {}))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"token": self.token, "port": self.port,
                                   "slots": {str(k): v for k, v in sorted(self.slots.items())},
                                   "retry": self.retry}, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def set_slot(self, slot: int, *, agent_id: str, steam_id64: str, display_name: str,
                 friend_code: str = "") -> None:
        if slot not in {s for s, _, _ in SLOT_LAYOUT}:
            raise RosterError(f"slot must be 1..4, got {slot}")
        steam_id64 = steam_id64.strip()
        if not steam_id64.isdigit() or len(steam_id64) != 17:
            raise RosterError("SteamID64 must contain 17 digits")
        for other, entry in self.slots.items():
            if other != slot and (entry.get("agent_id") == agent_id or entry.get("steam_id64") == steam_id64):
                raise RosterError(f"agent or account already assigned to slot {other}")
        self.slots[slot] = {"agent_id": agent_id.strip(), "steam_id64": steam_id64,
                            "display_name": display_name.strip(), "friend_code": friend_code.strip()}

    def accounts(self) -> dict[int, AccountProfile]:
        out = {}
        for slot, pair_id, role in SLOT_LAYOUT:
            e = self.slots.get(slot)
            if not e:
                continue
            out[slot] = AccountProfile(f"slot-{slot}", e["steam_id64"], e["display_name"],
                                       e.get("friend_code", ""), e["agent_id"], pair_id, role)
        return out

    def validate(self) -> list[str]:
        problems = []
        accounts = self.accounts()
        for slot, _, role in SLOT_LAYOUT:
            if slot not in accounts:
                problems.append(f"слот {slot} ({role.value}) не назначен")
        names = [a.display_name.casefold() for a in accounts.values()]
        if len(set(names)) != len(names):
            problems.append("отображаемые имена аккаунтов должны различаться (доказательство общего матча)")
        if any(not a.display_name for a in accounts.values()):
            problems.append("у каждого аккаунта должно быть отображаемое имя CS2")
        return problems

    def build_plan(self, *, build_version: str, resource_manifest: str, now: float | None = None) -> RunPlan:
        problems = self.validate()
        if problems:
            raise RosterError("; ".join(problems))
        a = self.accounts()
        pairs = (PairProfile("pair-1", 1, a[1], a[2]), PairProfile("pair-2", 2, a[3], a[4]))
        return RunPlan(new_id("run"), now or time.time(), pairs, build_version, resource_manifest,
                       RetryPolicy.from_dict(self.retry))


def resource_manifest_hash(paths: list[Path]) -> str:
    """Stable digest of the assets every agent must share (models, Inferno profile, HUD)."""
    digest = hashlib.sha256()
    for root in sorted(paths):
        if not root.exists():
            digest.update(f"missing:{root.name}".encode())
            continue
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for p in files:
            digest.update((p.name if p == root else p.relative_to(root).as_posix()).encode())
            digest.update(hashlib.sha256(p.read_bytes()).digest())
    return digest.hexdigest()[:16]
