"""Utils / recovery errors."""

from __future__ import annotations


class UtilsError(Exception):
    pass


class UtilsPlatformError(UtilsError):
    """Win32-only operation on non-Windows."""
