"""Operator view of four computers. It reports only states the assignment book has stored."""
from __future__ import annotations

from typing import Any

from core.wingman_fleet.assignments import AssignmentBook, AssignmentError
from core.wingman_fleet.roster import SLOT_LAYOUT


class FleetDesk:
    def __init__(self, book: AssignmentBook):
        self.book = book
        self.preparation_id = ""
        self.error = ""
        self.notice = ""

    def rows(self, links: dict[str, str] | None = None) -> list[dict[str, Any]]:
        links = links or {}
        chosen = {}
        assignment_status = ""
        if self.preparation_id:
            try:
                state = self.book.status(self.preparation_id)
            except AssignmentError:
                state = None
            if state is not None:
                assignment_status = state["status"]
                chosen = {int(slot["slot_id"]): slot for slot in state["slots"]}
        rows = []
        for slot_id, pair_id, role in SLOT_LAYOUT:
            slot = chosen.get(slot_id, {})
            agent_id = str(slot.get("agent_id") or "")
            rows.append({
                "slot_id": slot_id,
                "pair_id": pair_id,
                "role": role.value,
                "agent_id": agent_id,
                "link": links.get(agent_id, "offline") if agent_id else "offline",
                "steam_id64": slot.get("steam_id64", ""),
                "local_account_id": slot.get("local_account_id", ""),
                "reservation_status": slot.get("reservation_status", ""),
                "assignment_status": assignment_status,
                "identity": slot.get("identity_observed", ""),
            })
        return rows

    def accounts_for(self, agent_id: str) -> list[dict[str, Any]]:
        with self.book.store._lock:
            found = self.book.store.db.execute(
                "SELECT local_account_id, steam_id64, display_name, enabled, binding_status, availability_status,"
                " catalog_revision FROM catalog_cache WHERE agent_id=? ORDER BY display_name",
                (agent_id,),
            ).fetchall()
        return [dict(row) for row in found]

    def prepare(self, selections: list[dict[str, Any]], links: dict[str, str]) -> str:
        try:
            self.preparation_id = self.book.draft(selections, links=links)
            self.book.begin_prepare(self.preparation_id)
            queued = self.book.enqueue(self.preparation_id, "prepare")
            state = self.book.status(self.preparation_id)["status"]
            self.error = ""
            self.notice = f"{state}; команд в очереди: {queued}"
        except AssignmentError as exc:
            self.error = str(exc)
            self.notice = ""
        return self.notice

    def commit(self, run_id: str) -> str:
        if not self.preparation_id:
            self.error = "нет подготовки"
            self.notice = ""
            return ""
        try:
            self.book.decide_commit(self.preparation_id, run_id=run_id)
            queued = self.book.enqueue(self.preparation_id, "commit")
            state = self.book.status(self.preparation_id)["status"]
            self.error = ""
            self.notice = f"{state}; команд в очереди: {queued}"
        except AssignmentError as exc:
            self.error = str(exc)
            self.notice = ""
        return self.notice

    def release(self) -> str:
        if not self.preparation_id:
            self.error = "нет подготовки"
            return ""
        try:
            state = self.book.begin_release(self.preparation_id)
            queued = self.book.enqueue(self.preparation_id, "release")
            self.error = ""
            self.notice = f"{state}; команд в очереди: {queued}"
        except AssignmentError as exc:
            self.error = str(exc)
            self.notice = ""
        return self.notice
