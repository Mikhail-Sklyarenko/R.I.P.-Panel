"""ui_nav errors."""

from __future__ import annotations


class UiNavError(Exception):
    pass


class UiNavPlatformError(UiNavError):
    pass


class UiNavTimeoutError(UiNavError):
    pass
