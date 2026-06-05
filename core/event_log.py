"""Append-only events.jsonl (data/logs/)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from config.paths import get_events_log_path
from core.events import EventType
from core.session_state import SessionState


def append_event(
    event: EventType,
    *,
    login: str,
    state: SessionState | None = None,
    detail: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    path = get_events_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": event.value,
        "login": login,
    }
    if state is not None:
        record["state"] = state.value
    if detail:
        record["detail"] = detail
    if extra:
        record.update(extra)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
