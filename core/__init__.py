"""Ядро: FSM сессии, события, оркестратор."""

from core.events import EventType
from core.orchestrator import Orchestrator
from core.session_fsm import run_session
from core.session_state import (
    ALLOWED_TRANSITIONS,
    InvalidTransitionError,
    SessionState,
    advance,
    can_transition,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "EventType",
    "InvalidTransitionError",
    "Orchestrator",
    "SessionState",
    "advance",
    "can_transition",
    "run_session",
]
