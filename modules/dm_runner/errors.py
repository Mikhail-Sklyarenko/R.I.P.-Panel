"""dm_runner errors."""

from __future__ import annotations

from modules.ui_nav.errors import UiNavError, UiNavTimeoutError

DmRunnerError = UiNavError
DmRunnerTimeoutError = UiNavTimeoutError

__all__ = ["DmRunnerError", "DmRunnerTimeoutError"]
