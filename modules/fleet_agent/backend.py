"""Backend contract between the agent service and the machine it controls."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Protocol

from core.wingman_fleet.models import Command, CommandResult, Observation


@dataclass
class ExecContext:
    """Per-command context: cooperative cancel and the coordinator's clock."""
    cancel: threading.Event
    coordinator_time: Callable[[], float]
    gameplay_attempt: Callable[[], str]


class GameBackend(Protocol):
    def observe(self) -> Observation:
        """Fresh local evidence; identity/build fields are filled by the service."""

    def execute(self, cmd: Command, ctx: ExecContext) -> CommandResult:
        """Run one command to a verified outcome; never raise for expected failures."""

    def set_gameplay(self, attempt_id: str) -> None:
        """Lease state each tick: non-empty = this attempt may play, empty = revoke now."""

    def safe_stop(self, reason: str) -> None:
        """Release every input and stop the worker; must not raise."""
