"""dm_runner errors."""

from __future__ import annotations

from modules.ui_nav.errors import UiNavError, UiNavTimeoutError

DmRunnerError = UiNavError
DmRunnerTimeoutError = UiNavTimeoutError


class DmNavStopped(DmRunnerError):
    """Navigation aborted (operator stop or CS2 window closed)."""


__all__ = ["DmRunnerError", "DmRunnerTimeoutError", "DmNavStopped"]
