"""Single owner of keyboard/mouse on a farm PC: UI automation XOR gameplay."""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from enum import Enum
from typing import Callable, Iterator

_log = logging.getLogger(__name__)


class InputOwner(str, Enum):
    NONE = "none"
    UI = "ui"
    GAMEPLAY = "gameplay"


class InputBusy(RuntimeError):
    pass


def _default_release() -> None:
    from modules.ui_nav.actions import release_all_inputs
    release_all_inputs()


class InputSupervisor:
    def __init__(self, release: Callable[[], None] | None = None):
        self._release = release or _default_release
        self._lock = threading.RLock()
        self._owner = InputOwner.NONE
        self._purpose = ""
        self.gameplay_attempt = ""

    @property
    def owner(self) -> InputOwner:
        return self._owner

    def describe(self) -> str:
        return self._owner.value if not self._purpose else f"{self._owner.value}:{self._purpose}"

    @contextmanager
    def ui(self, purpose: str) -> Iterator[None]:
        """Hold inputs for one UI automation step; gameplay must already be stopped."""
        with self._lock:
            if self._owner is not InputOwner.NONE:
                raise InputBusy(f"inputs owned by {self.describe()}")
            self._owner, self._purpose = InputOwner.UI, purpose
        try:
            yield
        finally:
            with self._lock:
                self._owner, self._purpose = InputOwner.NONE, ""
            self.release_all()

    def grant_gameplay(self, attempt_id: str) -> bool:
        with self._lock:
            if self._owner is InputOwner.UI:
                return False
            self._owner, self._purpose, self.gameplay_attempt = InputOwner.GAMEPLAY, attempt_id, attempt_id
            return True

    def revoke_gameplay(self) -> None:
        with self._lock:
            was = self._owner is InputOwner.GAMEPLAY
            if was:
                self._owner, self._purpose, self.gameplay_attempt = InputOwner.NONE, "", ""
        if was:
            self.release_all()

    def release_all(self) -> None:
        try:
            self._release()
        except Exception:
            _log.exception("input release failed")
