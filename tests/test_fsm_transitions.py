"""Тесты FSM сессии (mock, без UI и Steam)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.events import EventType
from core.fsm import apply_event
from core.session_state import (
    InvalidTransitionError,
    SessionState,
    advance,
    can_transition,
)


def test_queued_to_failed_allowed() -> None:
    assert can_transition(SessionState.QUEUED, SessionState.FAILED)


def test_queued_to_failed_advance() -> None:
    with patch("core.session_state.advance", wraps=advance) as mock_advance:
        result = mock_advance(SessionState.QUEUED, SessionState.FAILED)
    assert result is SessionState.FAILED
    mock_advance.assert_called_once_with(SessionState.QUEUED, SessionState.FAILED)


def test_queued_to_failed_via_event() -> None:
    state = apply_event(SessionState.QUEUED, EventType.SESSION_FAILED)
    assert state is SessionState.FAILED


def test_queued_to_done_invalid() -> None:
    with pytest.raises(InvalidTransitionError):
        advance(SessionState.QUEUED, SessionState.DONE)
