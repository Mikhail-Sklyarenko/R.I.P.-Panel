"""Operator view of four computers. It reports only states the assignment book has stored."""
from __future__ import annotations

from typing import Any

from core.wingman_fleet.assignments import AssignmentBook, AssignmentError
from core.wingman_fleet.roster import SLOT_LAYOUT


class FleetDesk:
    def __init__(self, book: AssignmentBook):
        self.book = book
        self.preparation_id = book.current()
        self.error = ""
        self.notice = book.status(self.preparation_id)["status"] if self.preparation_id else ""
        self.selection: dict[int, dict[str, Any]] = {}

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
                "verification_status": slot.get("verification_status", ""),
                "verification_error": slot.get("verification_error", ""),
                "registration": self.book.registration_state(agent_id) if agent_id else "unregistered",
                "display_name": slot.get("display_name", ""),
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

    def choose(self, slot_id: int, agent_id: str, local_account_id: str) -> str:
        match = next(
            (item for item in self.accounts_for(agent_id) if item["local_account_id"] == local_account_id),
            None,
        )
        if match is None:
            self.selection.pop(slot_id, None)
            self.error = "аккаунт не найден в актуальном каталоге этого компьютера"
            self.notice = ""
            return self.error
        self.selection[slot_id] = {
            "slot_id": slot_id,
            "agent_id": agent_id,
            "local_account_id": match["local_account_id"],
            "steam_id64": match["steam_id64"],
            "expected_catalog_revision": int(match["catalog_revision"]),
            "display_name": match["display_name"],
        }
        self.error = ""
        return match["local_account_id"]

    def prepare(self, selections: list[dict[str, Any]] | None = None, links: dict[str, str] | None = None) -> str:
        chosen = list(selections) if selections is not None else list(self.selection.values())
        if len(chosen) != 4 or any(not item.get("local_account_id") for item in chosen):
            self.error = "выберите аккаунт на каждом из четырёх компьютеров"
            self.notice = ""
            return ""
        links = links or {}
        try:
            self.preparation_id = self.book.draft(chosen, links=links)
            self.book.begin_prepare(self.preparation_id, links)
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

    def enroll(self, agent_id: str) -> str:
        try:
            code = self.book.open_enrollment(agent_id)
        except AssignmentError as exc:
            self.error = str(exc)
            self.notice = ""
            return ""
        self.error = ""
        self.notice = f"код для {agent_id}: {code}"
        return code

    def revoke(self, agent_id: str) -> str:
        self.book.revoke_agent(agent_id)
        self.error = ""
        self.notice = f"{agent_id}: регистрация отозвана"
        return self.notice

    def verify(self) -> str:
        if not self.preparation_id:
            self.error = "нет подготовки"
            self.notice = ""
            return ""
        try:
            queued = self.book.enqueue(self.preparation_id, "verify")
        except AssignmentError as exc:
            self.error = str(exc)
            self.notice = ""
            return ""
        self.error = ""
        self.notice = f"проверка отправлена; команд: {queued}"
        return self.notice

    def reconcile(self) -> str:
        if not self.preparation_id:
            self.error = "нет подготовки"
            self.notice = ""
            return ""
        try:
            state = self.book.reconcile(self.preparation_id)
            queued = self.book.enqueue(self.preparation_id, "reconcile")
        except AssignmentError as exc:
            self.error = str(exc)
            self.notice = ""
            return ""
        self.error = ""
        self.notice = f"{state}; команд: {queued}"
        return self.notice

    def diagnostics(self) -> str:
        lines = [self.notice or self.error or "нет активного сообщения"]
        if self.preparation_id:
            try:
                state = self.book.status(self.preparation_id)
            except AssignmentError as exc:
                lines.append(str(exc))
            else:
                lines.append(
                    f"подготовка {state['status']} run={state['run_id'] or '—'} {state['last_error']}"
                )
        for row in self.rows():
            lines.append(
                f"PC-0{row['slot_id']} {row['agent_id'] or '—'} регистрация={row['registration']} "
                f"связь={row['link']} проверка={row['verification_status'] or 'нет'} "
                f"резерв={row['reservation_status'] or 'нет'} {row['verification_error']}"
            )
        self.notice = "\n".join(lines)
        self.error = ""
        return self.notice
