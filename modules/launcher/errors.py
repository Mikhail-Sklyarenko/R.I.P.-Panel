"""Ошибки launcher."""

from __future__ import annotations


class LauncherError(Exception):
    pass


class LauncherPlatformError(LauncherError):
    pass
